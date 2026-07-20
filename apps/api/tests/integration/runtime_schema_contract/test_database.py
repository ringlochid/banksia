from __future__ import annotations

from pathlib import Path

from autoclaw.persistence import RuntimeBase
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, func, select
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    create_runtime_schema_engine,
)


def _constraint_names(table_name: str, constraint_type: type[object]) -> set[str]:
    table = RuntimeBase.metadata.tables[table_name]
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and constraint.name is not None
    }


def _unique_columns(table_name: str) -> set[tuple[str, ...]]:
    table = RuntimeBase.metadata.tables[table_name]
    return {
        tuple(str(column.name) for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_exact_source_and_owner_backstops_are_present() -> None:
    assert {"fk_task_event_stream_heads_task"} <= _constraint_names(
        "task_event_stream_heads", ForeignKeyConstraint
    )
    assert {
        "fk_assignments_authoring_dispatch_owner",
        "fk_assignments_flow_node_owner",
        "fk_assignments_parent_owner",
    } <= _constraint_names("assignments", ForeignKeyConstraint)
    assert {"fk_attempts_latest_checkpoint_owner"} <= _constraint_names(
        "attempts", ForeignKeyConstraint
    )
    assert {
        "fk_dispatch_turns_assignment_owner",
        "fk_dispatch_turns_assignment_node_owner",
        "fk_dispatch_turns_attempt_owner",
        "fk_dispatch_turns_predecessor_owner",
        "fk_dispatch_turns_flow_start_source",
    } <= _constraint_names("dispatch_turns", ForeignKeyConstraint)
    assert {"fk_flows_current_dispatch_owner"} <= _constraint_names("flows", ForeignKeyConstraint)
    assert {
        "fk_flow_waits_unoccupied_flow",
        "fk_flow_waits_human_request_owner",
        "fk_flow_waits_command_run_owner",
    } <= _constraint_names("flow_waits", ForeignKeyConstraint)
    assert {
        "fk_accepted_boundaries_source_owner",
        "fk_accepted_boundaries_checkpoint_owner",
        "fk_accepted_boundaries_decision_owner",
        "fk_accepted_boundaries_successor_owner",
    } <= _constraint_names("accepted_boundaries", ForeignKeyConstraint)
    assert {
        "fk_human_requests_source_owner",
        "fk_human_requests_successor_owner",
    } <= _constraint_names("human_requests", ForeignKeyConstraint)
    assert {
        "fk_command_runs_source_owner",
        "fk_command_runs_successor_owner",
    } <= _constraint_names("command_runs", ForeignKeyConstraint)
    assert {
        "fk_assignment_decisions_child_authoring_source",
        "fk_assignment_decisions_source_revision_owner",
    } <= _constraint_names("assignment_decisions", ForeignKeyConstraint)
    assert {
        "fk_assignment_decision_checkpoints_checkpoint_owner",
        "fk_assignment_decision_checkpoints_decision_owner",
    } <= _constraint_names("assignment_decision_checkpoints", ForeignKeyConstraint)
    assert {
        "fk_assignment_decision_artifacts_publication_owner",
        "fk_assignment_decision_artifacts_decision_owner",
    } <= _constraint_names("assignment_decision_artifacts", ForeignKeyConstraint)


def test_task_event_chronology_constraints_are_present() -> None:
    assert {
        "ck_task_event_stream_heads_allocator_revision",
        "ck_task_event_stream_heads_last_event_pair",
        "ck_task_event_stream_heads_last_event_seq",
    } <= _constraint_names("task_event_stream_heads", CheckConstraint)


def test_target_currentness_and_pair_constraints_are_present() -> None:
    assert {
        "ck_dispatch_turns_exact_source_shape",
        "ck_dispatch_turns_lifecycle_fields",
        "ck_dispatch_turns_starting_close_reason",
        "ck_dispatch_turns_watchdog_requires_open",
    } <= _constraint_names("dispatch_turns", CheckConstraint)
    assert "ck_flows_current_dispatch_excludes_wait_pointer" in _constraint_names(
        "flows", CheckConstraint
    )
    for table_name in ("compiled_plan_nodes", "flow_nodes", "node_plan_revisions"):
        table = RuntimeBase.metadata.tables[table_name]
        assert table.c.policy_key.nullable is False
        assert table.c.policy_revision_no.nullable is False
        assert table.c.policy_description.nullable is False
        assert table.c.provider_kind.nullable is True
    assert {
        "ck_assignments_child_budget",
        "ck_assignments_retry_budget",
    } <= _constraint_names("assignments", CheckConstraint)
    assert {
        "ck_command_runs_abandoned_diagnostic",
        "ck_command_runs_launch_deadline",
    } <= _constraint_names("command_runs", CheckConstraint)
    assert {
        "ck_flow_nodes_provider_kind",
    } <= _constraint_names("flow_nodes", CheckConstraint)
    assert {
        "ck_node_plan_revisions_provider_kind",
    } <= _constraint_names("node_plan_revisions", CheckConstraint)
    assert ("predecessor_dispatch_id",) in _unique_columns("dispatch_turns")
    assert (
        "dispatch_id",
        "task_id",
        "flow_id",
        "active_status_marker",
    ) in _unique_columns("dispatch_turns")
    assert (
        "flow_id",
        "task_id",
        "current_dispatch_presence_marker",
    ) in _unique_columns("flows")
    assert ("source_dispatch_id",) in _unique_columns("accepted_boundaries")
    assert ("source_dispatch_id",) in _unique_columns("human_requests")
    assert ("source_dispatch_id",) in _unique_columns("command_runs")
    assert {index.name for index in RuntimeBase.metadata.tables["dispatch_turns"].indexes} >= {
        "uq_dispatch_turns_one_first_per_flow",
        "uq_dispatch_turns_one_current_per_flow",
    }


def test_target_sources_store_complete_canonical_fields() -> None:
    assert set(RuntimeBase.metadata.tables["human_requests"].columns.keys()) >= {
        "request_id",
        "task_id",
        "flow_id",
        "assignment_id",
        "attempt_id",
        "source_dispatch_id",
        "request_kind",
        "request_summary",
        "request_items_json",
        "context_refs_json",
        "suggested_human_instruction",
        "capability_basis_json",
        "due_at",
        "timeout_policy_json",
        "default_behavior_json",
        "status",
        "resolution_kind",
        "item_responses_json",
        "resolution_policy_basis_json",
        "resolution_summary",
        "resolved_by_actor_ref",
        "resolved_by_surface",
        "successor_dispatch_id",
        "opened_at",
        "resolved_at",
    }
    assert set(RuntimeBase.metadata.tables["command_runs"].columns.keys()) >= {
        "run_id",
        "task_id",
        "flow_id",
        "assignment_id",
        "attempt_id",
        "source_dispatch_id",
        "command_spec_json",
        "cwd_policy_json",
        "environment_refs_json",
        "summary",
        "expected_outputs_json",
        "timeout_seconds",
        "due_at",
        "stdout_logical_path",
        "stderr_logical_path",
        "state",
        "ownership_revision",
        "process_metadata_json",
        "cancellation_requested_at",
        "cancellation_requested_by_actor_ref",
        "terminal_summary",
        "terminal_exit_code",
        "terminal_failure_code",
        "terminal_event_source",
        "terminal_actor_ref",
        "successor_dispatch_id",
        "created_at",
        "started_at",
        "ended_at",
    }


def test_external_workspace_binding_is_not_a_cross_task_lease(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            first = seed_runtime_scope(connection, suffix="first")
            second = seed_runtime_scope(connection, suffix="second")
            bindings = RuntimeBase.metadata.tables["workspace_bindings"]
            count = connection.scalar(
                select(func.count())
                .select_from(bindings)
                .where(bindings.c.normalized_root_path == "/tmp/shared-workspace")
            )
        assert count == 2
        assert first.task_id != second.task_id
    finally:
        engine.dispose()


def test_repeated_task_compose_keys_create_independent_task_runs(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            first = seed_runtime_scope(connection, suffix="first-key-run")
            second = seed_runtime_scope(connection, suffix="second-key-run")
            tasks = RuntimeBase.metadata.tables["tasks"]
            connection.execute(
                tasks.update()
                .where(tasks.c.task_id == second.task_id)
                .values(task_key="task-key.first-key-run")
            )
            count = connection.scalar(
                select(func.count())
                .select_from(tasks)
                .where(tasks.c.task_key == "task-key.first-key-run")
            )
        assert count == 2
        assert first.task_id != second.task_id
    finally:
        engine.dispose()
