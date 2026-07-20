from __future__ import annotations

from copy import deepcopy
from typing import Any

from autoclaw.interfaces.mcp.mcp_operation_failures import (
    success_or_failure_output_schema,
)
from autoclaw.runtime.node_operations import NodeOperationDescriptor

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


def managed_input_schema(descriptor: NodeOperationDescriptor) -> dict[str, Any]:
    return _strict_object_schema(descriptor.request_model.model_json_schema())


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
