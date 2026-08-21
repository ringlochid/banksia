from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Literal, cast

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

from oh_my_subagents.workflows.contracts import NormalizedMember, NormalizedWorkflow
from oh_my_subagents.workflows.errors import (
    WorkflowInputError,
    WorkflowValidationIssue,
    workflow_input_error,
)
from oh_my_subagents.workflows.provider_retirement import require_active_providers

MAX_RAW_BYTES = 1024 * 1024
MAX_COLLECTION_DEPTH = 32
MAX_COLLECTION_NODES = 4096
MAX_MEMBERS = 256
MAX_MEMBER_DEPTH = 12

_YAML_ALLOWED_SCALAR_TAGS = {
    "tag:yaml.org,2002:null",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:str",
}
_OPTIONAL_MEMBER_PROSE = ("title", "description", "instruction")


class _JsonObjectPairs(list[tuple[str, object]]):
    pass


def parse_workflow(
    raw: bytes | str,
    *,
    source_format: Literal["json", "yaml"],
) -> NormalizedWorkflow:
    text = _decode_bounded_input(raw)
    if source_format == "json":
        payload = _parse_json(text)
    else:
        payload = _parse_yaml(text)
    return normalize_workflow_object(payload)


def normalize_workflow_object(payload: object) -> NormalizedWorkflow:
    _validate_json_shape(payload)
    return _normalize_validated_workflow_object(payload)


def normalize_bounded_workflow_object(payload: object) -> NormalizedWorkflow:
    """Normalize a structured Workflow after enforcing the authored-input byte bound."""

    _validate_json_shape(payload)
    _validate_serialized_input_size(payload)
    return _normalize_validated_workflow_object(payload)


def normalize_optional_member_prose(value: str | None) -> str | None:
    """Apply the shared Workflow Member text guardrails to one optional value."""

    if value is None:
        return None
    _validate_text(value, path="$")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized if normalized.strip() else None


def _normalize_validated_workflow_object(payload: object) -> NormalizedWorkflow:
    if not isinstance(payload, Mapping):
        raise workflow_input_error(
            source="schema.root",
            path="$",
            message="Workflow input must be one object",
        )
    normalized_payload = _normalize_workflow_mapping(dict(payload))
    try:
        workflow = NormalizedWorkflow.model_validate(normalized_payload)
    except ValidationError as exc:
        raise WorkflowInputError(*_pydantic_issues(exc)) from exc
    _validate_workflow_semantics(workflow)
    require_active_providers(workflow)
    return workflow


def _decode_bounded_input(raw: bytes | str) -> str:
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    except UnicodeEncodeError as exc:
        raise workflow_input_error(
            source="input.encoding",
            path="$",
            message="Workflow input must be valid UTF-8",
        ) from exc
    if len(encoded) > MAX_RAW_BYTES:
        raise workflow_input_error(
            source="input.size",
            path="$",
            message=f"Workflow input exceeds {MAX_RAW_BYTES} bytes",
        )
    try:
        return encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise workflow_input_error(
            source="input.encoding",
            path="$",
            message="Workflow input must be valid UTF-8",
        ) from exc


def _validate_serialized_input_size(payload: object) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_RAW_BYTES:
        raise workflow_input_error(
            source="input.size",
            path="$",
            message=f"Workflow input exceeds {MAX_RAW_BYTES} bytes",
        )


def _parse_json(text: str) -> object:
    def reject_constant(value: str) -> object:
        raise workflow_input_error(
            source="parser.non_finite",
            path="$",
            message=f"non-finite JSON number {value!r} is not allowed",
        )

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_JsonObjectPairs,
            parse_constant=reject_constant,
        )
        return _convert_json_pairs(parsed, path="$")
    except WorkflowInputError:
        raise
    except RecursionError as exc:
        raise workflow_input_error(
            source="input.depth",
            path="$",
            message=f"collection depth exceeds {MAX_COLLECTION_DEPTH}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise workflow_input_error(
            source="parser.syntax",
            path="$",
            message=f"invalid JSON at line {exc.lineno}, column {exc.colno}",
        ) from exc


def _parse_yaml(text: str) -> object:
    try:
        for token in yaml.scan(text):
            if isinstance(token, AnchorToken):
                raise workflow_input_error(
                    source="parser.yaml_anchor",
                    path="$",
                    message="YAML anchors are not allowed",
                )
            if isinstance(token, AliasToken):
                raise workflow_input_error(
                    source="parser.yaml_alias",
                    path="$",
                    message="YAML aliases are not allowed",
                )
            if isinstance(token, TagToken) and not _is_allowed_explicit_yaml_tag(token):
                raise workflow_input_error(
                    source="parser.yaml_tag",
                    path="$",
                    message="explicit YAML tags are not allowed",
                )
        documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except WorkflowInputError:
        raise
    except RecursionError as exc:
        raise workflow_input_error(
            source="input.depth",
            path="$",
            message=f"collection depth exceeds {MAX_COLLECTION_DEPTH}",
        ) from exc
    except yaml.YAMLError as exc:
        raise workflow_input_error(
            source="parser.syntax",
            path="$",
            message="invalid YAML input",
        ) from exc
    if len(documents) != 1 or documents[0] is None:
        raise workflow_input_error(
            source="parser.document_count",
            path="$",
            message="YAML input must contain exactly one non-empty document",
        )
    _validate_yaml_node(documents[0], path="$")
    try:
        return yaml.safe_load(text)
    except RecursionError as exc:
        raise workflow_input_error(
            source="input.depth",
            path="$",
            message=f"collection depth exceeds {MAX_COLLECTION_DEPTH}",
        ) from exc
    except yaml.YAMLError as exc:  # pragma: no cover - compose already parsed it
        raise workflow_input_error(
            source="parser.syntax",
            path="$",
            message="invalid YAML input",
        ) from exc


def _validate_yaml_node(node: Node, *, path: str) -> None:
    if isinstance(node, MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode) and key_node.value == "<<":
                raise workflow_input_error(
                    source="parser.yaml_merge",
                    path=_child_path(path, "<<"),
                    message="YAML merge keys are not allowed",
                )
            if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                raise workflow_input_error(
                    source="parser.yaml_key",
                    path=path,
                    message="YAML object keys must be strings",
                )
            key = key_node.value
            if key in seen:
                raise workflow_input_error(
                    source="parser.duplicate_key",
                    path=_child_path(path, key),
                    message=f"duplicate object key {key!r}",
                )
            seen.add(key)
            _validate_yaml_node(value_node, path=_child_path(path, key))
        return
    if isinstance(node, SequenceNode):
        for index, child in enumerate(node.value):
            _validate_yaml_node(child, path=f"{path}[{index}]")
        return
    if not isinstance(node, ScalarNode) or node.tag not in _YAML_ALLOWED_SCALAR_TAGS:
        raise workflow_input_error(
            source="parser.yaml_scalar",
            path=path,
            message="YAML value is not a JSON-compatible scalar",
        )
    if node.tag == "tag:yaml.org,2002:bool" and node.value.casefold() not in {"true", "false"}:
        raise workflow_input_error(
            source="parser.yaml_scalar",
            path=path,
            message="YAML boolean must use true or false",
        )


def _validate_json_shape(payload: object) -> None:
    collection_nodes = 0

    def visit(value: object, *, path: str, depth: int) -> None:
        nonlocal collection_nodes
        if isinstance(value, Mapping):
            collection_nodes += 1
            if depth > MAX_COLLECTION_DEPTH:
                raise workflow_input_error(
                    source="input.depth",
                    path=path,
                    message=f"collection depth exceeds {MAX_COLLECTION_DEPTH}",
                )
            for key, child in value.items():
                if not isinstance(key, str):
                    raise workflow_input_error(
                        source="input.key",
                        path=path,
                        message="object keys must be strings",
                    )
                _validate_text(key, path=_child_path(path, key))
                visit(child, path=_child_path(path, key), depth=depth + 1)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            collection_nodes += 1
            if depth > MAX_COLLECTION_DEPTH:
                raise workflow_input_error(
                    source="input.depth",
                    path=path,
                    message=f"collection depth exceeds {MAX_COLLECTION_DEPTH}",
                )
            for index, child in enumerate(value):
                visit(child, path=f"{path}[{index}]", depth=depth + 1)
        elif isinstance(value, float) and not math.isfinite(value):
            raise workflow_input_error(
                source="input.non_finite",
                path=path,
                message="numbers must be finite",
            )
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise workflow_input_error(
                source="input.value",
                path=path,
                message="value is not JSON-compatible",
            )
        elif isinstance(value, str):
            _validate_text(value, path=path)
        if collection_nodes > MAX_COLLECTION_NODES:
            raise workflow_input_error(
                source="input.nodes",
                path=path,
                message=f"collection node count exceeds {MAX_COLLECTION_NODES}",
            )

    visit(payload, path="$", depth=1)


def _convert_json_pairs(value: object, *, path: str) -> object:
    if isinstance(value, _JsonObjectPairs):
        result: dict[str, object] = {}
        for key, child in value:
            child_path = _child_path(path, key)
            if key in result:
                raise workflow_input_error(
                    source="parser.duplicate_key",
                    path=child_path,
                    message=f"duplicate object key {key!r}",
                )
            result[key] = _convert_json_pairs(child, path=child_path)
        return result
    if isinstance(value, list):
        return [
            _convert_json_pairs(child, path=f"{path}[{index}]") for index, child in enumerate(value)
        ]
    return value


def _is_allowed_explicit_yaml_tag(token: TagToken) -> bool:
    handle, suffix = token.value
    return handle == "!!" and suffix in {"null", "bool", "int", "float", "str", "map", "seq"}


def _normalize_workflow_mapping(payload: dict[str, object]) -> dict[str, object]:
    normalized = cast(dict[str, object], _normalize_value(payload, path="$"))
    _omit_blank_optional(normalized, "note")
    lead = normalized.get("lead")
    if isinstance(lead, dict):
        _normalize_member_mapping(lead)
    return normalized


def _normalize_member_mapping(member: dict[str, object]) -> None:
    for field_name in _OPTIONAL_MEMBER_PROSE:
        _omit_blank_optional(member, field_name)
    children = member.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _normalize_member_mapping(child)


def _normalize_value(value: object, *, path: str) -> object:
    if isinstance(value, dict):
        return {
            key: _normalize_value(child, path=_child_path(path, key))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _normalize_value(child, path=f"{path}[{index}]") for index, child in enumerate(value)
        ]
    if isinstance(value, str):
        _validate_text(value, path=path)
        return value.replace("\r\n", "\n").replace("\r", "\n")
    return value


def _omit_blank_optional(payload: dict[str, object], key: str) -> None:
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        payload.pop(key, None)


def _validate_text(value: str, *, path: str) -> None:
    for character in value:
        codepoint = ord(character)
        is_xml_character = (
            codepoint in {0x9, 0xA, 0xD}
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        )
        if not is_xml_character:
            raise workflow_input_error(
                source="input.character",
                path=path,
                message=f"illegal text character U+{codepoint:04X}",
            )


def _pydantic_issues(exc: ValidationError) -> tuple[WorkflowValidationIssue, ...]:
    issues: list[WorkflowValidationIssue] = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        if error.get("type") == "none_required":
            continue
        message = str(error.get("msg", "invalid Workflow value"))
        location = tuple(
            part for part in error.get("loc", ()) if not _is_pydantic_branch_location(part)
        )
        null_field = _explicit_null_field(message)
        if null_field is not None and (not location or location[-1] != null_field):
            location = (*location, null_field)
        path = "$"
        for part in location:
            path = f"{path}[{part}]" if isinstance(part, int) else _child_path(path, str(part))
        issues.append(
            WorkflowValidationIssue(
                source=f"schema.{error.get('type', 'validation')}",
                path=path,
                message=message,
            )
        )
    if issues:
        return tuple(issues)
    return (
        WorkflowValidationIssue(
            source="schema.validation",
            path="$",
            message="Workflow value does not match the authored schema",
        ),
    )


def _is_pydantic_branch_location(part: object) -> bool:
    if not isinstance(part, str):
        return False
    return part in {"codex", "claude", "openclaw", "none"} or ("[" in part and part.endswith("]"))


def _explicit_null_field(message: str) -> str | None:
    prefix = "Value error, "
    suffix = " cannot be null"
    if not message.startswith(prefix) or not message.endswith(suffix):
        return None
    field_name = message[len(prefix) : -len(suffix)]
    return field_name if field_name.isidentifier() else None


def _validate_workflow_semantics(workflow: NormalizedWorkflow) -> None:
    seen_ids: set[str] = set()
    member_count = 0

    def visit(member: NormalizedMember, *, path: str, depth: int) -> None:
        nonlocal member_count
        member_count += 1
        if member_count > MAX_MEMBERS:
            raise workflow_input_error(
                source="semantic.member_count",
                path=path,
                message=f"Workflow exceeds {MAX_MEMBERS} Members",
            )
        if depth > MAX_MEMBER_DEPTH:
            raise workflow_input_error(
                source="semantic.member_depth",
                path=path,
                message=f"Member tree depth exceeds {MAX_MEMBER_DEPTH}",
            )
        if member.id in seen_ids:
            raise workflow_input_error(
                source="semantic.member_id",
                path=f"{path}.id",
                message=f"Member ID {member.id!r} is duplicated",
            )
        seen_ids.add(member.id)
        if member.capabilities is not None:
            requests = member.capabilities.human_request
            if requests is not None and len(set(requests)) != len(requests):
                raise workflow_input_error(
                    source="semantic.capabilities",
                    path=f"{path}.capabilities.human_request",
                    message="Human Request capability kinds must be unique",
                )
        for index, child in enumerate(member.children or ()):
            visit(child, path=f"{path}.children[{index}]", depth=depth + 1)

    visit(workflow.lead, path="$.lead", depth=1)


def _child_path(parent: str, key: str) -> str:
    if key.isidentifier():
        return f"{parent}.{key}"
    return f"{parent}[{json.dumps(key, ensure_ascii=False)}]"


__all__ = [
    "MAX_COLLECTION_DEPTH",
    "MAX_COLLECTION_NODES",
    "MAX_MEMBERS",
    "MAX_MEMBER_DEPTH",
    "MAX_RAW_BYTES",
    "normalize_bounded_workflow_object",
    "normalize_optional_member_prose",
    "normalize_workflow_object",
    "parse_workflow",
]
