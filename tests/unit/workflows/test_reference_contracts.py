from __future__ import annotations

from pathlib import Path

import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from banksia.workflows import NormalizedWorkflow, parse_workflow

APPENDIX_ROOT = Path(__file__).resolve().parents[3] / "docs-internal/design/appendices"


def test_tracked_workflow_examples_and_seeds_pass_schema_and_strict_ingest() -> None:
    schema = yaml.safe_load(
        (APPENDIX_ROOT / "workflow-definition.schema.yaml").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    paths = tuple(sorted((APPENDIX_ROOT / "workflow-examples").glob("*.yaml"))) + tuple(
        sorted((APPENDIX_ROOT / "workflow-seeds").glob("*.yaml"))
    )

    assert len(paths) == 7
    for path in paths:
        raw = path.read_bytes()
        parsed_yaml = yaml.safe_load(raw)
        validator.validate(parsed_yaml)
        normalized = parse_workflow(raw, source_format="yaml")
        assert normalized.id == parsed_yaml["id"]


def test_generated_workflow_schema_exposes_strict_omission_and_provider_rules() -> None:
    validator = Draft202012Validator(NormalizedWorkflow.model_json_schema())
    valid = {
        "kind": "workflow",
        "id": "schema-proof",
        "description": "Generated schema proof.",
        "lead": {
            "id": "lead",
            "provider": {
                "kind": "codex",
                "effort": "high",
                "sandbox": {"mode": "workspace_write", "network": "deny"},
            },
            "capabilities": {"command_run": "allow"},
        },
    }
    validator.validate(valid)

    invalid_values = (
        valid | {"lead": {"id": "lead", "provider": None}},
        valid
        | {
            "lead": {
                "id": "lead",
                "provider": {"kind": "codex", "model": None},
            }
        },
        valid | {"lead": {"id": "lead", "capabilities": {}}},
        valid
        | {
            "lead": {
                "id": "lead",
                "provider": {
                    "kind": "codex",
                    "sandbox": {"mode": "read_only", "network": "allow"},
                },
            }
        },
    )
    assert all(tuple(validator.iter_errors(value)) for value in invalid_values)
