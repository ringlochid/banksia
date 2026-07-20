from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from autoclaw.persistence import RuntimeBase
from autoclaw.persistence.models import (
    AssignmentDecisionModel,
    AssignmentModel,
    FlowEdgeModel,
    FlowNodeModel,
    FlowRevisionModel,
    NodePlanRevisionModel,
)
from autoclaw.runtime.dispatch.authority import read_node_operation_authority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import NodeOperationScope
from autoclaw.runtime.node_operations.release.evidence import (
    _current_assignments_by_node,
)
from sqlalchemy import Connection, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.runtime.node_operations.structural_revision_fixture import (
    StructuralRevisionContext,
    seeded_structural_revision_context,
)


async def test_add_update_remove_rebuilds_relational_tree_and_exact_edges(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(tmp_path, suffix="happy") as context:
        with context.engine.begin() as connection:
            flow_nodes = RuntimeBase.metadata.tables["flow_nodes"]
            connection.execute(
                flow_nodes.update()
                .where(flow_nodes.c.flow_node_id == context.ids.root_node_id)
                .values(child_node_keys_json=["ghost-from-corrupt-json"])
            )

        added = await context.executor.execute(
            scope=context.scope,
            operation_name="add_child",
            arguments={
                "expected_structural_revision_id": context.ids.flow_revision_id,
                "payload": {
                    "target_parent_node_key": "branch",
                    "child": {
                        "node_key": "qa",
                        "role": "role.target",
                        "policy": "policy.target",
                        "description": "QA worker.",
                        "consumes": {"artifacts": [{"slot": "source", "required": True}]},
                    },
                },
            },
        )
        added_revision = added.model_dump()["flow"]["active_flow_revision_id"]
        assert await _child_keys(context, added_revision, "root") == (
            "child",
            "branch",
            "outside_parent",
        )
        assert await _child_keys(context, added_revision, "branch") == (
            "producer",
            "alternate",
            "reviewer",
            "qa",
        )
        assert await _edges(context, added_revision) == (
            ("producer", "reviewer", "artifact", "source"),
            ("producer", "qa", "artifact", "source"),
        )

        updated = await context.executor.execute(
            scope=context.scope,
            operation_name="update_child",
            arguments={
                "expected_structural_revision_id": added_revision,
                "payload": {
                    "child_node_key": "qa",
                    "patch": {"consumes": {"artifacts": [{"slot": "alternate", "required": True}]}},
                },
            },
        )
        updated_revision = updated.model_dump()["flow"]["active_flow_revision_id"]
        assert await _edges(context, updated_revision) == (
            ("producer", "reviewer", "artifact", "source"),
            ("alternate", "qa", "artifact", "alternate"),
        )

        removed = await context.executor.execute(
            scope=context.scope,
            operation_name="remove_child",
            arguments={
                "expected_structural_revision_id": updated_revision,
                "payload": {"child_node_key": "qa"},
            },
        )
        removed_revision = removed.model_dump()["flow"]["active_flow_revision_id"]
        assert await _edges(context, removed_revision) == (
            ("producer", "reviewer", "artifact", "source"),
        )
        assert await _node(context, removed_revision, "qa") is None


async def test_structural_revisions_preserve_replace_and_clear_authored_provider(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(tmp_path, suffix="provider") as context:
        added = await context.executor.execute(
            scope=context.scope,
            operation_name="add_child",
            arguments={
                "expected_structural_revision_id": context.ids.flow_revision_id,
                "payload": {
                    "target_parent_node_key": "branch",
                    "child": {
                        "node_key": "provider_worker",
                        "role": "role.target",
                        "policy": "policy.target",
                        "provider": {"kind": "codex"},
                        "description": "Worker with an explicit provider.",
                    },
                },
            },
        )
        added_revision = added.model_dump()["flow"]["active_flow_revision_id"]
        await _assert_provider(context, added_revision, "provider_worker", "codex")

        preserved = await context.executor.execute(
            scope=context.scope,
            operation_name="update_child",
            arguments={
                "expected_structural_revision_id": added_revision,
                "payload": {
                    "child_node_key": "provider_worker",
                    "patch": {"description": "Provider remains explicit."},
                },
            },
        )
        preserved_revision = preserved.model_dump()["flow"]["active_flow_revision_id"]
        await _assert_provider(context, preserved_revision, "provider_worker", "codex")

        replaced = await context.executor.execute(
            scope=context.scope,
            operation_name="update_child",
            arguments={
                "expected_structural_revision_id": preserved_revision,
                "payload": {
                    "child_node_key": "provider_worker",
                    "patch": {"provider": {"kind": "claude"}},
                },
            },
        )
        replaced_revision = replaced.model_dump()["flow"]["active_flow_revision_id"]
        await _assert_provider(context, replaced_revision, "provider_worker", "claude")

        cleared = await context.executor.execute(
            scope=context.scope,
            operation_name="update_child",
            arguments={
                "expected_structural_revision_id": replaced_revision,
                "payload": {
                    "child_node_key": "provider_worker",
                    "patch": {"provider": None},
                },
            },
        )
        cleared_revision = cleared.model_dump()["flow"]["active_flow_revision_id"]
        await _assert_provider(context, cleared_revision, "provider_worker", None)


async def test_structural_revision_preserves_historical_decision_revision(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(
        tmp_path,
        suffix="historical-decision",
    ) as context:
        async with context.session_factory() as session:
            child_assignment = await session.get(
                AssignmentModel,
                context.ids.child_assignment_id,
            )
            assert child_assignment is not None
            child_assignment.created_by_dispatch_id = context.ids.root_dispatch_id
            session.add(
                AssignmentDecisionModel(
                    assignment_decision_id=(f"assignment-decision.{context.ids.root_dispatch_id}"),
                    source_dispatch_id=context.ids.root_dispatch_id,
                    task_id=context.ids.task_id,
                    flow_id=context.ids.flow_id,
                    assignment_id=context.ids.root_assignment_id,
                    attempt_id=context.ids.root_attempt_id,
                    source_flow_revision_id=context.ids.flow_revision_id,
                    decision_kind="staged_child",
                    staged_child_assignment_id=context.ids.child_assignment_id,
                    staged_child_attempt_id=context.ids.child_attempt_id,
                )
            )
            await session.commit()

        result = await context.executor.execute(
            scope=context.scope,
            operation_name="add_child",
            arguments={
                "expected_structural_revision_id": context.ids.flow_revision_id,
                "payload": {
                    "target_parent_node_key": "branch",
                    "child": {
                        "node_key": "post_decision_worker",
                        "role": "role.target",
                        "policy": "policy.target",
                        "description": "Worker added after an earlier child decision.",
                    },
                },
            },
        )
        adopted_revision = result.model_dump()["flow"]["active_flow_revision_id"]

        async with context.session_factory() as session:
            decision = await session.get(
                AssignmentDecisionModel,
                f"assignment-decision.{context.ids.root_dispatch_id}",
            )
            root_assignment = await session.get(
                AssignmentModel,
                context.ids.root_assignment_id,
            )
        with context.engine.connect() as connection:
            foreign_key_violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()

        assert decision is not None
        assert decision.source_flow_revision_id == context.ids.flow_revision_id
        assert root_assignment is not None
        assert root_assignment.flow_revision_id == adopted_revision
        assert foreign_key_violations == []


async def test_release_rejects_descendant_owned_by_superseded_parent(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(
        tmp_path,
        suffix="stale-parent-lineage",
    ) as context:
        old_parent_id = f"assignment.{context.ids.suffix}.branch.old"
        current_parent_id = f"assignment.{context.ids.suffix}.branch.current"
        child_assignment_id = f"assignment.{context.ids.suffix}.producer.current"
        async with context.session_factory() as session:
            branch = await session.scalar(
                select(FlowNodeModel).where(FlowNodeModel.node_key == "branch")
            )
            producer = await session.scalar(
                select(FlowNodeModel).where(FlowNodeModel.node_key == "producer")
            )
            assert branch is not None and producer is not None
            old_parent = AssignmentModel(
                assignment_id=old_parent_id,
                task_id=context.ids.task_id,
                flow_id=context.ids.flow_id,
                flow_revision_id=context.ids.flow_revision_id,
                flow_node_id=branch.flow_node_id,
                assignment_key=f"assignment-key.{context.ids.suffix}.branch.old",
                node_key="branch",
                parent_assignment_id=context.ids.root_assignment_id,
                summary="Superseded branch assignment.",
                instruction=None,
                criteria_json=[],
                consumes_json=[],
                produces_json=[],
                current_attempt_id=None,
                work_plan_revision=0,
                superseded_at=datetime.now(UTC),
            )
            current_parent = AssignmentModel(
                assignment_id=current_parent_id,
                task_id=context.ids.task_id,
                flow_id=context.ids.flow_id,
                flow_revision_id=context.ids.flow_revision_id,
                flow_node_id=branch.flow_node_id,
                assignment_key=f"assignment-key.{context.ids.suffix}.branch.current",
                node_key="branch",
                parent_assignment_id=context.ids.root_assignment_id,
                summary="Current branch assignment.",
                instruction=None,
                criteria_json=[],
                consumes_json=[],
                produces_json=[],
                current_attempt_id=None,
                work_plan_revision=0,
                superseded_at=None,
            )
            child_assignment = AssignmentModel(
                assignment_id=child_assignment_id,
                task_id=context.ids.task_id,
                flow_id=context.ids.flow_id,
                flow_revision_id=context.ids.flow_revision_id,
                flow_node_id=producer.flow_node_id,
                assignment_key=f"assignment-key.{context.ids.suffix}.producer.current",
                node_key="producer",
                parent_assignment_id=old_parent_id,
                summary="Producer work owned by the superseded branch assignment.",
                instruction=None,
                criteria_json=[],
                consumes_json=[],
                produces_json=[],
                current_attempt_id=None,
                work_plan_revision=0,
                superseded_at=None,
            )
            branch.current_assignment_id = current_parent_id
            producer.current_assignment_id = child_assignment_id
            session.add_all((old_parent, current_parent, child_assignment))
            await session.commit()

        async with context.session_factory() as session:
            typed_session = cast(AsyncSession, session)
            authority = await read_node_operation_authority(typed_session, context.scope)
            branch = await session.scalar(
                select(FlowNodeModel).where(FlowNodeModel.node_key == "branch")
            )
            producer = await session.scalar(
                select(FlowNodeModel).where(FlowNodeModel.node_key == "producer")
            )
            assert branch is not None and producer is not None
            with pytest.raises(RuntimeOperationError, match="current parent assignment"):
                await _current_assignments_by_node(
                    typed_session,
                    authority,
                    (branch, producer),
                )


@pytest.mark.parametrize(
    ("suffix", "child", "message"),
    (
        (
            "missing-provider",
            {
                "node_key": "missing_consumer",
                "role": "role.target",
                "policy": "policy.target",
                "description": "Missing consumer.",
                "consumes": {"artifacts": [{"slot": "absent"}]},
            },
            "missing artifact consume selector target 'absent'",
        ),
        (
            "duplicate-slot",
            {
                "node_key": "duplicate_producer",
                "role": "role.target",
                "policy": "policy.target",
                "description": "Duplicate producer.",
                "produces": {
                    "artifacts": [{"slot": "source", "description": "Conflicting source."}]
                },
            },
            "duplicate artifact slot 'source'",
        ),
        (
            "cycle",
            {
                "node_key": "cycle_parent",
                "role": "role.target",
                "policy": "policy.target",
                "description": "Cyclic parent.",
                "children": [
                    {
                        "node_key": "cycle_a",
                        "role": "role.target",
                        "policy": "policy.target",
                        "description": "Cycle A.",
                        "consumes": {"artifacts": [{"slot": "cycle_b"}]},
                        "produces": {"artifacts": [{"slot": "cycle_a", "description": "Cycle A."}]},
                    },
                    {
                        "node_key": "cycle_b",
                        "role": "role.target",
                        "policy": "policy.target",
                        "description": "Cycle B.",
                        "consumes": {"artifacts": [{"slot": "cycle_a"}]},
                        "produces": {"artifacts": [{"slot": "cycle_b", "description": "Cycle B."}]},
                    },
                ],
            },
            "cyclic dependency graph",
        ),
    ),
)
async def test_invalid_candidate_rejects_before_revision_persistence(
    tmp_path: Path,
    suffix: str,
    child: dict[str, object],
    message: str,
) -> None:
    async with seeded_structural_revision_context(tmp_path, suffix=suffix) as context:
        with pytest.raises(RuntimeOperationError, match=message):
            await context.executor.execute(
                scope=context.scope,
                operation_name="add_child",
                arguments={
                    "expected_structural_revision_id": context.ids.flow_revision_id,
                    "payload": {
                        "target_parent_node_key": "branch",
                        "child": child,
                    },
                },
            )
        assert await _revision_count(context) == 1


async def test_open_work_and_stale_expected_revision_reject_without_orphans(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(tmp_path, suffix="guards") as context:
        with pytest.raises(RuntimeOperationError, match="current open work"):
            await context.executor.execute(
                scope=context.scope,
                operation_name="update_child",
                arguments={
                    "expected_structural_revision_id": context.ids.flow_revision_id,
                    "payload": {
                        "child_node_key": "child",
                        "patch": {"description": "Illegal live rewrite."},
                    },
                },
            )
        with pytest.raises(RuntimeOperationError) as stale:
            await context.executor.execute(
                scope=context.scope,
                operation_name="remove_child",
                arguments={
                    "expected_structural_revision_id": "flow-revision.stale",
                    "payload": {"child_node_key": "outside_leaf"},
                },
            )
        assert stale.value.code.value == "stale_flow_revision"
        assert await _revision_count(context) == 1
        assert await _nodes_outside_source(context) == 0


async def test_non_root_owner_cannot_cross_relational_subtree(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(tmp_path, suffix="subtree") as context:
        branch_scope = _make_branch_current(context)
        with pytest.raises(RuntimeOperationError) as rejected:
            await context.executor.execute(
                scope=branch_scope,
                operation_name="update_child",
                arguments={
                    "expected_structural_revision_id": context.ids.flow_revision_id,
                    "payload": {
                        "child_node_key": "outside_leaf",
                        "patch": {"description": "Cross-subtree rewrite."},
                    },
                },
            )
        assert rejected.value.code.value == "illegal_target_relation"
        assert await _revision_count(context) == 1


def _make_branch_current(context: StructuralRevisionContext) -> NodeOperationScope:
    dispatch_id = f"dispatch.{context.ids.suffix}.branch.1"
    assignment_id = f"assignment.{context.ids.suffix}.branch"
    attempt_id = f"attempt.{context.ids.suffix}.branch.1"
    now = datetime.now(tz=UTC)
    branch_node_id = f"flow-node.{context.ids.flow_revision_id}.branch"
    with context.engine.begin() as connection:
        _close_root_dispatch(connection, context, closed_at=now)
        _stage_branch_assignment(
            connection,
            context,
            assignment_id=assignment_id,
            attempt_id=attempt_id,
            branch_node_id=branch_node_id,
            opened_at=now,
        )
        _stage_branch_dispatch(
            connection,
            context,
            dispatch_id=dispatch_id,
            assignment_id=assignment_id,
            attempt_id=attempt_id,
            opened_at=now,
        )
        _stage_dispatch_support(connection, dispatch_id=dispatch_id, created_at=now)
        flows = RuntimeBase.metadata.tables["flows"]
        connection.execute(
            flows.update()
            .where(flows.c.flow_id == context.ids.flow_id)
            .values(current_dispatch_id=dispatch_id)
        )
    return NodeOperationScope(task_id=context.ids.task_id, dispatch_id=dispatch_id)


def _close_root_dispatch(
    connection: Connection,
    context: StructuralRevisionContext,
    *,
    closed_at: datetime,
) -> None:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    connection.execute(
        dispatches.update()
        .where(dispatches.c.dispatch_id == context.ids.current_dispatch_id)
        .values(status="closed", closed_at=closed_at, closed_reason="boundary")
    )


def _stage_branch_assignment(
    connection: Connection,
    context: StructuralRevisionContext,
    *,
    assignment_id: str,
    attempt_id: str,
    branch_node_id: str,
    opened_at: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["assignments"].insert(),
        {
            "assignment_id": assignment_id,
            "task_id": context.ids.task_id,
            "flow_id": context.ids.flow_id,
            "flow_revision_id": context.ids.flow_revision_id,
            "flow_node_id": branch_node_id,
            "assignment_key": f"assignment-key.{context.ids.suffix}.branch",
            "node_key": "branch",
            "parent_assignment_id": context.ids.root_assignment_id,
            "summary": "Branch assignment.",
            "instruction": None,
            "criteria_json": [],
            "consumes_json": [],
            "produces_json": [],
            "current_attempt_id": None,
            "work_plan_revision": 0,
            "created_by_dispatch_id": context.ids.current_dispatch_id,
            "created_at": opened_at,
            "superseded_at": None,
        },
    )
    connection.execute(
        tables["attempts"].insert(),
        {
            "attempt_id": attempt_id,
            "assignment_id": assignment_id,
            "task_id": context.ids.task_id,
            "flow_id": context.ids.flow_id,
            "node_key": "branch",
            "retry_of_attempt_id": None,
            "status": "running",
            "terminal_outcome": None,
            "opened_at": opened_at,
            "closed_at": None,
        },
    )
    connection.execute(
        tables["assignments"]
        .update()
        .where(tables["assignments"].c.assignment_id == assignment_id)
        .values(current_attempt_id=attempt_id)
    )
    connection.execute(
        tables["flow_nodes"]
        .update()
        .where(tables["flow_nodes"].c.flow_node_id == branch_node_id)
        .values(current_assignment_id=assignment_id, state="running")
    )


def _stage_branch_dispatch(
    connection: Connection,
    context: StructuralRevisionContext,
    *,
    dispatch_id: str,
    assignment_id: str,
    attempt_id: str,
    opened_at: datetime,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["dispatch_turns"].insert(),
        {
            "dispatch_id": dispatch_id,
            "task_id": context.ids.task_id,
            "flow_id": context.ids.flow_id,
            "assignment_id": assignment_id,
            "attempt_id": attempt_id,
            "node_key": "branch",
            "flow_start_source_flow_id": None,
            "predecessor_dispatch_id": context.ids.current_dispatch_id,
            "status": "open",
            "opened_reason": "boundary",
            "requested_provider": "codex",
            "resolved_provider": "codex",
            "provider_selection_basis": "default",
            "provider_route_kind": "codex",
            "model_override": None,
            "effort_override": None,
            "gateway_profile": None,
            "provider_start_revision": 0,
            "provider_start_attempt_count": 0,
            "next_provider_start_at": None,
            "provider_start_retry_kind": None,
            "provider_start_last_error_code": None,
            "created_at": opened_at,
            "adapter_started_at": opened_at,
            "last_node_activity_at": opened_at,
            "node_activity_revision": 0,
            "closed_at": None,
            "closed_reason": None,
        },
    )


def _stage_dispatch_support(
    connection: Connection,
    *,
    dispatch_id: str,
    created_at: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["dispatch_prompt_refs"].insert(),
        {
            "dispatch_id": dispatch_id,
            "instructions_logical_path": f"_runtime/dispatch/{dispatch_id}/instructions.md",
            "input_logical_path": f"_runtime/dispatch/{dispatch_id}/input.md",
            "dynamic_input_version": 1,
            "created_at": created_at,
        },
    )
    connection.execute(
        tables["dispatch_capability_sets"].insert(),
        {
            "dispatch_id": dispatch_id,
            "provider_native_access": "full",
            "provider_native_access_source": "default",
            "network_access": "allow",
            "network_access_source": "default",
            "human_direction": "allow",
            "human_approval": "allow",
            "human_input": "allow",
            "human_review": "allow",
            "command_run": "allow",
            "created_at": created_at,
        },
    )


async def _revision_count(context: StructuralRevisionContext) -> int:
    async with context.session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(FlowRevisionModel))
    return int(value or 0)


async def _nodes_outside_source(context: StructuralRevisionContext) -> int:
    async with context.session_factory() as session:
        value = await session.scalar(
            select(func.count())
            .select_from(FlowNodeModel)
            .where(FlowNodeModel.flow_revision_id != context.ids.flow_revision_id)
        )
    return int(value or 0)


async def _node(
    context: StructuralRevisionContext,
    revision_id: str,
    node_key: str,
) -> FlowNodeModel | None:
    async with context.session_factory() as session:
        return cast(
            FlowNodeModel | None,
            await session.scalar(
                select(FlowNodeModel).where(
                    FlowNodeModel.flow_revision_id == revision_id,
                    FlowNodeModel.node_key == node_key,
                )
            ),
        )


async def _assert_provider(
    context: StructuralRevisionContext,
    revision_id: str,
    node_key: str,
    expected: str | None,
) -> None:
    async with context.session_factory() as session:
        flow_node = await session.scalar(
            select(FlowNodeModel).where(
                FlowNodeModel.flow_revision_id == revision_id,
                FlowNodeModel.node_key == node_key,
            )
        )
        node_plan = (
            await session.scalar(
                select(NodePlanRevisionModel).where(
                    NodePlanRevisionModel.flow_revision_id == revision_id,
                    NodePlanRevisionModel.flow_node_id == flow_node.flow_node_id,
                )
            )
            if flow_node is not None
            else None
        )
        revision = await session.get(FlowRevisionModel, revision_id)

    assert flow_node is not None
    assert flow_node.provider_kind == expected
    assert node_plan is not None and node_plan.provider_kind == expected
    assert revision is not None
    snapshot_nodes = cast(list[dict[str, object]], revision.snapshot_json["nodes"])
    snapshot = next(node for node in snapshot_nodes if node["node_key"] == node_key)
    expected_provider = None if expected is None else {"kind": expected}
    assert snapshot["provider"] == expected_provider


async def _child_keys(
    context: StructuralRevisionContext,
    revision_id: str,
    node_key: str,
) -> tuple[str, ...]:
    node = await _node(context, revision_id, node_key)
    assert node is not None
    return tuple(node.child_node_keys_json)


async def _edges(
    context: StructuralRevisionContext,
    revision_id: str,
) -> tuple[tuple[str, str, str, str], ...]:
    async with context.session_factory() as session:
        edges = list(
            await session.scalars(
                select(FlowEdgeModel)
                .where(FlowEdgeModel.flow_revision_id == revision_id)
                .order_by(FlowEdgeModel.order_index)
            )
        )
    return tuple(
        (
            edge.provider_node_key,
            edge.consumer_node_key,
            edge.kind,
            edge.slot,
        )
        for edge in edges
    )
