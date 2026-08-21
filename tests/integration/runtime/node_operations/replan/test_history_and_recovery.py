from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    AssignmentModel,
    DispatchTurnModel,
    MemberConfigurationModel,
    MemberModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from oh_my_subagents.runtime.contracts import ReplanSuccess
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.dispatch.ordinary_continuation import OrdinaryOpeningResult
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from oh_my_subagents.runtime.replan.continuation import continue_committed_replan
from tests.helpers.disjoint_team_runtime import create_runtime_opening_dependencies
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class _RemovedHistoryObservation:
    opening_outcome: str
    child_exists: bool
    nested_exists: bool
    child_assignment_outcome: str | None
    historical_configuration_member_ids: frozenset[str]
    current_member_ids: tuple[str, ...]
    team_revision_count: int
    transition_count: int


@dataclass(frozen=True, slots=True)
class _FirstReplayObservation:
    listed_member_id: str
    unlisted_member_id: str
    successor_dispatch_id: str
    unlisted_configuration_id: str
    unlisted_branch_basis_id: str


@dataclass(frozen=True, slots=True)
class _ReplayHistoryObservation:
    opening_outcome: str
    successor_dispatch_id: str | None
    repeated_opening_outcome: str
    current_member_ids: tuple[str, ...]
    unlisted_parent_member_id: str | None
    unlisted_configuration_id: str
    unlisted_branch_basis_id: str
    transition_count: int
    team_revision_count: int
    member_count: int
    original_activity_revision: int | None
    first_successor_count: int
    second_successor_count: int


async def test_recursive_replan_preserves_removed_history_and_rejects_busy_or_noop_mutation(
    tmp_path: Path,
) -> None:
    dependencies = create_runtime_opening_dependencies()
    async with seeded_executor(tmp_path, suffix="replan-history") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        await _assert_busy_and_noop_updates_write_no_transition(
            executor,
            session_factory,
            ids,
            scope,
        )
        nested_id, update_successor_id = await _add_nested_member_and_continue(
            executor,
            session_factory,
            ids,
            scope,
            dependencies,
        )
        observed = await _remove_subtree_and_read_history(
            executor,
            session_factory,
            ids,
            nested_id=nested_id,
            source_dispatch_id=update_successor_id,
            dependencies=dependencies,
        )

    assert observed.opening_outcome == "opened"
    assert observed.child_exists and observed.nested_exists
    assert observed.child_assignment_outcome == "blocked"
    assert observed.historical_configuration_member_ids == {
        ids.child_member_id,
        nested_id,
    }
    assert observed.current_member_ids == (ids.root_member_id,)
    assert observed.team_revision_count == 3
    assert observed.transition_count == 2


async def _assert_busy_and_noop_updates_write_no_transition(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    scope: NodeOperationScope,
) -> None:
    with pytest.raises(RuntimeOperationError) as busy:
        await executor.execute(
            scope=scope,
            operation_name="update_child",
            arguments={
                "id": ids.child_member_id,
                "patch": {"title": "Busy child"},
            },
        )
    assert busy.value.code == OperationFailureCode.ILLEGAL_STATE
    async with session_factory() as session:
        assert await _count(session, ReplanTransitionModel) == 0
        await make_seed_child_terminal(session, ids)
    with pytest.raises(RuntimeOperationError) as no_op:
        await executor.execute(
            scope=scope,
            operation_name="update_child",
            arguments={
                "id": ids.child_member_id,
                "patch": {"title": "Child Member"},
            },
        )
    assert no_op.value.code == OperationFailureCode.ILLEGAL_STATE


async def _add_nested_member_and_continue(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    scope: NodeOperationScope,
    dependencies: DispatchOpeningDependencies,
) -> tuple[str, str]:
    updated = ReplanSuccess.model_validate(
        await executor.execute(
            scope=scope,
            operation_name="update_child",
            arguments={
                "id": ids.child_member_id,
                "patch": {
                    "children": [
                        {
                            "title": "Nested reviewer",
                            "instruction": "Review the bounded result.",
                        }
                    ]
                },
            },
        )
    )
    assert len(updated.created_ids) == 1
    assert updated.updated_ids == ()
    async with session_factory() as session:
        transition = await _transition_for_source(session, ids.current_dispatch_id)
        opening = await _continue_transition(
            session,
            transition.replan_transition_id,
            dependencies,
        )
    assert opening.outcome == "opened"
    assert opening.dispatch_id is not None
    return updated.created_ids[0], opening.dispatch_id


async def _remove_subtree_and_read_history(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    nested_id: str,
    source_dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
) -> _RemovedHistoryObservation:
    removed = ReplanSuccess.model_validate(
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=source_dispatch_id,
            ),
            operation_name="remove_child",
            arguments={"id": ids.child_member_id},
        )
    )
    assert removed.removed_ids == (ids.child_member_id, nested_id)
    async with session_factory() as session:
        transition = await _transition_for_source(session, source_dispatch_id)
        opening = await _continue_transition(
            session,
            transition.replan_transition_id,
            dependencies,
        )
        task = await session.get(TaskModel, ids.task_id)
        assert task is not None and task.current_team_revision_id is not None
        child = await session.get(MemberModel, (ids.task_id, ids.child_member_id))
        nested = await session.get(MemberModel, (ids.task_id, nested_id))
        child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
        configurations = tuple(
            await session.scalars(
                select(MemberConfigurationModel).where(
                    MemberConfigurationModel.task_id == ids.task_id,
                    MemberConfigurationModel.member_id.in_((ids.child_member_id, nested_id)),
                )
            )
        )
        current_member_ids = tuple(
            await session.scalars(
                select(TeamRevisionMemberModel.member_id)
                .where(
                    TeamRevisionMemberModel.task_id == ids.task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                )
                .order_by(TeamRevisionMemberModel.preorder_index)
            )
        )
        return _RemovedHistoryObservation(
            opening_outcome=opening.outcome,
            child_exists=child is not None,
            nested_exists=nested is not None,
            child_assignment_outcome=(
                child_assignment.terminal_outcome if child_assignment is not None else None
            ),
            historical_configuration_member_ids=frozenset(row.member_id for row in configurations),
            current_member_ids=current_member_ids,
            team_revision_count=await _count(session, TeamRevisionModel),
            transition_count=await _count(session, ReplanTransitionModel),
        )


async def test_replan_replay_is_exact_and_nested_patch_preserves_unlisted_sibling(
    tmp_path: Path,
) -> None:
    dependencies = create_runtime_opening_dependencies()
    async with seeded_executor(tmp_path, suffix="replan-exact-replay") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        first = await _commit_and_replay_first_nested_patch(
            executor,
            session_factory,
            ids,
            dependencies,
        )
        await _commit_listed_nested_patch(executor, ids, first)
        observed = await _continue_second_patch_and_read_history(
            session_factory,
            ids,
            first,
            dependencies,
        )

    assert observed.opening_outcome == "opened"
    assert observed.successor_dispatch_id is not None
    assert observed.repeated_opening_outcome == "skipped"
    assert observed.current_member_ids == (
        ids.root_member_id,
        ids.child_member_id,
        first.listed_member_id,
        first.unlisted_member_id,
    )
    assert observed.unlisted_parent_member_id == ids.child_member_id
    assert observed.unlisted_configuration_id == first.unlisted_configuration_id
    assert observed.unlisted_branch_basis_id == first.unlisted_branch_basis_id
    assert observed.transition_count == 2
    assert observed.team_revision_count == 3
    assert observed.member_count == 4
    assert observed.original_activity_revision == 1
    assert observed.first_successor_count == 1
    assert observed.second_successor_count == 1


async def _commit_and_replay_first_nested_patch(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    dependencies: DispatchOpeningDependencies,
) -> _FirstReplayObservation:
    scope = NodeOperationScope(
        task_id=ids.task_id,
        dispatch_id=ids.current_dispatch_id,
        provider_start_revision=0,
    )
    arguments = {
        "id": ids.child_member_id,
        "patch": {
            "children": [
                {"title": "Listed nested member"},
                {"title": "Unlisted nested sibling"},
            ]
        },
    }
    first_result = ReplanSuccess.model_validate(
        await executor.execute(
            scope=scope,
            operation_name="update_child",
            arguments=arguments,
        )
    )
    replayed_result = ReplanSuccess.model_validate(
        await executor.execute(
            scope=scope,
            operation_name="update_child",
            arguments=arguments,
        )
    )
    assert replayed_result == first_result
    with pytest.raises(RuntimeOperationError):
        await executor.execute(
            scope=scope,
            operation_name="update_child",
            arguments={
                "id": ids.child_member_id,
                "patch": {"instruction": "This is not the committed request."},
            },
        )
    assert len(first_result.created_ids) == 2
    listed_id, unlisted_id = first_result.created_ids
    async with session_factory() as session:
        transition = await _transition_for_source(session, ids.current_dispatch_id)
        opening = await _continue_transition(
            session,
            transition.replan_transition_id,
            dependencies,
        )
        repeated = await _continue_transition(
            session,
            transition.replan_transition_id,
            dependencies,
        )
    assert opening.outcome == "opened"
    assert opening.dispatch_id is not None
    assert repeated.outcome == "skipped"
    unlisted = await _current_member_selection(session_factory, ids, unlisted_id)
    return _FirstReplayObservation(
        listed_member_id=listed_id,
        unlisted_member_id=unlisted_id,
        successor_dispatch_id=opening.dispatch_id,
        unlisted_configuration_id=unlisted.member_configuration_id,
        unlisted_branch_basis_id=unlisted.member_branch_basis_id,
    )


async def _current_member_selection(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    member_id: str,
) -> TeamRevisionMemberModel:
    async with session_factory() as session:
        task = await session.get(TaskModel, ids.task_id)
        assert task is not None and task.current_team_revision_id is not None
        member = await session.scalar(
            select(TeamRevisionMemberModel).where(
                TeamRevisionMemberModel.task_id == ids.task_id,
                TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                TeamRevisionMemberModel.member_id == member_id,
            )
        )
    assert member is not None
    return cast(TeamRevisionMemberModel, member)


async def _commit_listed_nested_patch(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
    first: _FirstReplayObservation,
) -> None:
    result = ReplanSuccess.model_validate(
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=first.successor_dispatch_id,
            ),
            operation_name="update_child",
            arguments={
                "id": ids.child_member_id,
                "patch": {
                    "children": [
                        {
                            "id": first.listed_member_id,
                            "instruction": "Review the exact replay proof.",
                        }
                    ]
                },
            },
        )
    )
    assert result.updated_ids == (first.listed_member_id,)
    assert result.created_ids == ()


async def _continue_second_patch_and_read_history(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    first: _FirstReplayObservation,
    dependencies: DispatchOpeningDependencies,
) -> _ReplayHistoryObservation:
    async with session_factory() as session:
        transition = await _transition_for_source(
            session,
            first.successor_dispatch_id,
        )
        opening = await _continue_transition(
            session,
            transition.replan_transition_id,
            dependencies,
        )
        repeated = await _continue_transition(
            session,
            transition.replan_transition_id,
            dependencies,
        )
        task = await session.get(TaskModel, ids.task_id)
        assert task is not None and task.current_team_revision_id is not None
        current_rows = tuple(
            await session.scalars(
                select(TeamRevisionMemberModel)
                .where(
                    TeamRevisionMemberModel.task_id == ids.task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                )
                .order_by(TeamRevisionMemberModel.preorder_index)
            )
        )
        unlisted = next(row for row in current_rows if row.member_id == first.unlisted_member_id)
        original = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        return _ReplayHistoryObservation(
            opening_outcome=opening.outcome,
            successor_dispatch_id=opening.dispatch_id,
            repeated_opening_outcome=repeated.outcome,
            current_member_ids=tuple(row.member_id for row in current_rows),
            unlisted_parent_member_id=unlisted.parent_member_id,
            unlisted_configuration_id=unlisted.member_configuration_id,
            unlisted_branch_basis_id=unlisted.member_branch_basis_id,
            transition_count=await _count(session, ReplanTransitionModel),
            team_revision_count=await _count(session, TeamRevisionModel),
            member_count=await _count(session, MemberModel),
            original_activity_revision=(
                original.node_activity_revision if original is not None else None
            ),
            first_successor_count=await _successor_count(
                session,
                ids.current_dispatch_id,
            ),
            second_successor_count=await _successor_count(
                session,
                first.successor_dispatch_id,
            ),
        )


async def _transition_for_source(
    session: Any,
    source_dispatch_id: str,
) -> ReplanTransitionModel:
    transition = await session.scalar(
        select(ReplanTransitionModel).where(
            ReplanTransitionModel.source_dispatch_id == source_dispatch_id
        )
    )
    assert transition is not None
    return cast(ReplanTransitionModel, transition)


async def _count(session: Any, model: type[object]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _successor_count(session: Any, predecessor_dispatch_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(DispatchTurnModel)
            .where(DispatchTurnModel.predecessor_dispatch_id == predecessor_dispatch_id)
        )
        or 0
    )


async def _continue_transition(
    session: Any,
    transition_id: str,
    dependencies: DispatchOpeningDependencies,
) -> OrdinaryOpeningResult:
    return await continue_committed_replan(
        cast(AsyncSession, session),
        transition_id=transition_id,
        dependencies=dependencies,
    )
