from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from banksia.persistence import RuntimeBase
from sqlalchemy import Connection

from tests.helpers.assignment_persistence_seed import seed_assignments_and_attempts
from tests.helpers.catalog_seed import WORKFLOW_CONTENT_HASH
from tests.helpers.team_persistence_seed import (
    member_branch_basis_id,
    member_configuration_id,
    seed_team,
    team_revision_id,
)

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
    seed_team(connection, ids=ids, timestamp=FIXTURE_TIMESTAMP)
    _seed_compiled_plan(connection, ids=ids)
    _seed_workspace(connection, ids=ids)
    _seed_flow_shell(connection, ids=ids)
    _seed_flow_nodes(connection, ids=ids)
    seed_assignments_and_attempts(connection, ids=ids, timestamp=FIXTURE_TIMESTAMP)
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
            "workflow_key": "workflow.target",
            "workflow_revision_no": 1,
            "workflow_content_hash": WORKFLOW_CONTENT_HASH,
            "current_team_revision_id": None,
            "max_wave_members": 8,
            "task_root_path": f"/tmp/banksia-task-{ids.suffix}",
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
            "workflow_revision_no": 1,
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
                "task_id": ids.task_id,
                "team_revision_id": team_revision_id(ids),
                "member_id": node_key,
                "member_configuration_id": member_configuration_id(ids, node_key),
                "member_branch_basis_id": member_branch_basis_id(ids, node_key),
                "member_title": f"{node_key.title()} Member",
                "node_key": node_key,
                "parent_node_key": parent_node_key,
                "structural_kind": structural_kind,
                "description": f"{node_key} node",
                "node_instruction": None,
                "child_node_keys_json": ["child"] if node_key == "root" else [],
                "provider_kind": "codex",
                "order_index": order_index,
            },
        )


def _seed_workspace(connection: Connection, *, ids: RuntimeIds) -> None:
    tables = RuntimeBase.metadata.tables
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
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["flows"]
        .update()
        .where(tables["flows"].c.flow_id == ids.flow_id)
        .values(
            active_flow_revision_id=ids.flow_revision_id,
        )
    )
    connection.execute(
        tables["attempts"]
        .update()
        .where(tables["attempts"].c.attempt_id == ids.root_attempt_id)
        .values(current_dispatch_id=ids.current_dispatch_id)
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
                "task_id": ids.task_id,
                "flow_id": ids.flow_id,
                "flow_revision_id": ids.flow_revision_id,
                "team_revision_id": team_revision_id(ids),
                "member_id": node_key,
                "member_configuration_id": member_configuration_id(ids, node_key),
                "member_branch_basis_id": member_branch_basis_id(ids, node_key),
                "member_title": f"{node_key.title()} Member",
                "node_key": node_key,
                "parent_node_key": parent_node_key,
                "node_kind": structural_kind,
                "provider_kind": "codex",
                "description": f"{node_key} flow node",
                "node_instruction": None,
                "child_node_keys_json": ["child"] if node_key == "root" else [],
                "state": "running",
                "current_assignment_id": None,
                "order_index": order_index,
            },
        )
        connection.execute(
            tables["node_plan_revisions"].insert(),
            {
                "node_plan_revision_id": f"node-plan-revision.{ids.suffix}.{node_key}",
                "task_id": ids.task_id,
                "flow_id": ids.flow_id,
                "flow_revision_id": ids.flow_revision_id,
                "flow_node_id": flow_node_id,
                "team_revision_id": team_revision_id(ids),
                "member_id": node_key,
                "member_configuration_id": member_configuration_id(ids, node_key),
                "member_branch_basis_id": member_branch_basis_id(ids, node_key),
                "member_title": f"{node_key.title()} Member",
                "provider_kind": "codex",
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
            predecessor_dispatch_id=None,
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
            predecessor_dispatch_id=ids.root_dispatch_id,
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
            "flow_revision_id": ids.flow_revision_id,
            "flow_node_id": ids.root_node_id if row.node_key == "root" else ids.child_node_id,
            "team_revision_id": team_revision_id(ids),
            "member_id": row.node_key,
            "member_configuration_id": member_configuration_id(ids, row.node_key),
            "member_branch_basis_id": member_branch_basis_id(ids, row.node_key),
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
            "model_source": "provider_configuration",
            "effort_override": None,
            "effort_source": "provider_configuration",
            "gateway_profile": None,
            "gateway_profile_source": None,
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
    _insert_dispatch_request(connection, row.dispatch_id, timestamp)
    _insert_dispatch_capability_set(connection, row.dispatch_id, timestamp)


def _insert_dispatch_request(
    connection: Connection,
    dispatch_id: str,
    timestamp: datetime,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["dispatch_requests"].insert(),
        {
            "dispatch_id": dispatch_id,
            "instructions": "controller instructions\n",
            "input": "<banksia_dispatch_request><direct_team /></banksia_dispatch_request>\n",
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
            "provider_kind": "codex",
            "provider_native_access": "full",
            "provider_native_access_source": "default",
            "network_access": "allow",
            "network_access_source": "default",
            "requested_sandbox_mode": "full_access",
            "requested_sandbox_network": "allow",
            "sandbox_request_source": "default",
            "effective_sandbox_mode": "full_access",
            "effective_sandbox_network": "allow",
            "sandbox_mode_source": "default",
            "sandbox_network_source": "default",
            "requested_human_direction": "allow",
            "requested_human_approval": "allow",
            "requested_human_input": "allow",
            "requested_human_review": "allow",
            "requested_human_request_source": "member_configuration",
            "human_direction": "allow",
            "human_direction_source": "member_configuration",
            "human_approval": "allow",
            "human_approval_source": "member_configuration",
            "human_input": "allow",
            "human_input_source": "member_configuration",
            "human_review": "allow",
            "human_review_source": "member_configuration",
            "requested_command_run": "allow",
            "requested_command_run_source": "member_configuration",
            "command_run": "allow",
            "command_run_source": "member_configuration",
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
                "outcome": outcome,
                "summary": f"{outcome} checkpoint",
                "details": None,
                "recorded_at": timestamp,
            },
        )


__all__ = [
    "RuntimeIds",
    "runtime_ids",
    "seed_runtime_scope",
]
