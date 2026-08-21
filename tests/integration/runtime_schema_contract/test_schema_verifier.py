from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine

from oh_my_subagents.persistence.schema_contract import (
    normalize_schema_sql,
    schema_mismatch_messages,
    verify_schema_contract,
)
from oh_my_subagents.persistence.session import DatabaseSchemaMismatchError
from tests.helpers.sqlite_runtime import (
    create_runtime_schema_engine,
    rewrite_empty_sqlite_table,
)


def _messages(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return schema_mismatch_messages(connection, None)


def _verify(engine: Engine) -> None:
    with engine.connect() as connection:
        verify_schema_contract(connection, None)


def test_exact_schema_verifier_accepts_a_fresh_target_schema(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        assert _messages(engine) == []
        _verify(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("postgresql_reflection", "metadata_sql"),
    (
        (
            "((status)::text = ANY ((ARRAY['running'::character varying, "
            "'paused'::character varying])::text[]))",
            "status IN ('running', 'paused')",
        ),
        (
            "((status)::text <> ALL ((ARRAY['completed'::character varying, "
            "'cancelled'::character varying])::text[]))",
            "status NOT IN ('completed', 'cancelled')",
        ),
        (
            "CASE WHEN ((status)::text = ANY ((ARRAY['starting'::character varying, "
            "'open'::character varying])::text[])) THEN 1 ELSE NULL::integer END",
            "CASE WHEN status IN ('starting', 'open') THEN 1 ELSE NULL END",
        ),
    ),
)
def test_schema_verifier_normalizes_postgresql_array_rendering(
    postgresql_reflection: str,
    metadata_sql: str,
) -> None:
    assert normalize_schema_sql(postgresql_reflection) == normalize_schema_sql(metadata_sql)


@pytest.mark.parametrize(
    ("postgresql_reflection", "metadata_sql"),
    (
        (
            "state = 'pending' AND started_at IS NULL OR "
            "state = 'running' AND started_at IS NOT NULL",
            "(state = 'pending' AND started_at IS NULL) OR "
            "(state = 'running' AND started_at IS NOT NULL)",
        ),
        (
            "order_index >= 0 AND order_index <= 8",
            "order_index BETWEEN 0 AND 8",
        ),
        (
            "length(TRIM(BOTH FROM model_override)) > 0",
            "length(trim(model_override)) > 0",
        ),
    ),
)
def test_schema_verifier_normalizes_postgresql_decompiled_check_sql(
    postgresql_reflection: str,
    metadata_sql: str,
) -> None:
    assert normalize_schema_sql(postgresql_reflection) == normalize_schema_sql(metadata_sql)


def test_schema_verifier_preserves_material_boolean_grouping() -> None:
    assert normalize_schema_sql("enabled AND (first OR second)") != normalize_schema_sql(
        "(enabled AND first) OR second"
    )


@pytest.mark.parametrize(
    ("table_name", "transform", "expected_message"),
    (
        (
            "node_invocations",
            lambda ddl: ddl.replace(
                "\tlogical_tool_name VARCHAR(255) NOT NULL, \n",
                "",
            ),
            "node_invocations missing column logical_tool_name",
        ),
        (
            "node_invocations",
            lambda ddl: ddl.replace(
                "logical_tool_name VARCHAR(255) NOT NULL",
                "logical_tool_name TEXT NOT NULL",
            ),
            "node_invocations changed column logical_tool_name",
        ),
        (
            "node_invocations",
            lambda ddl: ddl.replace(
                "logical_tool_name VARCHAR(255) NOT NULL",
                "logical_tool_name VARCHAR(255)",
            ),
            "node_invocations changed column logical_tool_name",
        ),
        (
            "dispatch_turns",
            lambda ddl: ddl.replace(
                "node_activity_revision INTEGER DEFAULT '0' NOT NULL",
                "node_activity_revision INTEGER DEFAULT '1' NOT NULL",
            ),
            "dispatch_turns changed column node_activity_revision",
        ),
        (
            "tasks",
            lambda ddl: ddl.replace(
                "PRIMARY KEY (task_id)",
                "PRIMARY KEY (workflow_key)",
            ),
            "tasks changed primary key",
        ),
        (
            "team_revision_members",
            lambda ddl: ddl.replace(
                ", \n\tCONSTRAINT uq_team_revision_members_exact_selection "
                "UNIQUE (task_id, team_revision_id, member_id, "
                "member_configuration_id, member_branch_basis_id)",
                "",
            ),
            "team_revision_members missing unique constraint "
            "('task_id', 'team_revision_id', 'member_id', "
            "'member_configuration_id', 'member_branch_basis_id')",
        ),
        (
            "node_invocations",
            lambda ddl: ddl.replace(
                ", \n\tCONSTRAINT fk_node_invocations_dispatch_owner "
                "FOREIGN KEY(dispatch_id, task_id) REFERENCES dispatch_turns "
                "(dispatch_id, task_id) DEFERRABLE INITIALLY DEFERRED",
                "",
            ),
            "node_invocations missing foreign key",
        ),
        (
            "node_invocations",
            lambda ddl: ddl.replace(
                "DEFERRABLE INITIALLY DEFERRED",
                "NOT DEFERRABLE",
            ),
            "node_invocations missing foreign key",
        ),
        (
            "task_events",
            lambda ddl: ddl.replace("event_seq >= 1", "event_seq >= 0"),
            "task_events missing or changed check constraint ck_task_events_event_seq",
        ),
        (
            "task_event_stream_heads",
            lambda ddl: ddl.replace("allocator_revision >= 0", "allocator_revision >= -1"),
            "task_event_stream_heads missing or changed check constraint "
            "ck_task_event_stream_heads_allocator_revision",
        ),
    ),
)
def test_exact_schema_verifier_rejects_changed_table_contracts(
    tmp_path: Path,
    table_name: str,
    transform: Callable[[str], str],
    expected_message: str,
) -> None:
    database_path = tmp_path / "runtime.sqlite"
    engine = create_runtime_schema_engine(tmp_path)
    engine.dispose()
    rewrite_empty_sqlite_table(
        database_path,
        table_name=table_name,
        transform=transform,
    )
    engine = _create_runtime_schema_engine_for_existing_file(database_path)
    try:
        messages = _messages(engine)
        assert any(expected_message in message for message in messages)
        with pytest.raises(DatabaseSchemaMismatchError, match="does not match"):
            _verify(engine)
    finally:
        engine.dispose()


def test_exact_schema_verifier_rejects_missing_and_unexpected_tables(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE node_invocations")
            connection.exec_driver_sql("CREATE TABLE legacy_runtime_truth (id INTEGER)")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN compatibility_state TEXT")
        messages = _messages(engine)
        assert "missing table node_invocations" in messages
        assert "unexpected table legacy_runtime_truth" in messages
        assert "tasks unexpected column compatibility_state" in messages
    finally:
        engine.dispose()


def test_exact_schema_verifier_rejects_a_missing_required_index(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite"
    engine = create_runtime_schema_engine(tmp_path)
    engine.dispose()
    rewrite_empty_sqlite_table(
        database_path,
        table_name="dispatch_turns",
        transform=lambda ddl: ddl,
        omitted_indexes=frozenset({"ix_dispatch_turns_start_due"}),
    )
    engine = _create_runtime_schema_engine_for_existing_file(database_path)
    try:
        assert any(
            "dispatch_turns missing or changed index ix_dispatch_turns_start_due" in message
            for message in _messages(engine)
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "index_transform",
    (
        lambda name, ddl: (
            ddl.replace(
                "(status, next_provider_start_at)",
                "(status, created_at)",
            )
            if name == "ix_dispatch_turns_start_due"
            else ddl
        ),
        lambda name, ddl: (
            ddl.replace("CREATE INDEX", "CREATE UNIQUE INDEX", 1)
            if name == "ix_dispatch_turns_start_due"
            else ddl
        ),
        lambda name, ddl: (
            ddl.replace(
                "status IN ('starting', 'open')",
                "status = 'open'",
            )
            if name == "uq_dispatch_turns_one_current_per_attempt"
            else ddl
        ),
    ),
    ids=("changed-columns", "changed-uniqueness", "changed-predicate"),
)
def test_exact_schema_verifier_rejects_changed_required_indexes(
    tmp_path: Path,
    index_transform: Callable[[str, str], str],
) -> None:
    database_path = tmp_path / "runtime.sqlite"
    engine = create_runtime_schema_engine(tmp_path)
    engine.dispose()
    rewrite_empty_sqlite_table(
        database_path,
        table_name="dispatch_turns",
        transform=lambda ddl: ddl,
        index_transform=index_transform,
    )
    engine = _create_runtime_schema_engine_for_existing_file(database_path)
    try:
        assert any(
            "dispatch_turns missing or changed index" in message for message in _messages(engine)
        )
    finally:
        engine.dispose()


def _create_runtime_schema_engine_for_existing_file(database_path: Path) -> Engine:
    return create_engine(f"sqlite:///{database_path}")
