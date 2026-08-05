from __future__ import annotations

from sqlalchemy.engine import Connection

from banksia.persistence.schema_contract import (
    schema_mismatch_messages,
    verify_schema_contract,
)

ATTEMPT_WATCHDOG_REPLACEMENT_BUDGET_UPGRADE = "attempt-watchdog-replacement-budget"
_ATTEMPT_WATCHDOG_PREDECESSOR_DIFFERENCES = frozenset(
    {
        "attempts missing column watchdog_replacement_count",
        "attempts missing or changed check constraint ck_attempts_watchdog_replacement_count",
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


__all__ = [
    "ATTEMPT_WATCHDOG_REPLACEMENT_BUDGET_UPGRADE",
    "DatabaseSchemaUpgradeUnavailableError",
    "execute_database_upgrade",
    "identify_pending_database_upgrade",
]
