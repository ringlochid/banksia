from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, func, select

from oh_my_subagents.persistence import RuntimeBase
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import seed_runtime_scope
from tests.helpers.sqlite_runtime import create_runtime_schema_engine


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


def test_task_owns_lifecycle_team_root_and_result_backstops() -> None:
    assert {
        "fk_tasks_current_team_revision",
        "fk_tasks_result_boundary",
        "fk_tasks_root_assignment",
        "fk_tasks_workflow_revision",
    } <= _constraint_names("tasks", ForeignKeyConstraint)
    assert {
        "ck_tasks_control_revision",
        "ck_tasks_pause_state",
        "ck_tasks_status",
        "ck_tasks_terminal_outcome_status",
    } <= _constraint_names("tasks", CheckConstraint)
    assert {
        "status",
        "terminal_outcome",
        "control_revision",
        "pause_reason",
        "root_assignment_id",
        "current_team_revision_id",
        "result_boundary_id",
    } <= set(RuntimeBase.metadata.tables["tasks"].c.keys())


def test_exact_selection_and_source_backstops_are_present() -> None:
    assert {
        "fk_dispatch_turns_assignment_owner",
        "fk_dispatch_turns_attempt_owner",
        "fk_dispatch_turns_predecessor_owner",
        "fk_dispatch_turns_task_start_source",
        "fk_dispatch_turns_team_selection",
    } <= _constraint_names("dispatch_turns", ForeignKeyConstraint)
    assert {
        "fk_task_start_sources_root_assignment",
        "fk_task_start_sources_root_attempt",
        "fk_task_start_sources_successor_owner",
    } <= _constraint_names("task_start_sources", ForeignKeyConstraint)
    assert (
        "dispatch_id",
        "task_id",
        "assignment_id",
        "attempt_id",
        "team_revision_id",
        "member_id",
        "member_configuration_id",
        "member_branch_basis_id",
    ) in _unique_columns("dispatch_turns")
    assert {
        "flow_id",
        "flow_revision_id",
        "flow_node_id",
        "node_key",
    }.isdisjoint(RuntimeBase.metadata.tables["dispatch_turns"].c.keys())


def test_assignment_and_replan_currentness_are_task_team_scoped() -> None:
    assert {
        "fk_assignments_member",
        "fk_assignments_parent_owner",
    } <= _constraint_names("assignments", ForeignKeyConstraint)
    assert {
        "fk_replan_transitions_source_team_revision",
        "fk_replan_transitions_successor_team_predecessor",
        "fk_replan_transitions_successor_team_revision",
    } <= _constraint_names("replan_transitions", ForeignKeyConstraint)
    assert {
        "source_team_revision_id",
        "successor_team_revision_id",
    } <= set(RuntimeBase.metadata.tables["replan_transitions"].c.keys())
    assert {
        "source_flow_revision_id",
        "successor_flow_revision_id",
    }.isdisjoint(RuntimeBase.metadata.tables["replan_transitions"].c.keys())


def test_external_sources_are_task_scoped_without_flow_columns() -> None:
    for table_name in ("attempt_checkpoints", "human_requests", "command_runs"):
        columns = set(RuntimeBase.metadata.tables[table_name].c.keys())
        assert "task_id" in columns
        assert "flow_id" not in columns
    assert {
        "fk_human_requests_source_owner",
        "fk_human_requests_successor_owner",
    } <= _constraint_names("human_requests", ForeignKeyConstraint)
    assert {
        "fk_command_runs_source_owner",
        "fk_command_runs_successor_owner",
    } <= _constraint_names("command_runs", ForeignKeyConstraint)


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
