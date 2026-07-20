from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from autoclaw.persistence import RuntimeBase
from sqlalchemy import Connection

FIXTURE_TIMESTAMP = datetime(2026, 7, 18, tzinfo=UTC)


@dataclass(frozen=True)
class RuntimeIds:
    suffix: str
    task_id: str
    compiled_plan_id: str
    flow_id: str
    flow_revision_id: str
    root_node_id: str
    child_node_id: str
    root_assignment_id: str
    child_assignment_id: str
    root_attempt_id: str
    child_attempt_id: str
    root_dispatch_id: str
    child_dispatch_id: str
    current_dispatch_id: str
    root_checkpoint_id: str
    child_checkpoint_id: str


@dataclass(frozen=True)
class DispatchFixtureRow:
    dispatch_id: str
    assignment_id: str
    attempt_id: str
    node_key: str
    flow_start_source_flow_id: str | None
    predecessor_dispatch_id: str | None
    status: str
    opened_reason: str
    adapter_started_at: datetime | None
    closed_at: datetime | None
    closed_reason: str | None


def runtime_ids(suffix: str = "a") -> RuntimeIds:
    return RuntimeIds(
        suffix=suffix,
        task_id=f"task.{suffix}",
        compiled_plan_id=f"compiled-plan.{suffix}",
        flow_id=f"flow.{suffix}",
        flow_revision_id=f"flow-revision.{suffix}.1",
        root_node_id=f"flow-node.{suffix}.root",
        child_node_id=f"flow-node.{suffix}.child",
        root_assignment_id=f"assignment.{suffix}.root",
        child_assignment_id=f"assignment.{suffix}.child",
        root_attempt_id=f"attempt.{suffix}.root.1",
        child_attempt_id=f"attempt.{suffix}.child.1",
        root_dispatch_id=f"dispatch.{suffix}.root.1",
        child_dispatch_id=f"dispatch.{suffix}.child.1",
        current_dispatch_id=f"dispatch.{suffix}.root.2",
        root_checkpoint_id=f"checkpoint.{suffix}.root",
        child_checkpoint_id=f"checkpoint.{suffix}.child",
    )


def seed_runtime_scope(connection: Connection, *, suffix: str = "a") -> RuntimeIds:
    ids = runtime_ids(suffix)
    _seed_task(connection, ids=ids)
    _seed_compiled_plan(connection, ids=ids)
    _seed_task_compose_and_workspace(connection, ids=ids)
    _seed_flow_shell(connection, ids=ids)
    _seed_flow_nodes(connection, ids=ids)
    _seed_assignments_and_attempts(connection, ids=ids, timestamp=FIXTURE_TIMESTAMP)
    _seed_dispatch_lineage(connection, ids=ids, timestamp=FIXTURE_TIMESTAMP)
    _seed_checkpoints(connection, ids=ids, timestamp=FIXTURE_TIMESTAMP)
    _set_active_runtime_heads(connection, ids=ids)
    return ids


def _seed_task(connection: Connection, *, ids: RuntimeIds) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["tasks"].insert(),
        {
            "task_id": ids.task_id,
            "task_key": f"task-key.{ids.suffix}",
            "title": f"Target task {ids.suffix}",
            "summary": "Target runtime schema fixture.",
            "instruction": None,
            "workflow_key": "workflow.target",
            "task_root_path": f"/tmp/autoclaw-task-{ids.suffix}",
            "created_at": FIXTURE_TIMESTAMP,
            "updated_at": FIXTURE_TIMESTAMP,
        },
    )
    connection.execute(
        tables["task_event_stream_heads"].insert(),
        {"task_id": ids.task_id},
    )


def _seed_compiled_plan(connection: Connection, *, ids: RuntimeIds) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["compiled_plans"].insert(),
        {
            "compiled_plan_id": ids.compiled_plan_id,
            "task_id": ids.task_id,
            "workflow_key": "workflow.target",
            "definition_revision_no": 1,
            "compiler_version": "schema-contract-test",
            "snapshot_json": {},
            "created_at": FIXTURE_TIMESTAMP,
        },
    )
    for order_index, (node_key, parent_node_key, structural_kind) in enumerate(
        (("root", None, "root"), ("child", "root", "worker"))
    ):
        connection.execute(
            tables["compiled_plan_nodes"].insert(),
            {
                "compiled_plan_node_id": (f"compiled-plan-node.{ids.suffix}.{node_key}"),
                "compiled_plan_id": ids.compiled_plan_id,
                "node_key": node_key,
                "parent_node_key": parent_node_key,
                "structural_kind": structural_kind,
                "role_key": "role.target",
                "role_revision_no": 1,
                "role_description": "Target role.",
                "role_instruction": None,
                "policy_key": "policy.target",
                "policy_revision_no": 1,
                "policy_description": "Target policy.",
                "policy_instruction": None,
                "description": f"{node_key} node",
                "node_instruction": None,
                "child_node_keys_json": ["child"] if node_key == "root" else [],
                "consumes_json": None,
                "produces_json": None,
                "criteria_json": [],
                "child_defaults_json": None,
                "provider_kind": "codex",
                "order_index": order_index,
            },
        )
    connection.execute(
        tables["compiled_plan_edges"].insert(),
        {
            "compiled_plan_edge_id": (f"compiled-plan-edge.{ids.suffix}.root-child"),
            "compiled_plan_id": ids.compiled_plan_id,
            "provider_node_key": "root",
            "consumer_node_key": "child",
            "kind": "artifact",
            "slot": "input",
            "description": "Root output consumed by child.",
            "order_index": 0,
        },
    )


def _seed_task_compose_and_workspace(connection: Connection, *, ids: RuntimeIds) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["task_composes"].insert(),
        {
            "task_compose_id": f"task-compose.{ids.suffix}",
            "task_id": ids.task_id,
            "workflow_key": "workflow.target",
            "workflow_revision_no": 1,
            "compiled_plan_id": ids.compiled_plan_id,
            "compose_payload": {},
            "created_at": FIXTURE_TIMESTAMP,
        },
    )
    connection.execute(
        tables["workspace_bindings"].insert(),
        {
            "workspace_binding_id": f"workspace-binding.{ids.suffix}",
            "task_id": ids.task_id,
            "binding_mode": "external",
            "normalized_root_path": "/tmp/shared-workspace",
            "bound_at": FIXTURE_TIMESTAMP,
        },
    )


def _seed_flow_shell(connection: Connection, *, ids: RuntimeIds) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["flows"].insert(),
        {
            "flow_id": ids.flow_id,
            "task_id": ids.task_id,
            "compiled_plan_id": ids.compiled_plan_id,
            "status": "running",
            "terminal_outcome": None,
            "active_flow_revision_id": None,
            "current_dispatch_id": None,
            "waiting_cause": "none",
            "waiting_source_id": None,
            "control_revision": 0,
            "pause_reason": None,
            "pause_details": None,
            "paused_at": None,
            "paused_by_actor_ref": None,
            "created_at": FIXTURE_TIMESTAMP,
            "updated_at": FIXTURE_TIMESTAMP,
        },
    )
    connection.execute(
        tables["flow_revisions"].insert(),
        {
            "flow_revision_id": ids.flow_revision_id,
            "flow_id": ids.flow_id,
            "revision_no": 1,
            "parent_flow_revision_id": None,
            "source_compiled_plan_id": ids.compiled_plan_id,
            "cause": "launch",
            "created_by_dispatch_id": None,
            "snapshot_json": {},
            "adopted_at": FIXTURE_TIMESTAMP,
        },
    )


def _set_active_runtime_heads(connection: Connection, *, ids: RuntimeIds) -> None:
    flows = RuntimeBase.metadata.tables["flows"]
    connection.execute(
        flows.update()
        .where(flows.c.flow_id == ids.flow_id)
        .values(
            active_flow_revision_id=ids.flow_revision_id,
            current_dispatch_id=ids.current_dispatch_id,
        )
    )


def _seed_flow_nodes(
    connection: Connection,
    *,
    ids: RuntimeIds,
) -> None:
    tables = RuntimeBase.metadata.tables
    for order_index, (flow_node_id, node_key, parent_node_key, structural_kind) in enumerate(
        (
            (ids.root_node_id, "root", None, "root"),
            (ids.child_node_id, "child", "root", "worker"),
        )
    ):
        connection.execute(
            tables["flow_nodes"].insert(),
            {
                "flow_node_id": flow_node_id,
                "flow_id": ids.flow_id,
                "flow_revision_id": ids.flow_revision_id,
                "node_key": node_key,
                "parent_node_key": parent_node_key,
                "node_kind": structural_kind,
                "role_key": "role.target",
                "role_revision_no": 1,
                "role_description": "Target role.",
                "role_instruction": None,
                "policy_key": "policy.target",
                "policy_revision_no": 1,
                "policy_description": "Target policy.",
                "policy_instruction": None,
                "description": f"{node_key} flow node",
                "node_instruction": None,
                "child_node_keys_json": ["child"] if node_key == "root" else [],
                "consumes_json": None,
                "produces_json": None,
                "criteria_json": [],
                "child_defaults_json": None,
                "state": "running",
                "current_assignment_id": None,
                "order_index": order_index,
            },
        )
        connection.execute(
            tables["node_plan_revisions"].insert(),
            {
                "node_plan_revision_id": f"node-plan-revision.{ids.suffix}.{node_key}",
                "flow_id": ids.flow_id,
                "flow_revision_id": ids.flow_revision_id,
                "flow_node_id": flow_node_id,
                "role_key": "role.target",
                "role_revision_no": 1,
                "role_description": "Target role.",
                "role_instruction": None,
                "policy_key": "policy.target",
                "policy_revision_no": 1,
                "policy_description": "Target policy.",
                "policy_instruction": None,
            },
        )
    connection.execute(
        tables["flow_edges"].insert(),
        {
            "flow_edge_id": f"flow-edge.{ids.suffix}.root-child",
            "flow_revision_id": ids.flow_revision_id,
            "provider_node_key": "root",
            "consumer_node_key": "child",
            "kind": "artifact",
            "slot": "input",
            "description": "Root output consumed by child.",
            "order_index": 0,
        },
    )


def _seed_assignments_and_attempts(
    connection: Connection,
    *,
    ids: RuntimeIds,
    timestamp: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    rows = (
        (ids.root_assignment_id, ids.root_node_id, "root", None, ids.root_attempt_id),
        (
            ids.child_assignment_id,
            ids.child_node_id,
            "child",
            ids.root_assignment_id,
            ids.child_attempt_id,
        ),
    )
    for assignment_id, flow_node_id, node_key, parent_assignment_id, attempt_id in rows:
        connection.execute(
            tables["assignments"].insert(),
            {
                "assignment_id": assignment_id,
                "task_id": ids.task_id,
                "flow_id": ids.flow_id,
                "flow_revision_id": ids.flow_revision_id,
                "flow_node_id": flow_node_id,
                "assignment_key": f"assignment-key.{ids.suffix}.{node_key}",
                "node_key": node_key,
                "parent_assignment_id": parent_assignment_id,
                "summary": f"{node_key} assignment",
                "instruction": None,
                "criteria_json": [],
                "consumes_json": [],
                "produces_json": [],
                "current_attempt_id": None,
                "work_plan_revision": 0,
                "created_by_dispatch_id": None,
                "created_at": timestamp,
                "superseded_at": None,
            },
        )
        connection.execute(
            tables["attempts"].insert(),
            {
                "attempt_id": attempt_id,
                "assignment_id": assignment_id,
                "task_id": ids.task_id,
                "flow_id": ids.flow_id,
                "node_key": node_key,
                "retry_of_attempt_id": None,
                "status": "running",
                "terminal_outcome": None,
                "opened_at": timestamp,
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
            .where(tables["flow_nodes"].c.flow_node_id == flow_node_id)
            .values(current_assignment_id=assignment_id)
        )
    connection.execute(
        tables["assignment_criteria_refs"].insert(),
        {
            "assignment_criteria_ref_id": f"criteria-ref.{ids.suffix}.root.0",
            "assignment_id": ids.root_assignment_id,
            "slot": "criteria",
            "logical_path": "_runtime/criteria/root.md",
            "description": "Root criteria.",
            "version": 1,
            "order_index": 0,
        },
    )


def _seed_dispatch_lineage(
    connection: Connection,
    *,
    ids: RuntimeIds,
    timestamp: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["flow_start_sources"].insert(),
        {
            "flow_id": ids.flow_id,
            "task_id": ids.task_id,
            "successor_dispatch_id": None,
            "committed_at": timestamp,
        },
    )
    for row in _dispatch_fixture_rows(ids, timestamp):
        _insert_dispatch_fixture(connection, ids=ids, row=row, timestamp=timestamp)
    connection.execute(
        tables["flow_start_sources"]
        .update()
        .where(tables["flow_start_sources"].c.flow_id == ids.flow_id)
        .values(successor_dispatch_id=ids.root_dispatch_id)
    )


def _dispatch_fixture_rows(
    ids: RuntimeIds,
    timestamp: datetime,
) -> tuple[DispatchFixtureRow, ...]:
    return (
        DispatchFixtureRow(
            dispatch_id=ids.root_dispatch_id,
            assignment_id=ids.root_assignment_id,
            attempt_id=ids.root_attempt_id,
            node_key="root",
            flow_start_source_flow_id=ids.flow_id,
            predecessor_dispatch_id=None,
            status="closed",
            opened_reason="root",
            adapter_started_at=timestamp,
            closed_at=timestamp,
            closed_reason="boundary",
        ),
        DispatchFixtureRow(
            dispatch_id=ids.child_dispatch_id,
            assignment_id=ids.child_assignment_id,
            attempt_id=ids.child_attempt_id,
            node_key="child",
            flow_start_source_flow_id=None,
            predecessor_dispatch_id=ids.root_dispatch_id,
            status="closed",
            opened_reason="boundary",
            adapter_started_at=timestamp,
            closed_at=timestamp,
            closed_reason="boundary",
        ),
        DispatchFixtureRow(
            dispatch_id=ids.current_dispatch_id,
            assignment_id=ids.root_assignment_id,
            attempt_id=ids.root_attempt_id,
            node_key="root",
            flow_start_source_flow_id=None,
            predecessor_dispatch_id=ids.child_dispatch_id,
            status="open",
            opened_reason="child_return",
            adapter_started_at=timestamp,
            closed_at=None,
            closed_reason=None,
        ),
    )


def _insert_dispatch_fixture(
    connection: Connection,
    *,
    ids: RuntimeIds,
    row: DispatchFixtureRow,
    timestamp: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["dispatch_turns"].insert(),
        {
            "dispatch_id": row.dispatch_id,
            "task_id": ids.task_id,
            "flow_id": ids.flow_id,
            "assignment_id": row.assignment_id,
            "attempt_id": row.attempt_id,
            "node_key": row.node_key,
            "flow_start_source_flow_id": row.flow_start_source_flow_id,
            "predecessor_dispatch_id": row.predecessor_dispatch_id,
            "status": row.status,
            "opened_reason": row.opened_reason,
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
            "created_at": timestamp,
            "adapter_started_at": row.adapter_started_at,
            "last_node_activity_at": row.adapter_started_at,
            "node_activity_revision": 0,
            "closed_at": row.closed_at,
            "closed_reason": row.closed_reason,
        },
    )
    _insert_dispatch_prompt_refs(connection, row.dispatch_id, timestamp)
    _insert_dispatch_capability_set(connection, row.dispatch_id, timestamp)


def _insert_dispatch_prompt_refs(
    connection: Connection,
    dispatch_id: str,
    timestamp: datetime,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["dispatch_prompt_refs"].insert(),
        {
            "dispatch_id": dispatch_id,
            "instructions_logical_path": (f"_runtime/dispatch/{dispatch_id}/instructions.md"),
            "input_logical_path": f"_runtime/dispatch/{dispatch_id}/input.md",
            "dynamic_input_version": 1,
            "created_at": timestamp,
        },
    )


def _insert_dispatch_capability_set(
    connection: Connection,
    dispatch_id: str,
    timestamp: datetime,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["dispatch_capability_sets"].insert(),
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
            "created_at": timestamp,
        },
    )


def _seed_checkpoints(
    connection: Connection,
    *,
    ids: RuntimeIds,
    timestamp: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    rows = (
        (
            ids.root_checkpoint_id,
            ids.root_assignment_id,
            ids.root_attempt_id,
            ids.root_dispatch_id,
            "green",
        ),
        (
            ids.child_checkpoint_id,
            ids.child_assignment_id,
            ids.child_attempt_id,
            ids.child_dispatch_id,
            "blocked",
        ),
    )
    for checkpoint_id, assignment_id, attempt_id, dispatch_id, outcome in rows:
        connection.execute(
            tables["attempt_checkpoints"].insert(),
            {
                "checkpoint_id": checkpoint_id,
                "task_id": ids.task_id,
                "flow_id": ids.flow_id,
                "assignment_id": assignment_id,
                "attempt_id": attempt_id,
                "authoring_dispatch_id": dispatch_id,
                "checkpoint_kind": "terminal",
                "outcome": outcome,
                "summary": f"{outcome} checkpoint",
                "evidence_json": {},
                "criteria_results_json": [],
                "recorded_at": timestamp,
            },
        )


__all__ = [
    "RuntimeIds",
    "runtime_ids",
    "seed_runtime_scope",
]
