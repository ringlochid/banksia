from __future__ import annotations

from pathlib import Path

import pytest
from banksia.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    FlowRevisionModel,
    MemberConfigurationModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import AddChildRequest, ReplanSuccess, UpdateChildRequest
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchCleanupRequested,
    ReplanCommitted,
)
from pydantic import ValidationError
from sqlalchemy import func, select, update
from tests.helpers.executor_harness import SessionFactory, seeded_executor
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.team_persistence_seed import member_branch_basis_id


def test_replan_contracts_are_closed_and_distinguish_omit_from_null() -> None:
    request = UpdateChildRequest.model_validate({"id": "child", "patch": {"description": None}})
    assert request.patch.model_fields_set == {"description"}
    assert request.patch.description is None

    with pytest.raises(ValidationError):
        AddChildRequest.model_validate({"parent_id": "root", "child": {"description": "new"}})
    with pytest.raises(ValidationError, match="children"):
        UpdateChildRequest.model_validate({"id": "child", "patch": {"children": []}})
    with pytest.raises(ValidationError, match="children"):
        AddChildRequest.model_validate({"child": {"children": []}})
    with pytest.raises(ValidationError, match="children"):
        AddChildRequest.model_validate(
            {"child": {"children": [{"title": "Nested", "children": []}]}}
        )
    with pytest.raises(ValidationError):
        AddChildRequest.model_validate({"child": {"id": "caller-selected", "description": "new"}})
    with pytest.raises(ValidationError, match="illegal text character"):
        AddChildRequest.model_validate({"child": {"instruction": "unsafe\u0000text"}})
    with pytest.raises(ValidationError, match="same existing Member"):
        UpdateChildRequest.model_validate(
            {
                "id": "child",
                "patch": {
                    "children": [
                        {"id": "nested", "instruction": "First change."},
                        {"id": "nested", "instruction": "Second change."},
                    ]
                },
            }
        )

    normalized = AddChildRequest.model_validate(
        {"child": {"title": "  ", "instruction": "line one\r\nline two"}}
    )
    assert normalized.child.title is None
    assert normalized.child.instruction == "line one\nline two"


def test_replan_contracts_enforce_recursive_width_as_hidden_controller_validation() -> None:
    too_many_children = [{"title": f"Child {index}"} for index in range(33)]

    with pytest.raises(ValidationError, match="controller direct-child limit"):
        AddChildRequest.model_validate(
            {
                "child": {
                    "title": "Branch",
                    "children": too_many_children,
                }
            }
        )
    with pytest.raises(ValidationError, match="controller direct-child limit"):
        UpdateChildRequest.model_validate(
            {
                "id": "child",
                "patch": {
                    "children": too_many_children,
                },
            }
        )


async def test_recursive_add_commits_complete_successors_and_closes_source(
    tmp_path: Path,
) -> None:
    effects = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="recursive-add",
        runtime_effect_publisher=effects,
    ) as (executor, session_factory, ids, _signals):
        response = ReplanSuccess.model_validate(
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="add_child",
                arguments={
                    "child": {
                        "title": "Reviewer",
                        "description": "Review the work.",
                        "instruction": "Return actionable findings.",
                        "provider": {"kind": "codex"},
                        "children": [
                            {
                                "title": "Verifier",
                                "description": "Verify the highest-risk findings.",
                            }
                        ],
                    }
                },
            )
        )

        assert response.operation == "add_child"
        assert len(response.created_ids) == 2
        assert response.must_stop is True
        reviewer = next(
            member for member in response.direct_team if member.id == response.created_ids[0]
        )
        assert reviewer.provider.kind == "codex"
        assert reviewer.participation == "required"
        assert reviewer.availability == "available"
        assert response.behavior == "manager"
        assert response.effective_capabilities.command_run == "allow"
        assert "assign_child" in response.available_actions
        assert "start_command_run" in response.available_actions
        assert tuple(type(signal) for signal in effects.signals) == (
            ReplanCommitted,
            DispatchCleanupRequested,
        )
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            flow = await session.get(FlowModel, ids.flow_id)
            source = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            transition = await session.scalar(select(ReplanTransitionModel))
            selected_count = await session.scalar(
                select(func.count())
                .select_from(TeamRevisionMemberModel)
                .where(TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id)
            )
            flow_nodes = tuple(
                await session.scalars(
                    select(FlowNodeModel)
                    .where(FlowNodeModel.flow_revision_id == flow.active_flow_revision_id)
                    .order_by(FlowNodeModel.order_index)
                )
            )
            successor_selections = {
                selection.member_id: selection
                for selection in await session.scalars(
                    select(TeamRevisionMemberModel).where(
                        TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id
                    )
                )
            }

        assert task is not None and task.current_team_revision_id is not None
        assert flow is not None and flow.active_flow_revision_id is not None
        assert source is not None and source.closed_reason == "structural_replan"
        assert transition is not None
        assert transition.manifest_state == "pending"
        assert transition.successor_state == "blocked"
        assert selected_count == 4
        assert len(flow_nodes) == 4
        assert flow_nodes[0].child_node_keys_json[-1] == response.created_ids[0]
        assert flow_nodes[2].child_node_keys_json == [response.created_ids[1]]
        root_basis = successor_selections["root"].member_branch_basis_id
        child_basis = successor_selections["child"].member_branch_basis_id
        assert root_basis != member_branch_basis_id(ids, "root")
        assert child_basis == member_branch_basis_id(ids, "child")


async def test_update_rejects_descendant_with_active_work(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-busy") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        with pytest.raises(RuntimeOperationError, match="active assigned work"):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="update_child",
                arguments={
                    "id": "child",
                    "patch": {"instruction": "Use the new instruction."},
                },
            )
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            source = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            transition_count = await session.scalar(
                select(func.count()).select_from(ReplanTransitionModel)
            )
        assert flow is not None and flow.active_flow_revision_id == ids.flow_revision_id
        assert source is not None and source.status == "open"
    assert transition_count == 0


async def test_update_rejects_no_effect_without_committing_revisions(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-no-effect") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await _finish_child_work(session_factory, ids)
        with pytest.raises(RuntimeOperationError) as rejected:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="update_child",
                arguments={
                    "id": "child",
                    "patch": {"description": "child member fixture"},
                },
            )
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            source = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            transition_count = await session.scalar(
                select(func.count()).select_from(ReplanTransitionModel)
            )
            team_revision_count = await session.scalar(
                select(func.count()).select_from(TeamRevisionModel)
            )
            flow_revision_count = await session.scalar(
                select(func.count()).select_from(FlowRevisionModel)
            )

    assert rejected.value.code == OperationFailureCode.ILLEGAL_STATE
    assert flow is not None and flow.active_flow_revision_id == ids.flow_revision_id
    assert source is not None and source.status == "open"
    assert transition_count == 0
    assert team_revision_count == 1
    assert flow_revision_count == 1


async def test_update_recursively_upserts_without_rebinding_history(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-update") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await _finish_child_work(session_factory, ids)
        response = ReplanSuccess.model_validate(
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="update_child",
                arguments={
                    "id": "child",
                    "patch": {
                        "description": None,
                        "instruction": "Review the exact changed surface.",
                        "children": [
                            {
                                "title": "Verifier",
                                "description": "Verify the review findings.",
                            }
                        ],
                    },
                },
            )
        )
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            current_child = await session.scalar(
                select(TeamRevisionMemberModel).where(
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    TeamRevisionMemberModel.member_id == "child",
                )
            )
            configuration = await session.get(
                MemberConfigurationModel,
                current_child.member_configuration_id,
            )
            current_nodes = tuple(
                await session.scalars(
                    select(FlowNodeModel)
                    .join(
                        FlowModel,
                        FlowModel.active_flow_revision_id == FlowNodeModel.flow_revision_id,
                    )
                    .where(FlowModel.flow_id == ids.flow_id)
                    .order_by(FlowNodeModel.order_index)
                )
            )
            current_root = await session.scalar(
                select(TeamRevisionMemberModel).where(
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    TeamRevisionMemberModel.member_id == "root",
                )
            )

        assert response.updated_ids == ("child",)
        assert len(response.created_ids) == 1
        assert current_child is not None
        assert current_root is not None
        assert configuration is not None
        assert configuration.description is None
        assert configuration.instruction == "Review the exact changed surface."
        assert configuration.predecessor_member_configuration_id.endswith(".child.1")
        assert tuple(node.member_id for node in current_nodes) == (
            "root",
            "child",
            response.created_ids[0],
        )
        assert current_nodes[2].parent_node_key == "child"
        assert current_child.member_branch_basis_id != member_branch_basis_id(ids, "child")
        assert current_root.member_branch_basis_id != member_branch_basis_id(ids, "root")


async def test_remove_commits_successor_without_erasing_historical_rows(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-remove") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await _finish_child_work(session_factory, ids)
        response = ReplanSuccess.model_validate(
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="remove_child",
                arguments={"id": "child"},
            )
        )
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            flow = await session.get(FlowModel, ids.flow_id)
            successor_members = await session.scalar(
                select(func.count())
                .select_from(TeamRevisionMemberModel)
                .where(TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id)
            )
            successor_nodes = await session.scalar(
                select(func.count())
                .select_from(FlowNodeModel)
                .where(FlowNodeModel.flow_revision_id == flow.active_flow_revision_id)
            )
            historical_child = await session.get(FlowNodeModel, ids.child_node_id)
            current_root = await session.scalar(
                select(TeamRevisionMemberModel).where(
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    TeamRevisionMemberModel.member_id == "root",
                )
            )

        assert response.removed_ids == ("child",)
        assert response.direct_team == ()
        assert response.behavior == "contributor"
        assert "assign_child" not in response.available_actions
        assert successor_members == 1
        assert successor_nodes == 1
        assert historical_child is not None
        assert current_root is not None
        assert current_root.member_branch_basis_id != member_branch_basis_id(ids, "root")


async def _finish_child_work(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> None:
    async with session_factory() as session:
        now = utc_now()
        await session.execute(
            update(AttemptModel)
            .where(AttemptModel.attempt_id == ids.child_attempt_id)
            .values(status="cancelled", terminal_outcome=None, closed_at=now)
        )
        await session.execute(
            update(FlowNodeModel)
            .where(FlowNodeModel.flow_node_id == ids.child_node_id)
            .values(state="done")
        )
        await session.commit()
