from __future__ import annotations

from pathlib import Path

from banksia.persistence import RuntimeBase
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
        "fk_assignments_parent_owner",
    } <= _constraint_names("assignments", ForeignKeyConstraint)
    assert "fk_assignments_flow_node_owner" not in _constraint_names(
        "assignments",
        ForeignKeyConstraint,
    )
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
    assert {
        "fk_accepted_boundaries_source_owner",
        "fk_accepted_boundaries_checkpoint_owner",
        "fk_accepted_boundaries_successor_owner",
    } <= _constraint_names("accepted_boundaries", ForeignKeyConstraint)
    assert {"fk_tasks_result_boundary"} <= _constraint_names(
        "tasks",
        ForeignKeyConstraint,
    )
    assert {
        "fk_human_requests_source_owner",
        "fk_human_requests_successor_owner",
    } <= _constraint_names("human_requests", ForeignKeyConstraint)
    assert {
        "fk_command_runs_source_owner",
        "fk_command_runs_successor_owner",
    } <= _constraint_names("command_runs", ForeignKeyConstraint)
    assert {
        "fk_delegation_waves_source_owner",
        "fk_delegation_waves_parent_attempt_owner",
        "fk_delegation_waves_exact_successor_lineage",
    } <= _constraint_names("delegation_waves", ForeignKeyConstraint)
    assert {
        "fk_delegation_wave_members_wave_owner",
        "fk_delegation_wave_members_child_source",
        "fk_delegation_wave_members_child_owner",
        "fk_delegation_wave_members_child_member",
        "fk_delegation_wave_members_child_node",
        "fk_delegation_wave_members_direct_child",
        "fk_delegation_wave_members_terminal_boundary_owner",
    } <= _constraint_names("delegation_wave_members", ForeignKeyConstraint)


def test_task_event_chronology_constraints_are_present() -> None:
    assert {
        "ck_task_event_stream_heads_allocator_revision",
        "ck_task_event_stream_heads_last_event_pair",
        "ck_task_event_stream_heads_last_event_seq",
    } <= _constraint_names("task_event_stream_heads", CheckConstraint)


def test_target_currentness_and_pair_constraints_are_present() -> None:
    assert (
        "workflow_key",
        "revision_no",
        "content_hash",
    ) in _unique_columns("workflow_revisions")
    assert {
        "ck_dispatch_turns_exact_source_shape",
        "ck_dispatch_turns_lifecycle_fields",
        "ck_dispatch_turns_starting_close_reason",
        "ck_dispatch_turns_watchdog_requires_open",
    } <= _constraint_names("dispatch_turns", CheckConstraint)
    for table_name in ("compiled_plan_nodes", "flow_nodes", "node_plan_revisions"):
        table = RuntimeBase.metadata.tables[table_name]
        assert table.c.team_revision_id.nullable is False
        assert table.c.member_id.nullable is False
        assert table.c.member_configuration_id.nullable is False
        assert table.c.member_branch_basis_id.nullable is False
        assert table.c.provider_kind.nullable is True
    assert {
        "ck_assignments_child_budget",
        "ck_assignments_retry_budget",
        "ck_assignments_terminal_outcome",
        "ck_assignments_terminal_state",
    } <= _constraint_names("assignments", CheckConstraint)
    assert {"ck_accepted_boundaries_source_shape"} <= _constraint_names(
        "accepted_boundaries",
        CheckConstraint,
    )
    assert {
        "team_revision_id",
        "member_configuration_id",
        "member_branch_basis_id",
        "flow_revision_id",
        "flow_node_id",
    }.isdisjoint(RuntimeBase.metadata.tables["assignments"].c.keys())
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
    assert ("source_dispatch_id",) in _unique_columns("accepted_boundaries")
    assert ("source_dispatch_id",) in _unique_columns("human_requests")
    assert ("source_dispatch_id",) in _unique_columns("command_runs")


def test_replan_revision_and_team_root_backstops_are_present() -> None:
    assert (
        "task_id",
        "team_revision_id",
        "predecessor_team_revision_id",
    ) in _unique_columns("team_revisions")
    assert (
        "flow_id",
        "flow_revision_id",
        "parent_flow_revision_id",
    ) in _unique_columns("flow_revisions")
    assert (
        "task_id",
        "team_revision_id",
        "member_id",
        "root_selection_marker",
    ) in _unique_columns("team_revision_members")
    assert (
        "task_id",
        "team_revision_id",
        "root_selection_marker",
    ) in _unique_columns("team_revision_members")
    assert {"fk_team_revisions_selected_root"} <= _constraint_names(
        "team_revisions",
        ForeignKeyConstraint,
    )
    assert {
        "fk_replan_transitions_successor_team_predecessor",
        "fk_replan_transitions_successor_flow_parent",
    } <= _constraint_names("replan_transitions", ForeignKeyConstraint)


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
    assert set(RuntimeBase.metadata.tables["human_request_file_references"].columns.keys()) == {
        "request_id",
        "order_index",
        "path",
        "description",
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
        "summary",
        "timeout_seconds",
        "due_at",
        "output_path",
        "output_observed_bytes",
        "output_written_bytes",
        "output_complete",
        "output_encoding",
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
