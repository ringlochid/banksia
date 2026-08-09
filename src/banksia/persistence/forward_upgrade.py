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
    if pending_upgrade == ATTEMPT_WATCHDOG_REPLACEMENT_BUDGET_UPGRADE:
        _add_attempt_watchdog_replacement_budget(connection, schema_name=schema_name)
    elif pending_upgrade == MEMBER_STEERING_EVENTS_UPGRADE:
        _upgrade_task_event_type_constraint(connection, schema_name=schema_name)
    elif pending_upgrade == ATTEMPT_WATCHDOG_AND_MEMBER_STEERING_UPGRADE:
        _add_attempt_watchdog_replacement_budget(connection, schema_name=schema_name)
        _upgrade_task_event_type_constraint(connection, schema_name=schema_name)
    else:
        raise DatabaseSchemaUpgradeUnavailableError(
            [f"registered upgrade {pending_upgrade!r} has no implementation"]
        )
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
    if frozenset(messages) == _ATTEMPT_WATCHDOG_PREDECESSOR_DIFFERENCES:
        return ATTEMPT_WATCHDOG_REPLACEMENT_BUDGET_UPGRADE
    if frozenset(messages) == _MEMBER_STEERING_EVENT_DIFFERENCES:
        return MEMBER_STEERING_EVENTS_UPGRADE
    if frozenset(messages) == (
        _ATTEMPT_WATCHDOG_PREDECESSOR_DIFFERENCES | _MEMBER_STEERING_EVENT_DIFFERENCES
    ):
        return ATTEMPT_WATCHDOG_AND_MEMBER_STEERING_UPGRADE
    raise DatabaseSchemaUpgradeUnavailableError(messages)


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
    source = cast(Table, TaskEventModel.__table__)
    temporary_name = "_banksia_upgrade_task_events"
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
    "MEMBER_STEERING_EVENTS_UPGRADE",
    "DatabaseSchemaUpgradeUnavailableError",
    "execute_database_upgrade",
    "identify_pending_database_upgrade",
]
