from __future__ import annotations

from copy import deepcopy
from typing import Any

from banksia.interfaces.mcp.mcp_operation_failures import (
    success_or_failure_output_schema,
)
from banksia.runtime.node_operations import NodeOperationDescriptor

_SCOPE_PROPERTIES: dict[str, dict[str, object]] = {
    "task_id": {
        "type": "string",
        "minLength": 1,
        "description": "Full controller task ID.",
    },
    "dispatch_id": {
        "type": "string",
        "minLength": 1,
        "description": "Full controller dispatch ID.",
    },
}
_ALL_HUMAN_REQUEST_KINDS = ("input", "direction", "approval", "review")


def compatibility_input_schema(descriptor: NodeOperationDescriptor) -> dict[str, Any]:
    semantic_schema = managed_input_schema(descriptor)
    semantic_properties = semantic_schema.get("properties", {})
    semantic_required = semantic_schema.get("required", [])
    if not isinstance(semantic_properties, dict) or not isinstance(semantic_required, list):
        raise ValueError(f"Node operation '{descriptor.name}' has an invalid semantic schema")

    compatibility_schema = deepcopy(semantic_schema)
    compatibility_schema["title"] = f"Compatibility{descriptor.request_model.__name__}"
    compatibility_schema["properties"] = {
        **deepcopy(_SCOPE_PROPERTIES),
        **semantic_properties,
    }
    compatibility_schema["required"] = [
        "task_id",
        "dispatch_id",
        *semantic_required,
    ]
    compatibility_schema["additionalProperties"] = False
    return compatibility_schema


def managed_input_schema(
    descriptor: NodeOperationDescriptor,
    *,
    human_request_kinds: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    schema = _strict_object_schema(descriptor.request_model.model_json_schema())
    if (
        descriptor.name.value == "open_human_request"
        and human_request_kinds is not None
        and human_request_kinds != _ALL_HUMAN_REQUEST_KINDS
    ):
        definitions = schema.get("$defs")
        if not isinstance(definitions, dict):
            raise ValueError("Human Request schema is missing definitions")
        request_schema = definitions.get("HumanRequestOpenRequest")
        if not isinstance(request_schema, dict):
            raise ValueError("Human Request schema is missing its request definition")
        properties = request_schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("Human Request schema is missing request properties")
        kind_schema = properties.get("kind")
        if not isinstance(kind_schema, dict):
            raise ValueError("Human Request schema is missing its kind property")
        kind_schema.pop("$ref", None)
        kind_schema["type"] = "string"
        kind_schema["enum"] = list(human_request_kinds)
    return schema


def operation_output_schema(descriptor: NodeOperationDescriptor) -> dict[str, Any]:
    success_schema = _strict_object_schema(descriptor.success_model.model_json_schema())
    return success_or_failure_output_schema(success_schema)


def _strict_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized_schema = deepcopy(schema)
    if normalized_schema.get("type") != "object":
        raise ValueError("Node operation schemas must describe JSON objects")
    if normalized_schema.get("additionalProperties") is not False:
        raise ValueError("Node operation schemas must forbid additional properties")
    return normalized_schema


__all__ = [
    "compatibility_input_schema",
    "managed_input_schema",
    "operation_output_schema",
]
