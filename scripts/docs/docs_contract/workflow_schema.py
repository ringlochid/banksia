from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .models import ContractFinding

type SchemaPathPart = str | int
type SchemaPath = tuple[SchemaPathPart, ...]

INVALID_PERCENT_ESCAPE_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")
INVALID_JSON_POINTER_ESCAPE_PATTERN = re.compile(r"~(?:[^01]|$)")
ARRAY_INDEX_PATTERN = re.compile(r"0|[1-9][0-9]*")
REFERENCE_KEYWORDS = frozenset({"$ref", "$dynamicRef"})


def workflow_schema_reference_findings(
    *,
    root: Path,
    path: Path,
    schema: Mapping[str, Any],
) -> list[ContractFinding]:
    """Validate the maintained schema's deterministic local-reference graph."""

    findings: list[ContractFinding] = []
    resolved_references: dict[SchemaPath, SchemaPath] = {}
    for reference_path, keyword, reference in iter_schema_references(schema):
        if keyword == "$dynamicRef":
            findings.append(
                schema_reference_finding(
                    root=root,
                    path=path,
                    message=(
                        f"{format_schema_path(reference_path)} uses unsupported $dynamicRef; "
                        "the maintained Workflow schema permits local $ref JSON Pointers only"
                    ),
                )
            )
            continue
        target_path, error = resolve_local_reference(schema=schema, reference=reference)
        if error is not None:
            findings.append(
                schema_reference_finding(
                    root=root,
                    path=path,
                    message=f"{format_schema_path(reference_path)} {error}",
                )
            )
            continue
        assert target_path is not None
        target = value_at_schema_path(schema, target_path)
        if not isinstance(target, (Mapping, bool)):
            findings.append(
                schema_reference_finding(
                    root=root,
                    path=path,
                    message=(
                        f"{format_schema_path(reference_path)} resolves to "
                        f"{format_schema_path(target_path)}, which is not a schema object "
                        "or boolean"
                    ),
                )
            )
            continue
        resolved_references[reference_path] = target_path

    findings.extend(nested_schema_identifier_findings(root=root, path=path, schema=schema))
    findings.extend(
        unused_definition_findings(
            root=root,
            path=path,
            schema=schema,
            resolved_references=resolved_references,
        )
    )
    return findings


def iter_schema_references(
    schema: Mapping[str, Any],
) -> Iterator[tuple[SchemaPath, str, object]]:
    for value, value_path in iter_json_values(schema):
        if not isinstance(value, Mapping):
            continue
        for keyword in sorted(REFERENCE_KEYWORDS & value.keys()):
            yield (*value_path, keyword), keyword, value[keyword]


def iter_json_values(
    value: object, *, path: SchemaPath = ()
) -> Iterator[tuple[object, SchemaPath]]:
    yield value, path
    if isinstance(value, Mapping):
        for key in sorted(value):
            yield from iter_json_values(value[key], path=(*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_json_values(child, path=(*path, index))


def resolve_local_reference(
    *,
    schema: Mapping[str, Any],
    reference: object,
) -> tuple[SchemaPath | None, str | None]:
    if not isinstance(reference, str):
        return None, f"must be a string, got {type(reference).__name__}"
    if not reference.startswith("#"):
        return (
            None,
            f"uses non-local reference {reference!r}; remote and relative refs are forbidden",
        )

    fragment = reference[1:]
    if INVALID_PERCENT_ESCAPE_PATTERN.search(fragment):
        return None, f"contains an invalid percent escape in reference {reference!r}"
    try:
        pointer = unquote(fragment, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, f"contains non-UTF-8 percent encoding in reference {reference!r}"
    if not pointer:
        return (), None
    if not pointer.startswith("/"):
        return None, f"uses unsupported plain-name fragment {reference!r}; use a JSON Pointer"

    target: object = schema
    target_path: list[SchemaPathPart] = []
    for encoded_token in pointer[1:].split("/"):
        if INVALID_JSON_POINTER_ESCAPE_PATTERN.search(encoded_token):
            return None, f"contains an invalid JSON Pointer escape in reference {reference!r}"
        token = encoded_token.replace("~1", "/").replace("~0", "~")
        if isinstance(target, Mapping):
            if token not in target:
                return None, f"points to missing JSON Pointer {reference!r}"
            target = target[token]
            target_path.append(token)
            continue
        if isinstance(target, Sequence) and not isinstance(target, (str, bytes, bytearray)):
            if not ARRAY_INDEX_PATTERN.fullmatch(token):
                return None, f"contains invalid array index {token!r} in reference {reference!r}"
            index = int(token)
            if index >= len(target):
                return None, f"points to missing JSON Pointer {reference!r}"
            target = target[index]
            target_path.append(index)
            continue
        return None, f"traverses through a scalar in reference {reference!r}"
    return tuple(target_path), None


def nested_schema_identifier_findings(
    *,
    root: Path,
    path: Path,
    schema: Mapping[str, Any],
) -> list[ContractFinding]:
    return [
        schema_reference_finding(
            root=root,
            path=path,
            message=(
                f"{format_schema_path((*value_path, '$id'))} creates a nested schema resource; "
                "the maintained Workflow schema supports one root resource only"
            ),
        )
        for value, value_path in iter_json_values(schema)
        if value_path and isinstance(value, Mapping) and "$id" in value
    ]


def unused_definition_findings(
    *,
    root: Path,
    path: Path,
    schema: Mapping[str, Any],
    resolved_references: Mapping[SchemaPath, SchemaPath],
) -> list[ContractFinding]:
    definitions = schema.get("$defs")
    if not isinstance(definitions, Mapping):
        return []

    reachable_paths = collect_reachable_schema_paths(
        schema=schema,
        resolved_references=resolved_references,
    )
    used_definition_names = {
        schema_path[1]
        for schema_path in reachable_paths
        if len(schema_path) >= 2 and schema_path[0] == "$defs" and isinstance(schema_path[1], str)
    }
    return [
        schema_reference_finding(
            root=root,
            path=path,
            message=f"top-level $defs entry {name!r} is unreachable from the root schema",
        )
        for name in sorted(definitions)
        if name not in used_definition_names
    ]


def collect_reachable_schema_paths(
    *,
    schema: Mapping[str, Any],
    resolved_references: Mapping[SchemaPath, SchemaPath],
) -> set[SchemaPath]:
    reachable: set[SchemaPath] = set()
    pending: list[SchemaPath] = [()]
    while pending:
        current_path = pending.pop()
        if current_path in reachable:
            continue
        reachable.add(current_path)
        current = value_at_schema_path(schema, current_path)
        if isinstance(current, Mapping):
            reference_path = (*current_path, "$ref")
            if reference_path in resolved_references:
                pending.append(resolved_references[reference_path])
            pending.extend(
                (*current_path, key)
                for key in sorted(current, reverse=True)
                if key not in {"$defs", "$ref", "$dynamicRef"}
                and isinstance(current[key], (Mapping, list))
            )
        elif isinstance(current, list):
            pending.extend(
                (*current_path, index)
                for index in reversed(range(len(current)))
                if isinstance(current[index], (Mapping, list))
            )
    return reachable


def value_at_schema_path(schema: object, path: SchemaPath) -> object:
    value = schema
    for part in path:
        value = value[part]  # type: ignore[index]
    return value


def format_schema_path(path: SchemaPath) -> str:
    rendered = "$"
    for part in path:
        if isinstance(part, int):
            rendered += f"[{part}]"
        elif part.isidentifier():
            rendered += f".{part}"
        else:
            rendered += f"[{part!r}]"
    return rendered


def schema_reference_finding(*, root: Path, path: Path, message: str) -> ContractFinding:
    return ContractFinding(
        category="workflow-fixture",
        path=path.relative_to(root),
        line=1,
        message=f"Workflow schema reference error: {message}",
    )


__all__ = ["workflow_schema_reference_findings"]
