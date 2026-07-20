from __future__ import annotations

import re
from collections.abc import Mapping

from sqlalchemy.engine import Connection
from sqlalchemy.sql.schema import Column

ComputedSchemaSignature = tuple[str, bool | None]


def reflected_computed_signature(value: object | None) -> ComputedSchemaSignature | None:
    """Normalize a reflected generated-column contract."""

    if not isinstance(value, Mapping):
        return None
    sqltext = value.get("sqltext")
    if not isinstance(sqltext, str):
        return None
    persisted = value.get("persisted")
    return normalize_schema_sql(sqltext), bool(persisted) if persisted is not None else None


def metadata_computed_signature(
    connection: Connection,
    column: Column[object],
) -> ComputedSchemaSignature | None:
    """Normalize a metadata generated-column contract for one dialect."""

    computed = column.computed
    if computed is None:
        return None
    compiled = str(
        computed.sqltext.compile(
            dialect=connection.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    return normalize_schema_sql(compiled), computed.persisted


def normalize_schema_sql(value: str) -> str:
    """Normalize reflected and metadata SQL for cross-dialect comparison."""

    normalized = value.lower().replace('"', "").replace("`", "")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(
        r"::(?:charactervarying|varchar|text|smallint|integer|bigint|boolean|"
        r"jsonb?|timestamp(?:with|without)timezone|numeric|doubleprecision)(?:\(\d+(?:,\d+)?\))?(?:\[\])?",
        "",
        normalized,
    )
    normalized = normalized.replace("<>", "!=")
    normalized = re.sub(
        r"\(*([a-z_][a-z0-9_.]*)\)*=any\(*array\[([^\]]*)\]\)*",
        r"\1in(\2)",
        normalized,
    )
    normalized = re.sub(
        r"\(*([a-z_][a-z0-9_.]*)\)*!=all\(*array\[([^\]]*)\]\)*",
        r"\1notin(\2)",
        normalized,
    )
    previous = ""
    while previous != normalized:
        previous = normalized
        normalized = re.sub(r"\(([a-z_][a-z0-9_.]*)\)", r"\1", normalized)
        normalized = re.sub(r"\(array\[([^\]]*)\]\)", r"array[\1]", normalized)
    return _strip_balanced_outer_parentheses(normalized)


def _strip_balanced_outer_parentheses(value: str) -> str:
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        wraps_entire_value = True
        for index, character in enumerate(value):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    wraps_entire_value = False
                    break
        if not wraps_entire_value or depth != 0:
            break
        value = value[1:-1]
    return value


__all__ = [
    "ComputedSchemaSignature",
    "metadata_computed_signature",
    "normalize_schema_sql",
    "reflected_computed_signature",
]
