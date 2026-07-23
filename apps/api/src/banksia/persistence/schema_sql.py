from __future__ import annotations

import re
from collections.abc import Mapping

from sqlalchemy.engine import Connection
from sqlalchemy.sql.schema import Column

ComputedSchemaSignature = tuple[str, bool | None]

_BOOLEAN_AND = "@and@"
_BOOLEAN_OR = "@or@"


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
    normalized = re.sub(
        r"\b([a-z_][a-z0-9_.]*)\s+between\s+(-?\d+)\s+and\s+(-?\d+)\b",
        r"(\1 >= \2 and \1 <= \3)",
        normalized,
    )
    normalized = re.sub(
        r"\btrim\s*\(\s*both\s+from\s+([a-z_][a-z0-9_.]*)\s*\)",
        r"trim(\1)",
        normalized,
    )
    normalized = _mark_boolean_operators(normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(
        r"::(?:charactervarying|varchar|text|smallint|integer|bigint|boolean|"
        r"jsonb?|timestamp(?:with|without)timezone|numeric|doubleprecision)(?:\(\d+(?:,\d+)?\))?(?:\[\])?",
        "",
        normalized,
    )
    normalized = normalized.replace("<>", "!=")
    normalized = _strip_scalar_parentheses(normalized)
    normalized = re.sub(
        r"([a-z_][a-z0-9_.]*)=any\(\(array\[([^\]]*)\]\)\)",
        r"\1in(\2)",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_.]*)=any\(array\[([^\]]*)\]\)",
        r"\1in(\2)",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_.]*)!=all\(\(array\[([^\]]*)\]\)\)",
        r"\1notin(\2)",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_.]*)!=all\(array\[([^\]]*)\]\)",
        r"\1notin(\2)",
        normalized,
    )
    normalized = _strip_scalar_parentheses(normalized)
    normalized = _strip_case_when_parentheses(normalized)
    normalized = _canonicalize_boolean_expression(normalized)
    return normalized.replace(_BOOLEAN_AND, "and").replace(_BOOLEAN_OR, "or")


def _strip_scalar_parentheses(value: str) -> str:
    value = re.sub(r"\(([a-z_][a-z0-9_.]*)\)", r"\1", value)
    return value


def _strip_case_when_parentheses(value: str) -> str:
    search_from = 0
    while True:
        open_index = value.find("casewhen(", search_from)
        if open_index < 0:
            return value
        open_index += len("casewhen")
        close_index = _matching_parenthesis(value, open_index)
        if close_index is not None and value.startswith("then", close_index + 1):
            value = (
                value[:open_index] + value[open_index + 1 : close_index] + value[close_index + 1 :]
            )
            search_from = open_index
            continue
        search_from = open_index + 1


def _matching_parenthesis(value: str, open_index: int) -> int | None:
    depth = 0
    index = open_index
    while index < len(value):
        character = value[index]
        if character == "'":
            index = _skip_quoted_value(value, index)
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _mark_boolean_operators(value: str) -> str:
    marked: list[str] = []
    index = 0
    is_quoted = False
    while index < len(value):
        character = value[index]
        if character == "'":
            marked.append(character)
            if is_quoted and index + 1 < len(value) and value[index + 1] == "'":
                marked.append("'")
                index += 2
                continue
            is_quoted = not is_quoted
            index += 1
            continue
        if not is_quoted:
            operator = _boolean_operator_at(value, index)
            if operator is not None:
                marked.append(operator)
                index += 3 if operator == _BOOLEAN_AND else 2
                continue
        marked.append(character)
        index += 1
    return "".join(marked)


def _boolean_operator_at(value: str, index: int) -> str | None:
    for keyword, marker in (("and", _BOOLEAN_AND), ("or", _BOOLEAN_OR)):
        end = index + len(keyword)
        if value[index:end] != keyword:
            continue
        previous = value[index - 1] if index > 0 else ""
        following = value[end] if end < len(value) else ""
        if not _is_identifier_character(previous) and not _is_identifier_character(following):
            return marker
    return None


def _is_identifier_character(character: str) -> bool:
    return character.isalnum() or character in {"_", "."}


def _canonicalize_boolean_expression(value: str, *, parent_precedence: int = 0) -> str:
    normalized = _strip_balanced_outer_parentheses(value)
    alternatives = _split_top_level(normalized, _BOOLEAN_OR)
    if len(alternatives) > 1:
        canonical = _BOOLEAN_OR.join(
            _canonicalize_boolean_expression(part, parent_precedence=1) for part in alternatives
        )
        return f"({canonical})" if parent_precedence > 1 else canonical

    conjuncts = _split_top_level(normalized, _BOOLEAN_AND)
    if len(conjuncts) > 1:
        canonical = _BOOLEAN_AND.join(
            _canonicalize_boolean_expression(part, parent_precedence=2) for part in conjuncts
        )
        return f"({canonical})" if parent_precedence > 2 else canonical
    return normalized


def _split_top_level(value: str, marker: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            index = _skip_quoted_value(value, index)
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif depth == 0 and value.startswith(marker, index):
            parts.append(value[start:index])
            index += len(marker)
            start = index
            continue
        index += 1
    parts.append(value[start:])
    return tuple(parts)


def _skip_quoted_value(value: str, index: int) -> int:
    index += 1
    while index < len(value):
        if value[index] != "'":
            index += 1
            continue
        if index + 1 < len(value) and value[index + 1] == "'":
            index += 2
            continue
        return index + 1
    return index


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
