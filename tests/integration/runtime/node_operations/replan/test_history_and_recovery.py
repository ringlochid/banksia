from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import banksia.runtime.replan.continuation as replan_continuation
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    DispatchTurnModel,
    MemberConfigurationModel,
    MemberModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import (
    AddChildRequest,
    ReplanSuccess,
    UpdateChildRequest,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher, ReplanCommitted
from banksia.runtime.post_commit.dispatch_startup import read_replan_continuation_page
from banksia.runtime.replan.continuation import continue_committed_replan
from tests.helpers.executor_harness import (
    make_seed_child_terminal,
    seeded_executor,
    seeded_task_root,
)


async def test_recursive_replan_contract_rejects_ambiguity_and_preserves_removed_history(
    tmp_path: Path,
) -> None:
    omitted = UpdateChildRequest.model_validate(
        {"id": "child", "patch": {"instruction": "Keep the existing title."}}
    )
    cleared = UpdateChildRequest.model_validate({"id": "child", "patch": {"title": None}})
    assert "title" not in omitted.patch.model_fields_set
    assert "title" in cleared.patch.model_fields_set
    assert cleared.model_dump(mode="json", exclude_unset=True)["patch"] == {"title": None}

    invalid_requests = (
        (AddChildRequest, {"parent_id": "root", "child": {"title": "Reviewer"}}),
        (AddChildRequest, {"child": {"title": "Reviewer", "children": []}}),
        (
            UpdateChildRequest,
            {
                "id": "child",
                "patch": {
                    "children": [
                        {"id": "nested", "title": "First"},
                        {"id": "nested", "title": "Second"},
                    ]
                },
            },
        ),
        (
            AddChildRequest,
            {
                "child": {
                    "title": "Reviewer",
                    "children": [{"title": f"Leaf {index}"} for index in range(33)],
                }
            },
        ),
    )
    for model, payload in invalid_requests:
        with pytest.raises(ValidationError):
            model.model_validate(payload)

    dependencies = _opening_dependencies()
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
        nested_id = updated.created_ids[0]
        assert updated.updated_ids == ()

        async with session_factory() as session:
            update_transition = await _transition_for_source(
                session,
                ids.current_dispatch_id,
            )
            update_opening = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=update_transition.replan_transition_id,
                dependencies=dependencies,
            )
        assert update_opening.outcome == "opened"
        assert update_opening.dispatch_id is not None

        removed = ReplanSuccess.model_validate(
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=update_opening.dispatch_id,
                ),
                operation_name="remove_child",
                arguments={"id": ids.child_member_id},
            )
        )
        assert removed.removed_ids == (ids.child_member_id, nested_id)

        async with session_factory() as session:
            remove_transition = await _transition_for_source(
                session,
                update_opening.dispatch_id,
            )
            remove_opening = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=remove_transition.replan_transition_id,
                dependencies=dependencies,
            )
            task = await session.get(TaskModel, ids.task_id)
            child = await session.get(MemberModel, (ids.task_id, ids.child_member_id))
            nested = await session.get(MemberModel, (ids.task_id, nested_id))
            child_assignment = await session.get(
                AssignmentModel,
                ids.child_assignment_id,
            )
            historical_configurations = tuple(
                await session.scalars(
                    select(MemberConfigurationModel).where(
                        MemberConfigurationModel.task_id == ids.task_id,
                        MemberConfigurationModel.member_id.in_((ids.child_member_id, nested_id)),
                    )
                )
            )
            assert task is not None and task.current_team_revision_id is not None
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
            team_revision_count = await _count(session, TeamRevisionModel)
            transition_count = await _count(session, ReplanTransitionModel)

    assert remove_opening.outcome == "opened"
    assert child is not None and nested is not None
    assert child_assignment is not None
    assert child_assignment.terminal_outcome == "blocked"
    assert {row.member_id for row in historical_configurations} == {
        ids.child_member_id,
        nested_id,
    }
    assert current_member_ids == (ids.root_member_id,)
    assert team_revision_count == 3
    assert transition_count == 2


async def test_replan_replay_is_exact_and_nested_patch_preserves_unlisted_sibling(
    tmp_path: Path,
) -> None:
    dependencies = _opening_dependencies()
    async with seeded_executor(tmp_path, suffix="replan-exact-replay") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)

        first_scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
            provider_start_revision=0,
        )
        first_arguments = {
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
                scope=first_scope,
                operation_name="update_child",
                arguments=first_arguments,
            )
        )
        replayed_result = ReplanSuccess.model_validate(
            await executor.execute(
                scope=first_scope,
                operation_name="update_child",
                arguments=first_arguments,
            )
        )
        assert replayed_result == first_result
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=first_scope,
                operation_name="update_child",
                arguments={
                    "id": ids.child_member_id,
                    "patch": {"instruction": "This is not the committed request."},
                },
            )
        assert len(first_result.created_ids) == 2
        listed_id, unlisted_id = first_result.created_ids
        async with session_factory() as session:
            first_transition = await _transition_for_source(
                session,
                ids.current_dispatch_id,
            )
            first_opened = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=first_transition.replan_transition_id,
                dependencies=dependencies,
            )
            first_replay = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=first_transition.replan_transition_id,
                dependencies=dependencies,
            )
        assert first_opened.outcome == "opened"
        assert first_opened.dispatch_id is not None
        assert first_replay.outcome == "skipped"
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None and task.current_team_revision_id is not None
            first_unlisted = await session.scalar(
                select(TeamRevisionMemberModel).where(
                    TeamRevisionMemberModel.task_id == ids.task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    TeamRevisionMemberModel.member_id == unlisted_id,
                )
            )
        assert first_unlisted is not None

        second_result = ReplanSuccess.model_validate(
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=first_opened.dispatch_id,
                ),
                operation_name="update_child",
                arguments={
                    "id": ids.child_member_id,
                    "patch": {
                        "children": [
                            {
                                "id": listed_id,
                                "instruction": "Review the exact replay proof.",
                            }
                        ]
                    },
                },
            )
        )
        assert second_result.updated_ids == (listed_id,)
        assert second_result.created_ids == ()

        async with session_factory() as session:
            second_transition = await _transition_for_source(
                session,
                first_opened.dispatch_id,
            )
            second_opened = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=second_transition.replan_transition_id,
                dependencies=dependencies,
            )
            second_replay = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=second_transition.replan_transition_id,
                dependencies=dependencies,
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
            transition_count = await _count(session, ReplanTransitionModel)
            team_revision_count = await _count(session, TeamRevisionModel)
            member_count = await _count(session, MemberModel)
            original_source = await session.get(
                DispatchTurnModel,
                ids.current_dispatch_id,
            )
            first_successor_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(DispatchTurnModel)
                    .where(DispatchTurnModel.predecessor_dispatch_id == ids.current_dispatch_id)
                )
                or 0
            )
            second_successor_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(DispatchTurnModel)
                    .where(DispatchTurnModel.predecessor_dispatch_id == first_opened.dispatch_id)
                )
                or 0
            )

    assert second_opened.outcome == "opened"
    assert second_opened.dispatch_id is not None
    assert second_replay.outcome == "skipped"
    assert tuple(row.member_id for row in current_rows) == (
        ids.root_member_id,
        ids.child_member_id,
        listed_id,
        unlisted_id,
    )
    unlisted_row = next(row for row in current_rows if row.member_id == unlisted_id)
    assert unlisted_row.parent_member_id == ids.child_member_id
    assert unlisted_row.member_configuration_id == first_unlisted.member_configuration_id
    assert unlisted_row.member_branch_basis_id == first_unlisted.member_branch_basis_id
    assert transition_count == 2
    assert team_revision_count == 3
    assert member_count == 4
    assert original_source is not None and original_source.node_activity_revision == 1
    assert first_successor_count == 1
    assert second_successor_count == 1


async def test_manifest_repair_is_restart_discoverable_and_opens_one_exact_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    dependencies = _opening_dependencies()
    async with seeded_executor(
        tmp_path,
        suffix="replan-manifest-repair",
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _signals):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Recovery reviewer"}},
        )
        signal = publisher.signals[0]
        assert isinstance(signal, ReplanCommitted)

        async def fail_projection(*_args: object, **_kwargs: object) -> bool:
            raise OSError("manifest storage is temporarily unavailable")

        with monkeypatch.context() as scoped:
            scoped.setattr(
                replan_continuation,
                "project_workflow_manifest",
                fail_projection,
            )
            async with session_factory() as session:
                failed = await continue_committed_replan(
                    cast(AsyncSession, session),
                    transition_id=signal.transition_id,
                    dependencies=dependencies,
                )
                transition = await session.get(
                    ReplanTransitionModel,
                    signal.transition_id,
                )
            page = await read_replan_continuation_page(
                lambda: cast(
                    AbstractAsyncContextManager[AsyncSession],
                    session_factory(),
                ),
                cursor=None,
                page_size=10,
            )

        assert failed.outcome == "paused"
        assert transition is not None
        assert transition.manifest_state == "repair_required"
        assert transition.successor_state == "blocked"
        assert transition.successor_dispatch_id is None
        assert page.sources == (ReplanCommitted(signal.transition_id),)

        async with session_factory() as session:
            repaired = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=signal.transition_id,
                dependencies=dependencies,
            )
            duplicate = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=signal.transition_id,
                dependencies=dependencies,
            )
            transition = await session.get(
                ReplanTransitionModel,
                signal.transition_id,
            )
            successor_count = await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(
                    DispatchTurnModel.predecessor_dispatch_id == ids.current_dispatch_id,
                )
            )

    assert repaired.outcome == "opened"
    assert repaired.dispatch_id is not None
    assert duplicate.outcome == "skipped"
    assert transition is not None
    assert transition.manifest_state == "current"
    assert transition.successor_state == "opened"
    assert transition.successor_dispatch_id == repaired.dispatch_id
    assert successor_count == 1
    manifest = seeded_task_root(
        tmp_path,
        "replan-manifest-repair",
    ).joinpath("manifest.md")
    assert "Recovery reviewer" in manifest.read_text(encoding="utf-8")


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


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
