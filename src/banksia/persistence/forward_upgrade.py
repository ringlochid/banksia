from __future__ import annotations

from typing import cast

from sqlalchemy import CheckConstraint, MetaData, Table
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateIndex, CreateTable

from banksia.persistence.models import TaskEventModel
from banksia.persistence.schema_contract import (
    schema_mismatch_messages,
    verify_schema_contract,
)

ATTEMPT_WATCHDOG_REPLACEMENT_BUDGET_UPGRADE = "attempt-watchdog-replacement-budget"
MEMBER_STEERING_EVENTS_UPGRADE = "member-steering-events"
ATTEMPT_WATCHDOG_AND_MEMBER_STEERING_UPGRADE = (
    "attempt-watchdog-replacement-budget-and-member-steering-events"
)
COMMAND_EXIT_CODE_WIDTH_UPGRADE = "command-exit-code-width"
_ATTEMPT_WATCHDOG_PREDECESSOR_DIFFERENCES = frozenset(
    {
        "attempts missing column watchdog_replacement_count",
        "attempts missing or changed check constraint ck_attempts_watchdog_replacement_count",
    }
)
_MEMBER_STEERING_EVENT_DIFFERENCES = frozenset(
    {
        "task_events missing or changed check constraint ck_task_events_event_type",
        "task_events unexpected or changed check constraint ck_task_events_event_type",
    }
)
_COMMAND_EXIT_CODE_WIDTH_DIFFERENCES = frozenset(
    {
        "command_runs changed column terminal_exit_code: expected "
        "('BIGINT', True, None, None), found ('INTEGER', True, None, None)"
    }
)
_UPGRADE_STEPS = (
    (
        ATTEMPT_WATCHDOG_REPLACEMENT_BUDGET_UPGRADE,
        _ATTEMPT_WATCHDOG_PREDECESSOR_DIFFERENCES,
    ),
    (MEMBER_STEERING_EVENTS_UPGRADE, _MEMBER_STEERING_EVENT_DIFFERENCES),
    (COMMAND_EXIT_CODE_WIDTH_UPGRADE, _COMMAND_EXIT_CODE_WIDTH_DIFFERENCES),
)


class DatabaseSchemaUpgradeUnavailableError(RuntimeError):
    """Raised when no registered forward upgrade matches the complete schema."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = tuple(messages)
        joined = "; ".join(messages)
        super().__init__(
            f"no supported data-preserving database upgrade matches this schema: {joined}"
        )


def execute_database_upgrade(
    connection: Connection,
    *,
    schema_name: str | None,
    expected_upgrade: str,
) -> bool:
    """Execute one still-current upgrade and verify the resulting exact schema."""

    pending_upgrade = identify_pending_database_upgrade(connection, schema_name)
    if pending_upgrade is None:
        return False
    if pending_upgrade != expected_upgrade:
        raise DatabaseSchemaUpgradeUnavailableError(
            [
                f"expected upgrade {expected_upgrade!r}, "
                f"but current schema requires {pending_upgrade!r}"
            ]
        )
    selected_steps = _selected_upgrade_steps(pending_upgrade)
    if ATTEMPT_WATCHDOG_REPLACEMENT_BUDGET_UPGRADE in selected_steps:
        _add_attempt_watchdog_replacement_budget(connection, schema_name=schema_name)
    if MEMBER_STEERING_EVENTS_UPGRADE in selected_steps:
        _upgrade_task_event_type_constraint(connection, schema_name=schema_name)
    if COMMAND_EXIT_CODE_WIDTH_UPGRADE in selected_steps:
        _upgrade_command_exit_code_width(connection, schema_name=schema_name)
    verify_schema_contract(connection, schema_name)
    return True


def identify_pending_database_upgrade(
    connection: Connection,
    schema_name: str | None,
) -> str | None:
    """Identify one exact registered predecessor or reject the whole schema."""

    messages = schema_mismatch_messages(connection, schema_name)
    if not messages:
        return None
    differences = frozenset(messages)
    selected = tuple(name for name, owned in _UPGRADE_STEPS if owned <= differences)
    recognized = frozenset().union(*(owned for name, owned in _UPGRADE_STEPS if name in selected))
    if selected and differences == recognized:
        return "-and-".join(selected)
    raise DatabaseSchemaUpgradeUnavailableError(messages)


def _selected_upgrade_steps(upgrade: str) -> tuple[str, ...]:
    selected = tuple(name for name, _differences in _UPGRADE_STEPS if name in upgrade)
    if not selected or "-and-".join(selected) != upgrade:
        raise DatabaseSchemaUpgradeUnavailableError(
            [f"registered upgrade {upgrade!r} has no implementation"]
        )
    return selected


def _add_attempt_watchdog_replacement_budget(
    connection: Connection,
    *,
    schema_name: str | None,
) -> None:
    attempts_table = _qualified_table_name(
        connection,
        schema_name=schema_name,
        table_name="attempts",
    )
    column_contract = "watchdog_replacement_count INTEGER DEFAULT '0' NOT NULL"
    check_contract = (
        "CONSTRAINT ck_attempts_watchdog_replacement_count CHECK (watchdog_replacement_count >= 0)"
    )
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            f"ALTER TABLE {attempts_table} ADD COLUMN {column_contract} {check_contract}"
        )
        return
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(f"ALTER TABLE {attempts_table} ADD COLUMN {column_contract}")
        connection.exec_driver_sql(f"ALTER TABLE {attempts_table} ADD {check_contract}")
        return
    raise DatabaseSchemaUpgradeUnavailableError(
        [f"database backend {connection.dialect.name!r} has no supported upgrade path"]
    )


def _qualified_table_name(
    connection: Connection,
    *,
    schema_name: str | None,
    table_name: str,
) -> str:
    preparer = connection.dialect.identifier_preparer
    quoted_table = preparer.quote_identifier(table_name)
    if schema_name is None:
        return quoted_table
    return f"{preparer.quote_identifier(schema_name)}.{quoted_table}"


def _upgrade_task_event_type_constraint(
    connection: Connection,
    *,
    schema_name: str | None,
) -> None:
    if connection.dialect.name == "sqlite":
        _rebuild_sqlite_task_events(connection)
        return
    if connection.dialect.name == "postgresql":
        table_name = _qualified_table_name(
            connection,
            schema_name=schema_name,
            table_name="task_events",
        )
        constraint = next(
            item
            for item in cast(Table, TaskEventModel.__table__).constraints
            if isinstance(item, CheckConstraint) and item.name == "ck_task_events_event_type"
        )
        sql = str(
            constraint.sqltext.compile(
                dialect=connection.dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        connection.exec_driver_sql(
            f"ALTER TABLE {table_name} DROP CONSTRAINT ck_task_events_event_type"
        )
        connection.exec_driver_sql(
            f"ALTER TABLE {table_name} ADD CONSTRAINT ck_task_events_event_type CHECK ({sql})"
        )
        return
    raise DatabaseSchemaUpgradeUnavailableError(
        [f"database backend {connection.dialect.name!r} has no supported upgrade path"]
    )


def _rebuild_sqlite_task_events(connection: Connection) -> None:
    _rebuild_sqlite_table(
        connection,
        cast(Table, TaskEventModel.__table__),
        temporary_name="_banksia_upgrade_task_events",
    )


def _upgrade_command_exit_code_width(
    connection: Connection,
    *,
    schema_name: str | None,
) -> None:
    if connection.dialect.name == "postgresql":
        table_name = _qualified_table_name(
            connection,
            schema_name=schema_name,
            table_name="command_runs",
        )
        connection.exec_driver_sql(
            f"ALTER TABLE {table_name} ALTER COLUMN terminal_exit_code TYPE BIGINT"
        )
        return
    raise DatabaseSchemaUpgradeUnavailableError(
        [f"database backend {connection.dialect.name!r} has no supported upgrade path"]
    )


def _rebuild_sqlite_table(
    connection: Connection,
    source: Table,
    *,
    temporary_name: str,
) -> None:
    metadata = MetaData()
    for table in source.metadata.tables.values():
        if table is not source:
            table.to_metadata(metadata)
    temporary = source.to_metadata(metadata, name=temporary_name)
    preparer = connection.dialect.identifier_preparer
    quoted_source = preparer.quote_identifier(source.name)
    quoted_temporary = preparer.quote_identifier(temporary_name)
    columns = ", ".join(preparer.quote_identifier(column.name) for column in source.columns)
    connection.execute(CreateTable(temporary))
    connection.exec_driver_sql(
        f"INSERT INTO {quoted_temporary} ({columns}) SELECT {columns} FROM {quoted_source}"
    )
    connection.exec_driver_sql(f"DROP TABLE {quoted_source}")
    connection.exec_driver_sql(f"ALTER TABLE {quoted_temporary} RENAME TO {quoted_source}")
    for index in sorted(source.indexes, key=lambda item: item.name or ""):
        connection.execute(CreateIndex(index))


__all__ = [
    "ATTEMPT_WATCHDOG_AND_MEMBER_STEERING_UPGRADE",
    "ATTEMPT_WATCHDOG_REPLACEMENT_BUDGET_UPGRADE",
    "COMMAND_EXIT_CODE_WIDTH_UPGRADE",
    "MEMBER_STEERING_EVENTS_UPGRADE",
    "DatabaseSchemaUpgradeUnavailableError",
    "execute_database_upgrade",
    "identify_pending_database_upgrade",
]
