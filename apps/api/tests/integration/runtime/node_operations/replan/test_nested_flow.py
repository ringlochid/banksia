from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    FlowModel,
    FlowNodeModel,
    MemberConfigurationModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import ReplanSuccess
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher, ReplanCommitted
from banksia.runtime.replan.continuation import continue_committed_replan
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import SessionFactory, seeded_executor
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class NestedReplanState:
    branch_children: tuple[str, ...]
    reviewer_instruction: str | None
    verifier_configuration_id: str
    branch_basis_by_member_id: dict[str, str]
    revision_count: int
    transition_count: int


async def test_nested_replan_update_preserves_unlisted_children_and_appends_new_ones(
    tmp_path: Path,
) -> None:
    effects = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="nested-replan-flow",
        runtime_effect_publisher=effects,
    ) as (executor, session_factory, ids, _signals):
        added = await _add_review_branch(executor, ids)
        branch_id, reviewer_id, verifier_id = added.created_ids
        (
            opened_dispatch_id,
            before_basis_by_member_id,
            verifier_configuration_id,
        ) = await _open_review_branch(
            session_factory,
            effects,
            task_id=ids.task_id,
            branch_id=branch_id,
            reviewer_id=reviewer_id,
            verifier_id=verifier_id,
        )
        updated = await _update_review_branch(
            executor,
            ids,
            dispatch_id=opened_dispatch_id,
            branch_id=branch_id,
            reviewer_id=reviewer_id,
        )
        appended_id = updated.created_ids[0]
        state = await _read_nested_replan_state(
            session_factory,
            ids,
            branch_id=branch_id,
            reviewer_id=reviewer_id,
            verifier_id=verifier_id,
        )
        replayed_add = await _add_review_branch(executor, ids)

        assert replayed_add == added
        assert updated.updated_ids == (reviewer_id,)
        assert updated.created_ids == (appended_id,)
        assert state.branch_children == (reviewer_id, verifier_id, appended_id)
        assert state.verifier_configuration_id == verifier_configuration_id
        assert state.reviewer_instruction == "Review the primary change and its tests."
        assert state.branch_basis_by_member_id["root"] != before_basis_by_member_id["root"]
        assert state.branch_basis_by_member_id[branch_id] != before_basis_by_member_id[branch_id]
        assert (
            state.branch_basis_by_member_id[reviewer_id] != before_basis_by_member_id[reviewer_id]
        )
        assert (
            state.branch_basis_by_member_id[verifier_id] == before_basis_by_member_id[verifier_id]
        )
        assert state.branch_basis_by_member_id["child"] == before_basis_by_member_id["child"]
        assert state.revision_count == 3
        assert state.transition_count == 2


async def _add_review_branch(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
) -> ReplanSuccess:
    result = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
            provider_start_revision=0,
        ),
        operation_name="add_child",
        arguments={
            "child": {
                "title": "Review branch",
                "children": [
                    {
                        "title": "Primary reviewer",
                        "instruction": "Review the primary change.",
                    },
                    {
                        "title": "Independent verifier",
                        "instruction": "Verify the primary review.",
                    },
                ],
            }
        },
    )
    return ReplanSuccess.model_validate(result)


async def _open_review_branch(
    session_factory: SessionFactory,
    effects: CapturedRuntimeEffectPublisher,
    *,
    task_id: str,
    branch_id: str,
    reviewer_id: str,
    verifier_id: str,
) -> tuple[str, dict[str, str], str]:
    signal = effects.signals[0]
    assert isinstance(signal, ReplanCommitted)
    async with session_factory() as session:
        opened = await continue_committed_replan(
            cast(AsyncSession, session),
            transition_id=signal.transition_id,
            dependencies=_opening_dependencies(),
        )
        task = await session.get(TaskModel, task_id)
        assert task is not None
        selections = tuple(
            await session.scalars(
                select(TeamRevisionMemberModel).where(
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    TeamRevisionMemberModel.member_id.in_(
                        ("root", "child", branch_id, reviewer_id, verifier_id)
                    ),
                )
            )
        )
    assert opened.outcome == "opened"
    assert opened.dispatch_id is not None
    selections_by_member_id = {selection.member_id: selection for selection in selections}
    verifier = selections_by_member_id[verifier_id]
    assert verifier is not None
    return (
        opened.dispatch_id,
        {
            member_id: selection.member_branch_basis_id
            for member_id, selection in selections_by_member_id.items()
        },
        verifier.member_configuration_id,
    )


async def _update_review_branch(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
    *,
    dispatch_id: str,
    branch_id: str,
    reviewer_id: str,
) -> ReplanSuccess:
    result = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=dispatch_id,
        ),
        operation_name="update_child",
        arguments={
            "id": branch_id,
            "patch": {
                "children": [
                    {
                        "id": reviewer_id,
                        "instruction": "Review the primary change and its tests.",
                    },
                    {
                        "title": "Contrarian reviewer",
                        "instruction": "Look for consequential contrary evidence.",
                    },
                ]
            },
        },
    )
    return ReplanSuccess.model_validate(result)


async def _read_nested_replan_state(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    branch_id: str,
    reviewer_id: str,
    verifier_id: str,
) -> NestedReplanState:
    async with session_factory() as session:
        task = await session.get(TaskModel, ids.task_id)
        flow = await session.get(FlowModel, ids.flow_id)
        assert task is not None and flow is not None
        branch = await session.scalar(
            select(FlowNodeModel).where(
                FlowNodeModel.flow_revision_id == flow.active_flow_revision_id,
                FlowNodeModel.member_id == branch_id,
            )
        )
        selections = {
            member_id: await session.scalar(
                select(TeamRevisionMemberModel).where(
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    TeamRevisionMemberModel.member_id == member_id,
                )
            )
            for member_id in ("root", "child", branch_id, reviewer_id, verifier_id)
        }
        reviewer = selections[reviewer_id]
        verifier = selections[verifier_id]
        assert branch is not None and reviewer is not None and verifier is not None
        reviewer_configuration = await session.get(
            MemberConfigurationModel,
            reviewer.member_configuration_id,
        )
        revision_count = await session.scalar(select(func.count()).select_from(TeamRevisionModel))
        transition_count = await session.scalar(
            select(func.count()).select_from(ReplanTransitionModel)
        )
    assert reviewer_configuration is not None
    assert revision_count is not None and transition_count is not None
    return NestedReplanState(
        branch_children=tuple(branch.child_node_keys_json),
        reviewer_instruction=reviewer_configuration.instruction,
        verifier_configuration_id=verifier.member_configuration_id,
        branch_basis_by_member_id={
            member_id: selection.member_branch_basis_id
            for member_id, selection in selections.items()
            if selection is not None
        },
        revision_count=revision_count,
        transition_count=transition_count,
    )


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
