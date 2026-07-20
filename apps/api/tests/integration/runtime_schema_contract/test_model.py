from __future__ import annotations

from typing import cast

import autoclaw.persistence as persistence
from autoclaw.persistence import RuntimeBase
from autoclaw.persistence.session import RuntimeAsyncSession
from sqlalchemy import JSON, Table
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

TARGET_TABLES = {
    "accepted_boundaries",
    "artifact_current_pointers",
    "artifact_publications",
    "assignment_criteria_refs",
    "assignment_decision_artifacts",
    "assignment_decision_checkpoints",
    "assignment_decisions",
    "assignment_work_plan_steps",
    "assignment_work_plans",
    "assignments",
    "attempt_checkpoints",
    "attempts",
    "checkpoint_transients",
    "command_runs",
    "compiled_plan_edges",
    "compiled_plan_nodes",
    "compiled_plans",
    "dispatch_capability_sets",
    "dispatch_prompt_refs",
    "dispatch_turns",
    "flow_edges",
    "flow_nodes",
    "flow_revisions",
    "flow_start_sources",
    "flow_waits",
    "flows",
    "human_requests",
    "node_invocations",
    "node_plan_revisions",
    "policy_definitions",
    "policy_revisions",
    "role_definitions",
    "role_revisions",
    "task_composes",
    "task_events",
    "task_event_stream_heads",
    "tasks",
    "transient_localizations",
    "workflow_definitions",
    "workflow_revisions",
    "workspace_bindings",
}

REMOVED_TABLES = {
    "budget_counters",
    "context_items",
    "context_spaces",
    "dispatch_continuity_states",
    "dispatch_delivery_states",
    "dispatch_watchdog_states",
    "flow_wait_states",
    "manifest_roots",
    "node_sessions",
    "pending_human_requests",
    "provider_event_records",
    "task_resource_bindings",
    "workspace_root_leases",
    "workspace_roots",
}


def test_target_metadata_has_one_complete_table_set_and_no_legacy_shadow_tables() -> None:
    assert set(RuntimeBase.metadata.tables) == TARGET_TABLES
    assert set(RuntimeBase.metadata.tables).isdisjoint(REMOVED_TABLES)
    assert all(table.primary_key.columns for table in RuntimeBase.metadata.tables.values())


def test_every_target_table_has_one_public_persistence_model() -> None:
    exported_models = {
        value.__table__.name
        for name in persistence.__all__
        if isinstance((value := getattr(persistence, name)), type) and hasattr(value, "__table__")
    }

    assert exported_models == TARGET_TABLES


def test_runtime_foreign_keys_have_explicit_lazy_raise_relationship_navigation() -> None:
    configure_mappers()

    runtime_mappers = tuple(
        mapper
        for mapper in RuntimeBase.registry.mappers
        if cast(Table, mapper.local_table).name in TARGET_TABLES
        and not cast(Table, mapper.local_table).name.endswith(("_definitions", "_revisions"))
    )
    unmapped_foreign_keys = {
        (mapper.class_.__name__, column.key)
        for mapper in runtime_mappers
        for column in mapper.columns
        if column.foreign_keys
        and column
        not in set().union(*(relationship.local_columns for relationship in mapper.relationships))
    }

    assert unmapped_foreign_keys == set()
    assert all(
        relationship.lazy == "raise"
        for mapper in runtime_mappers
        for relationship in mapper.relationships
    )


def test_target_metadata_compiles_for_both_supported_database_dialects() -> None:
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        for table in RuntimeBase.metadata.tables.values():
            assert str(CreateTable(table).compile(dialect=dialect)).startswith("\nCREATE TABLE")
            for index in table.indexes:
                assert str(CreateIndex(index).compile(dialect=dialect)).startswith("CREATE")


def test_currentness_marker_ddl_is_stored_and_portable() -> None:
    marker_columns = (
        RuntimeBase.metadata.tables["dispatch_turns"].c.active_status_marker,
        RuntimeBase.metadata.tables["flows"].c.current_dispatch_presence_marker,
        RuntimeBase.metadata.tables["flow_waits"].c.required_current_dispatch_presence_marker,
    )
    assert all(column.computed is not None for column in marker_columns)
    assert all(column.computed.persisted is True for column in marker_columns if column.computed)

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        for table_name in ("dispatch_turns", "flows", "flow_waits"):
            ddl = str(CreateTable(RuntimeBase.metadata.tables[table_name]).compile(dialect=dialect))
            assert "GENERATED ALWAYS AS" in ddl
            assert "STORED" in ddl


def test_runtime_async_session_keeps_ordinary_commit_semantics() -> None:
    assert RuntimeAsyncSession.commit is AsyncSession.commit


def test_json_columns_persist_python_none_as_database_null() -> None:
    json_types: list[JSON] = []
    for table in RuntimeBase.metadata.tables.values():
        for column in table.columns:
            column_type = column.type
            if isinstance(column_type, JSON):
                json_types.append(column_type)

    assert json_types
    assert all(column_type.none_as_null for column_type in json_types)
