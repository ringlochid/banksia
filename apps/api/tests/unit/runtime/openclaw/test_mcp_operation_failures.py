from __future__ import annotations

from autoclaw.interfaces.mcp.mcp_operation_failures import success_or_failure_output_schema


def test_success_or_failure_output_schema_keeps_root_object_for_mcp_catalogs() -> None:
    schema = success_or_failure_output_schema(
        {
            "title": "CheckpointRead",
            "type": "object",
            "properties": {
                "checkpoint_id": {"type": "string"},
            },
            "required": ["checkpoint_id"],
        }
    )

    assert schema["type"] == "object"
    assert schema["title"] == "CheckpointRead"
    assert len(schema["oneOf"]) == 2
    success_variant, failure_variant = schema["oneOf"]
    assert success_variant["type"] == "object"
    assert success_variant["required"] == ["checkpoint_id"]
    assert failure_variant["type"] == "object"


def test_success_or_failure_output_schema_merges_defs_without_losing_variants() -> None:
    schema = success_or_failure_output_schema(
        {
            "title": "TypedSuccess",
            "type": "object",
            "properties": {
                "item": {"$ref": "#/$defs/TypedItem"},
            },
            "required": ["item"],
            "$defs": {
                "TypedItem": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                }
            },
        }
    )

    assert schema["type"] == "object"
    assert "TypedItem" in schema["$defs"]
    success_variant, failure_variant = schema["oneOf"]
    assert success_variant["properties"]["item"] == {"$ref": "#/$defs/TypedItem"}
    assert failure_variant["properties"]["ok"] == {
        "const": False,
        "default": False,
        "title": "Ok",
        "type": "boolean",
    }
