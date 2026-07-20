from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import CheckConstraint, Computed, UniqueConstraint, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.sql.schema import Column, DefaultClause, ForeignKeyConstraint, Index, Table
from sqlalchemy.types import TypeEngine

from autoclaw.persistence.schema_sql import (
    ComputedSchemaSignature,
    metadata_computed_signature,
    normalize_schema_sql,
    reflected_computed_signature,
)

SchemaColumnSignature = tuple[str, bool, str | None, ComputedSchemaSignature | None]
SchemaForeignKeySignature = tuple[
    tuple[str, ...],
    str | None,
    str,
    tuple[str, ...],
    str | None,
    str | None,
    bool,
    str | None,
    str | None,
]
SchemaIndexSignature = tuple[str, bool, tuple[str, ...], str | None]
SchemaUniqueSignature = tuple[str, ...]


class DatabaseSchemaMismatchError(RuntimeError):
    """Raised when a nonempty database is not the exact current schema."""


def verify_schema_contract(
    connection: Connection,
    schema_name: str | None,
) -> None:
    """Reject any nonexact schema without issuing repair DDL."""

    messages = schema_mismatch_messages(connection, schema_name)
    if messages:
        raise_schema_mismatch(messages)


def schema_mismatch_messages(
    connection: Connection,
    schema_name: str | None,
) -> list[str]:
    """Return exact schema differences from the registered runtime metadata."""

    expected_tables = _metadata_tables()
    actual_table_names = list_schema_table_names(connection, schema_name)
    expected_table_names = set(expected_tables)
    messages = [
        *(f"missing table {name}" for name in sorted(expected_table_names - actual_table_names)),
        *(f"unexpected table {name}" for name in sorted(actual_table_names - expected_table_names)),
    ]

    for table_name in sorted(expected_table_names & actual_table_names):
        table = expected_tables[table_name]
        messages.extend(
            _table_mismatch_messages(
                connection,
                schema_name=schema_name,
                table_name=table_name,
                table=table,
            )
        )

    return messages


def create_configured_schema(connection: Connection, schema_name: str | None) -> None:
    """Create the configured PostgreSQL schema when one is selected."""

    if schema_name is None:
        return
    quoted_schema = connection.dialect.identifier_preparer.quote_identifier(schema_name)
    connection.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema}")


def list_schema_table_names(
    connection: Connection,
    schema_name: str | None,
) -> set[str]:
    """List tables in the exact configured schema."""

    inspector = inspect(connection)
    if schema_name is not None and not inspector.has_schema(schema_name):
        return set()
    return {str(table_name) for table_name in inspector.get_table_names(schema=schema_name)}


def raise_schema_mismatch(messages: list[str]) -> None:
    """Raise the reset-only schema mismatch error with actionable guidance."""

    joined = "; ".join(messages)
    raise DatabaseSchemaMismatchError(
        "existing database does not match the current reset-only runtime schema: "
        f"{joined}. Run `autoclaw db reset`."
    )


def _table_mismatch_messages(
    connection: Connection,
    *,
    schema_name: str | None,
    table_name: str,
    table: Table,
) -> list[str]:
    messages: list[str] = []
    messages.extend(
        _column_mismatch_messages(
            connection,
            schema_name=schema_name,
            table_name=table_name,
            table=table,
        )
    )
    messages.extend(
        _primary_key_mismatch_messages(
            connection,
            schema_name=schema_name,
            table_name=table_name,
            table=table,
        )
    )
    messages.extend(
        _unique_mismatch_messages(
            connection,
            schema_name=schema_name,
            table_name=table_name,
            table=table,
        )
    )
    messages.extend(
        _foreign_key_mismatch_messages(
            connection,
            schema_name=schema_name,
            table_name=table_name,
            table=table,
        )
    )
    messages.extend(
        _check_mismatch_messages(
            connection,
            schema_name=schema_name,
            table_name=table_name,
            table=table,
        )
    )
    messages.extend(
        _index_mismatch_messages(
            connection,
            schema_name=schema_name,
            table_name=table_name,
            table=table,
        )
    )
    return messages


def _column_mismatch_messages(
    connection: Connection,
    *,
    schema_name: str | None,
    table_name: str,
    table: Table,
) -> list[str]:
    expected_columns = _metadata_column_signatures(connection, table)
    actual_columns = _column_signatures(connection, schema_name, table_name)
    messages = [
        *(
            f"{table_name} missing column {column_name}"
            for column_name in sorted(expected_columns.keys() - actual_columns.keys())
        ),
        *(
            f"{table_name} unexpected column {column_name}"
            for column_name in sorted(actual_columns.keys() - expected_columns.keys())
        ),
    ]
    for column_name in sorted(expected_columns.keys() & actual_columns.keys()):
        if expected_columns[column_name] != actual_columns[column_name]:
            messages.append(
                f"{table_name} changed column {column_name}: expected "
                f"{expected_columns[column_name]}, found {actual_columns[column_name]}"
            )
    return messages


def _primary_key_mismatch_messages(
    connection: Connection,
    *,
    schema_name: str | None,
    table_name: str,
    table: Table,
) -> list[str]:
    expected_primary_key = _metadata_primary_key_signature(table)
    actual_primary_key = _primary_key_signature(connection, schema_name, table_name)
    if expected_primary_key == actual_primary_key:
        return []
    return [
        f"{table_name} changed primary key: expected {expected_primary_key}, "
        f"found {actual_primary_key}"
    ]


def _unique_mismatch_messages(
    connection: Connection,
    *,
    schema_name: str | None,
    table_name: str,
    table: Table,
) -> list[str]:
    expected_uniques = _metadata_unique_signatures(table)
    actual_uniques = _unique_signatures(connection, schema_name, table_name)
    return [
        *(
            f"{table_name} missing unique constraint {signature}"
            for signature in sorted(expected_uniques - actual_uniques)
        ),
        *(
            f"{table_name} unexpected unique constraint {signature}"
            for signature in sorted(actual_uniques - expected_uniques)
        ),
    ]


def _foreign_key_mismatch_messages(
    connection: Connection,
    *,
    schema_name: str | None,
    table_name: str,
    table: Table,
) -> list[str]:
    expected_foreign_keys = _metadata_foreign_key_signatures(table)
    actual_foreign_keys = _foreign_key_signatures(connection, schema_name, table_name)
    return [
        *(
            f"{table_name} missing foreign key {signature}"
            for signature in sorted(expected_foreign_keys - actual_foreign_keys)
        ),
        *(
            f"{table_name} unexpected foreign key {signature}"
            for signature in sorted(actual_foreign_keys - expected_foreign_keys)
        ),
    ]


def _check_mismatch_messages(
    connection: Connection,
    *,
    schema_name: str | None,
    table_name: str,
    table: Table,
) -> list[str]:
    expected_checks = _metadata_check_constraints(connection, table)
    actual_checks = _check_constraints(connection, schema_name, table_name)
    return [
        *(
            f"{table_name} missing or changed check constraint {signature[0]}"
            for signature in sorted(expected_checks - actual_checks)
        ),
        *(
            f"{table_name} unexpected or changed check constraint {signature[0]}"
            for signature in sorted(actual_checks - expected_checks)
        ),
    ]


def _index_mismatch_messages(
    connection: Connection,
    *,
    schema_name: str | None,
    table_name: str,
    table: Table,
) -> list[str]:
    expected_indexes = _metadata_indexes(connection, table)
    actual_indexes = _indexes(connection, schema_name, table_name)
    return [
        *(
            f"{table_name} missing or changed index {signature[0]}"
            for signature in sorted(expected_indexes - actual_indexes)
        ),
        *(
            f"{table_name} unexpected or changed index {signature[0]}"
            for signature in sorted(actual_indexes - expected_indexes)
        ),
    ]


def _column_signatures(
    connection: Connection,
    schema_name: str | None,
    table_name: str,
) -> dict[str, SchemaColumnSignature]:
    return {
        str(column["name"]): (
            _type_signature(connection, column["type"]),
            bool(column["nullable"]),
            _normalize_default(column.get("default")),
            reflected_computed_signature(column.get("computed")),
        )
        for column in inspect(connection).get_columns(table_name, schema=schema_name)
        if column.get("name") is not None and column.get("type") is not None
    }


def _metadata_column_signatures(
    connection: Connection,
    table: Table,
) -> dict[str, SchemaColumnSignature]:
    return {
        str(column.name): (
            _type_signature(connection, column.type),
            bool(column.nullable),
            _metadata_default(connection, column),
            metadata_computed_signature(connection, column),
        )
        for column in table.columns
    }


def _type_signature(connection: Connection, column_type: TypeEngine[Any]) -> str:
    compiled = str(column_type.compile(dialect=connection.dialect))
    return re.sub(r"\s+", " ", compiled.strip()).upper()


def _metadata_default(connection: Connection, column: Column[object]) -> str | None:
    server_default = column.server_default
    if server_default is None:
        return None
    if isinstance(server_default, Computed):
        return None
    if not isinstance(server_default, DefaultClause):
        return _normalize_default(str(server_default))
    argument = server_default.arg
    if isinstance(argument, str):
        return _normalize_default(argument)
    return _normalize_default(
        str(
            argument.compile(
                dialect=connection.dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
    )


def _normalize_default(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_schema_sql(str(value))
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == "'":
        normalized = normalized[1:-1].replace("''", "'")
    return normalized


def _metadata_tables() -> dict[str, Table]:
    from autoclaw.persistence import RuntimeBase

    return {str(name): table for name, table in RuntimeBase.metadata.tables.items()}


def _foreign_key_signatures(
    connection: Connection,
    schema_name: str | None,
    table_name: str,
) -> set[SchemaForeignKeySignature]:
    return {
        _reflected_foreign_key_signature(
            foreign_key,
            configured_schema=schema_name,
        )
        for foreign_key in inspect(connection).get_foreign_keys(
            table_name,
            schema=schema_name,
        )
    }


def _reflected_foreign_key_signature(
    foreign_key: Mapping[str, Any],
    *,
    configured_schema: str | None,
) -> SchemaForeignKeySignature:
    options = foreign_key.get("options") or {}
    referred_schema = foreign_key.get("referred_schema")
    normalized_schema = None if referred_schema == configured_schema else referred_schema
    return (
        tuple(str(column) for column in foreign_key.get("constrained_columns") or []),
        str(normalized_schema) if normalized_schema is not None else None,
        str(foreign_key.get("referred_table")),
        tuple(str(column) for column in foreign_key.get("referred_columns") or []),
        _normalize_reference_action(options.get("onupdate")),
        _normalize_reference_action(options.get("ondelete")),
        bool(options.get("deferrable", False)),
        _normalize_optional_keyword(options.get("initially")),
        _normalize_optional_keyword(options.get("match")),
    )


def _metadata_foreign_key_signatures(table: Table) -> set[SchemaForeignKeySignature]:
    signatures: set[SchemaForeignKeySignature] = set()
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        elements = tuple(constraint.elements)
        signatures.add(
            (
                tuple(str(element.parent.name) for element in elements),
                None,
                str(elements[0].column.table.name),
                tuple(str(element.column.name) for element in elements),
                _normalize_reference_action(constraint.onupdate),
                _normalize_reference_action(constraint.ondelete),
                bool(constraint.deferrable),
                _normalize_optional_keyword(constraint.initially),
                _normalize_optional_keyword(constraint.match),
            )
        )
    return signatures


def _normalize_reference_action(value: object | None) -> str | None:
    normalized = _normalize_optional_keyword(value)
    if normalized in {None, "NO ACTION"}:
        return None
    return normalized


def _normalize_optional_keyword(value: object | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def _primary_key_signature(
    connection: Connection,
    schema_name: str | None,
    table_name: str,
) -> tuple[str, ...]:
    reflected = inspect(connection).get_pk_constraint(
        table_name,
        schema=schema_name,
    )
    return tuple(str(column) for column in reflected.get("constrained_columns") or [])


def _metadata_primary_key_signature(table: Table) -> tuple[str, ...]:
    return tuple(str(column.name) for column in table.primary_key.columns)


def _unique_signatures(
    connection: Connection,
    schema_name: str | None,
    table_name: str,
) -> set[SchemaUniqueSignature]:
    return {
        tuple(str(column) for column in constraint.get("column_names") or [])
        for constraint in inspect(connection).get_unique_constraints(
            table_name,
            schema=schema_name,
        )
    }


def _metadata_unique_signatures(table: Table) -> set[SchemaUniqueSignature]:
    return {
        tuple(str(column.name) for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _check_constraints(
    connection: Connection,
    schema_name: str | None,
    table_name: str,
) -> set[tuple[str, str]]:
    constraints: set[tuple[str, str]] = set()
    for constraint in inspect(connection).get_check_constraints(
        table_name,
        schema=schema_name,
    ):
        sqltext = constraint.get("sqltext")
        if isinstance(sqltext, str):
            constraints.add(
                (
                    str(constraint.get("name") or ""),
                    normalize_schema_sql(sqltext),
                )
            )
    return constraints


def _metadata_check_constraints(
    connection: Connection,
    table: Table,
) -> set[tuple[str, str]]:
    constraints: set[tuple[str, str]] = set()
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint) or constraint.name is None:
            continue
        compiled = str(
            constraint.sqltext.compile(
                dialect=connection.dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        constraints.add((str(constraint.name), normalize_schema_sql(compiled)))
    return constraints


def _indexes(
    connection: Connection,
    schema_name: str | None,
    table_name: str,
) -> set[SchemaIndexSignature]:
    signatures: set[SchemaIndexSignature] = set()
    for index in inspect(connection).get_indexes(table_name, schema=schema_name):
        if index.get("duplicates_constraint"):
            continue
        name = index.get("name")
        if not isinstance(name, str):
            continue
        signatures.add(
            (
                name,
                bool(index.get("unique")),
                tuple(str(column) for column in index.get("column_names") or []),
                _reflected_index_predicate(index),
            )
        )
    return signatures


def _metadata_indexes(
    connection: Connection,
    table: Table,
) -> set[SchemaIndexSignature]:
    return {
        (
            str(index.name),
            bool(index.unique),
            tuple(str(column.name) for column in index.columns),
            _metadata_index_predicate(connection, index),
        )
        for index in table.indexes
        if index.name is not None
    }


def _metadata_index_predicate(connection: Connection, index: Index) -> str | None:
    dialect_name = connection.dialect.name
    if dialect_name == "sqlite":
        predicate = index.dialect_options["sqlite"].get("where")
    elif dialect_name == "postgresql":
        predicate = index.dialect_options["postgresql"].get("where")
    else:
        predicate = None
    if predicate is None:
        return None
    return normalize_schema_sql(str(predicate.compile(dialect=connection.dialect)))


def _reflected_index_predicate(index: Mapping[str, object]) -> str | None:
    dialect_options = index.get("dialect_options")
    if not isinstance(dialect_options, dict):
        return None
    predicate = dialect_options.get("sqlite_where")
    if predicate is None:
        predicate = dialect_options.get("postgresql_where")
    if predicate is None:
        return None
    return normalize_schema_sql(str(predicate))


__all__ = [
    "DatabaseSchemaMismatchError",
    "create_configured_schema",
    "list_schema_table_names",
    "normalize_schema_sql",
    "raise_schema_mismatch",
    "schema_mismatch_messages",
    "verify_schema_contract",
]
