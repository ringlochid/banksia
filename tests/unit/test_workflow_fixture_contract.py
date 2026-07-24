from __future__ import annotations

import importlib
import math
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing.exceptions import Unresolvable

from .docs_contract_test_tree import (
    build_valid_contract_tree,
    contract_modules,
    ensure_repo_root_on_path,
    workflow_finding_messages,
)

APPENDIX_ROOT = Path("docs-internal/design/appendices")
SCHEMA_PATH = APPENDIX_ROOT / "workflow-definition.schema.yaml"
MINIMAL_PATH = APPENDIX_ROOT / "workflow-examples/minimal.yaml"
EXAMPLE_README_PATH = APPENDIX_ROOT / "workflow-examples/README.md"
SEED_PATH = APPENDIX_ROOT / "workflow-seeds/reviewed-delivery.yaml"


def workflow_modules() -> tuple[Any, Any]:
    ensure_repo_root_on_path()
    fixtures = importlib.import_module("scripts.docs.docs_contract.workflow_fixtures")
    schema = importlib.import_module("scripts.docs.docs_contract.workflow_schema")
    return fixtures, schema


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def write_yaml_mapping(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def workflow_findings(report: Any, *, path: Path | None = None) -> list[Any]:
    return [
        finding
        for finding in report.findings
        if finding.category == "workflow-fixture" and (path is None or finding.path == path)
    ]


def test_workflow_fixture_inventory_and_schema_are_validated(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    example_root = tmp_path / APPENDIX_ROOT / "workflow-examples"
    for unexpected_name in ("unexpected.yaml", "alternate.yml"):
        (example_root / unexpected_name).write_text(
            (example_root / "minimal.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (example_root / "unexpected.json").write_text(
        '{"kind":"workflow","id":"unexpected","description":"Unexpected.","lead":{"id":"lead"}}\n',
        encoding="utf-8",
    )
    schema_path = tmp_path / SCHEMA_PATH
    schema_path.write_text(
        schema_path.read_text(encoding="utf-8").replace(
            "type: object",
            "type: not-a-json-schema-type",
            1,
        ),
        encoding="utf-8",
    )

    messages = workflow_finding_messages(validator.build_contract_report(tmp_path))

    assert any("unexpected.yaml" in message for message in messages)
    assert any("alternate.yml" in message for message in messages)
    assert any("unexpected.json" in message for message in messages)
    assert any("schema is not valid Draft 2020-12" in message for message in messages)


def test_workflow_semantics_enforce_tree_and_cross_family_identity(
    tmp_path: Path,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    minimal_path = tmp_path / MINIMAL_PATH
    minimal_path.write_text(
        minimal_path.read_text(encoding="utf-8") + "    children:\n        - id: lead\n",
        encoding="utf-8",
    )
    seed_path = tmp_path / SEED_PATH
    seed_path.write_text(
        seed_path.read_text(encoding="utf-8")
        .replace("id: reviewed-delivery\n", "id: direct-work\n", 1)
        .replace("    id: lead\n", "    id: lead\n    provider:\n        kind: codex\n", 1),
        encoding="utf-8",
    )

    messages = workflow_finding_messages(validator.build_contract_report(tmp_path))

    assert any("duplicate Member id 'lead'" in message for message in messages)
    assert any(
        "packaged seed Member 'lead' must omit 'provider'" in message for message in messages
    )
    assert any("Workflow id 'direct-work' must be distinct" in message for message in messages)


@pytest.mark.parametrize(
    ("yaml_text", "expected_message"),
    (
        (
            "kind: workflow\nid: direct-work\nid: duplicate\n"
            "description: Complete a task.\nlead:\n    id: lead\n",
            "duplicate YAML mapping key 'id'",
        ),
        (
            "kind: workflow\nid: direct-work\ndescription: Complete a task.\n"
            "lead: &lead\n    id: lead\ncopy: *lead\n",
            "YAML aliases are not allowed",
        ),
        (
            "kind: workflow\nid: direct-work\ndescription: Complete a task.\n"
            "lead:\n    <<: {id: lead}\n",
            "YAML merge keys are not allowed",
        ),
        (
            "kind: workflow\nid: direct-work\n"
            "description: !product Complete a task.\nlead:\n    id: lead\n",
            "could not determine a constructor for the tag '!product'",
        ),
        (
            "kind: workflow\nid: direct-work\ndescription: Complete a task.\n"
            "lead:\n    id: lead\n---\nkind: workflow\n",
            "expected a single document in the stream",
        ),
        (
            "kind: workflow\nid: direct-work\ndescription: Complete a task.\nlead:\n    1: lead\n",
            "YAML mapping keys must be strings",
        ),
        (
            "kind: workflow\nid: direct-work\ndescription: Complete a task.\n"
            "lead:\n    id: lead\n    title: .nan\n",
            "$.lead.title contains a non-finite number",
        ),
    ),
)
def test_workflow_fixture_loader_rejects_nonportable_yaml_with_diagnostics(
    tmp_path: Path,
    yaml_text: str,
    expected_message: str,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    (tmp_path / MINIMAL_PATH).write_text(yaml_text, encoding="utf-8")

    report = validator.build_contract_report(tmp_path)
    findings = workflow_findings(report, path=MINIMAL_PATH)

    assert any(expected_message in finding.message for finding in findings)
    assert all(finding.path == MINIMAL_PATH and finding.line >= 1 for finding in findings)


def test_workflow_readme_inventory_must_match_validated_fixtures(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    readme_path = tmp_path / EXAMPLE_README_PATH
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8").replace(
            "[Full](full.yaml)",
            "[Full](minimal.yaml)",
        ),
        encoding="utf-8",
    )

    messages = workflow_finding_messages(validator.build_contract_report(tmp_path))

    assert any(
        "reference-example Workflow README inventory mismatch" in message
        and "missing: full.yaml" in message
        and "duplicate: minimal.yaml" in message
        for message in messages
    )


def test_workflow_example_and_seed_paths_must_remain_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures, _ = workflow_modules()
    monkeypatch.setattr(
        fixtures,
        "EXPECTED_WORKFLOW_SEED_FILES",
        (*fixtures.EXPECTED_WORKFLOW_SEED_FILES, "minimal.yaml"),
    )

    findings = fixtures.distinct_inventory_findings(tmp_path)

    assert len(findings) == 1
    assert "overlap: minimal.yaml" in findings[0].message


def test_recursive_local_schema_reference_graph_is_valid(tmp_path: Path) -> None:
    _, schema_module = workflow_modules()
    build_valid_contract_tree(tmp_path)
    schema_path = tmp_path / SCHEMA_PATH
    schema = read_yaml_mapping(schema_path)

    findings = schema_module.workflow_schema_reference_findings(
        root=tmp_path,
        path=schema_path,
        schema=schema,
    )

    assert findings == []


@pytest.mark.parametrize(
    ("reference", "expected_message"),
    (
        (42, "must be a string"),
        ("https://example.invalid/workflow", "uses non-local reference"),
        ("other.yaml#/$defs/identifier", "uses non-local reference"),
        ("#identifier", "uses unsupported plain-name fragment"),
        ("#/$defs/bad%ZZ", "contains an invalid percent escape"),
        ("#/$defs/%FF", "contains non-UTF-8 percent encoding"),
        ("#/$defs/bad~2name", "contains an invalid JSON Pointer escape"),
        ("#/$defs/missing", "points to missing JSON Pointer"),
        ("#/required/00", "contains invalid array index"),
        ("#/required/99", "points to missing JSON Pointer"),
        ("#/title", "which is not a schema object or boolean"),
    ),
)
def test_schema_reference_validator_rejects_nondeterministic_or_broken_refs(
    tmp_path: Path,
    reference: object,
    expected_message: str,
) -> None:
    _, schema_module = workflow_modules()
    build_valid_contract_tree(tmp_path)
    schema_path = tmp_path / SCHEMA_PATH
    schema = read_yaml_mapping(schema_path)
    schema["properties"]["id"]["$ref"] = reference

    findings = schema_module.workflow_schema_reference_findings(
        root=tmp_path,
        path=schema_path,
        schema=schema,
    )

    assert any(expected_message in finding.message for finding in findings)


def test_schema_reference_validator_supports_escaped_and_percent_encoded_tokens(
    tmp_path: Path,
) -> None:
    _, schema_module = workflow_modules()
    build_valid_contract_tree(tmp_path)
    schema_path = tmp_path / SCHEMA_PATH
    schema = read_yaml_mapping(schema_path)
    schema["$defs"].update(
        {
            "slash/name": {},
            "tilde~name": {},
            "space name": {},
        }
    )
    schema["allOf"] = [
        {"$ref": "#/$defs/slash~1name"},
        {"$ref": "#/$defs/tilde~0name"},
        {"$ref": "#/$defs/space%20name"},
    ]

    findings = schema_module.workflow_schema_reference_findings(
        root=tmp_path,
        path=schema_path,
        schema=schema,
    )

    assert findings == []


def test_schema_reference_validator_rejects_dynamic_refs_and_nested_resources(
    tmp_path: Path,
) -> None:
    _, schema_module = workflow_modules()
    build_valid_contract_tree(tmp_path)
    schema_path = tmp_path / SCHEMA_PATH
    schema = read_yaml_mapping(schema_path)
    member_items = schema["$defs"]["workflowMember"]["properties"]["children"]["items"]
    member_items["$dynamicRef"] = member_items.pop("$ref")
    schema["properties"]["id"]["$id"] = "nested-identifier"

    findings = schema_module.workflow_schema_reference_findings(
        root=tmp_path,
        path=schema_path,
        schema=schema,
    )
    messages = {finding.message for finding in findings}

    assert any("unsupported $dynamicRef" in message for message in messages)
    assert any("creates a nested schema resource" in message for message in messages)


def test_schema_reference_validator_rejects_unused_and_broken_unused_defs(
    tmp_path: Path,
) -> None:
    _, schema_module = workflow_modules()
    build_valid_contract_tree(tmp_path)
    schema_path = tmp_path / SCHEMA_PATH
    schema = read_yaml_mapping(schema_path)
    schema["$defs"]["unused"] = {"type": "string"}
    schema["$defs"]["unusedBroken"] = {"$ref": "#/$defs/missing"}

    findings = schema_module.workflow_schema_reference_findings(
        root=tmp_path,
        path=schema_path,
        schema=schema,
    )
    messages = {finding.message for finding in findings}

    assert any("points to missing JSON Pointer" in message for message in messages)
    assert any("$defs entry 'unused' is unreachable" in message for message in messages)
    assert any("$defs entry 'unusedBroken' is unreachable" in message for message in messages)


def test_contract_report_rejects_a_broken_used_schema_ref(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    schema_path = tmp_path / SCHEMA_PATH
    schema = read_yaml_mapping(schema_path)
    schema["properties"]["id"]["$ref"] = "#/$defs/missing"
    write_yaml_mapping(schema_path, schema)

    messages = workflow_finding_messages(validator.build_contract_report(tmp_path))

    assert any(
        "Workflow schema reference error" in message and "points to missing JSON Pointer" in message
        for message in messages
    )


def test_fixture_schema_resolution_failure_becomes_a_diagnostic() -> None:
    fixtures, _ = workflow_modules()

    class FailingValidator:
        def iter_errors(self, _fixture: object) -> object:
            raise Unresolvable(ref="#/$defs/missing")

    messages = fixtures.fixture_schema_error_messages(
        fixture={},
        validator=FailingValidator(),
    )

    assert len(messages) == 1
    assert "reference resolution failed without retrieval" in messages[0]


def test_json_round_trip_detects_nonfinite_and_changed_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures, _ = workflow_modules()
    path = tmp_path / "fixture.yaml"
    validator = Draft202012Validator(
        {
            "type": "object",
            "required": ["kind"],
            "properties": {"kind": {"const": "workflow"}},
        }
    )

    nonfinite_findings = fixtures.json_round_trip_findings(
        root=tmp_path,
        path=path,
        fixture={"kind": "workflow", "score": math.nan},
        validator=validator,
        initial_schema_messages=(),
    )
    assert any(
        "cannot round-trip through strict JSON" in finding.message for finding in nonfinite_findings
    )

    monkeypatch.setattr(fixtures.json, "loads", lambda _serialized: {})
    changed_findings = fixtures.json_round_trip_findings(
        root=tmp_path,
        path=path,
        fixture={"kind": "workflow"},
        validator=validator,
        initial_schema_messages=(),
    )
    changed_messages = {finding.message for finding in changed_findings}
    assert "Workflow fixture JSON round-trip changed its normalized value" in changed_messages
    assert (
        "Workflow fixture JSON round-trip changed its schema validation result" in changed_messages
    )


@pytest.mark.parametrize(
    ("field", "prose", "label"),
    (
        ("note", "Call open_human_request when blocked.", "controller operation"),
        ("instruction", "Record a Checkpoint after delivery.", "Checkpoint teaching"),
        ("note", "Create a Delegation Wave for the team.", "Delegation Wave teaching"),
        ("instruction", "Run the children in parallel.", "execution scheduling"),
        ("note", "Wait for children before continuing.", "runtime wait"),
        ("instruction", "Write a shared note under notes/.", "note or file-reference teaching"),
        ("note", "Do not simply relay a child's result.", "anti-relay teaching"),
    ),
)
def test_generic_orchestration_teaching_is_rejected_from_authored_workflows(
    tmp_path: Path,
    field: str,
    prose: str,
    label: str,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    minimal_path = tmp_path / MINIMAL_PATH
    fixture = read_yaml_mapping(minimal_path)
    if field == "note":
        fixture["note"] = prose
    else:
        fixture["lead"][field] = prose
    write_yaml_mapping(minimal_path, fixture)

    messages = workflow_finding_messages(validator.build_contract_report(tmp_path))

    assert any(f"contains generic {label}" in message for message in messages)


@pytest.mark.parametrize(
    ("prose", "label"),
    (
        ("Use OMX Autopilot for this delivery.", "OMC/OMX product"),
        ("Invoke /team before implementation.", "OMC/OMX command"),
        ("Ask the Prometheus agent to plan.", "OMC/OMX agent name"),
        ("Read MEMORY.md before starting.", "OMC/OMX memory file"),
    ),
)
def test_packaged_seeds_reject_omc_omx_runtime_dependencies(
    tmp_path: Path,
    prose: str,
    label: str,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    seed_path = tmp_path / SEED_PATH
    seed = read_yaml_mapping(seed_path)
    seed["lead"]["instruction"] = prose
    write_yaml_mapping(seed_path, seed)

    messages = workflow_finding_messages(validator.build_contract_report(tmp_path))

    assert any(f"depends on {label}" in message for message in messages)


def test_omc_omx_structural_inspiration_remains_allowed_in_reference_examples(
    tmp_path: Path,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)

    report = validator.build_contract_report(tmp_path)

    assert workflow_findings(report) == []
