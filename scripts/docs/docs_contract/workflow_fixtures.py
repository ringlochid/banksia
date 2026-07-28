from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from referencing.exceptions import Unresolvable

from .authored_guidance import generic_guidance_messages, seed_dependency_messages
from .links import iter_markdown_links
from .models import ContractFinding
from .strict_yaml import StrictYamlError, load_strict_yaml
from .workflow_schema import workflow_schema_reference_findings

WORKFLOW_SCHEMA_PATH = Path("docs/reference/workflows/workflow-definition.schema.yaml")
WORKFLOW_EXAMPLE_ROOT = Path("examples/workflows")
WORKFLOW_SEED_ROOT = Path("src/banksia/workflows/resources/starter_workflows")
WORKFLOW_EXAMPLE_README_PATH = WORKFLOW_EXAMPLE_ROOT / "README.md"
EXPECTED_WORKFLOW_EXAMPLE_FILES = (
    "advanced-cross-layer-delivery.yaml",
    "advanced-reviewed-code-change.yaml",
    "advanced-technical-decision.yaml",
)
EXPECTED_WORKFLOW_SEED_FILES = (
    "decision-through-competing-prototypes.yaml",
    "deep-research-and-decision-brief.yaml",
    "experiment-and-replication-program.yaml",
    "idea-to-validated-demo.yaml",
    "incident-investigation-and-recovery.yaml",
    "migration-and-modernisation.yaml",
    "production-feature-delivery.yaml",
    "security-audit-and-hardening.yaml",
)
DRAFT_2020_12_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"


def workflow_fixture_findings(root: Path) -> list[ContractFinding]:
    """Validate the tracked Workflow schema, examples, and provider-neutral seeds."""

    findings = inventory_findings(root)
    findings.extend(readme_inventory_findings(root))
    findings.extend(distinct_inventory_findings(root))
    schema_path = root / WORKFLOW_SCHEMA_PATH
    schema_value, schema_finding = load_workflow_yaml(root=root, path=schema_path)
    if schema_finding is not None:
        findings.append(schema_finding)
        return findings
    if not isinstance(schema_value, dict):
        findings.append(
            workflow_finding(
                root=root,
                path=schema_path,
                message="Workflow schema must be one YAML object document",
            )
        )
        return findings

    schema = schema_value
    schema_is_valid = validate_schema(root=root, path=schema_path, schema=schema, findings=findings)
    validator = Draft202012Validator(schema) if schema_is_valid else None

    workflow_id_locations: dict[str, Path] = {}
    for family_root, filenames, is_seed in (
        (WORKFLOW_EXAMPLE_ROOT, EXPECTED_WORKFLOW_EXAMPLE_FILES, False),
        (WORKFLOW_SEED_ROOT, EXPECTED_WORKFLOW_SEED_FILES, True),
    ):
        findings.extend(
            workflow_family_findings(
                root=root,
                family_root=family_root,
                filenames=filenames,
                is_seed=is_seed,
                validator=validator,
                workflow_id_locations=workflow_id_locations,
            )
        )
    return findings


def workflow_family_findings(
    *,
    root: Path,
    family_root: Path,
    filenames: tuple[str, ...],
    is_seed: bool,
    validator: Draft202012Validator | None,
    workflow_id_locations: dict[str, Path],
) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for filename in filenames:
        fixture_path = root / family_root / filename
        if not fixture_path.is_file():
            continue
        fixture, fixture_finding = load_workflow_yaml(root=root, path=fixture_path)
        if fixture_finding is not None:
            findings.append(fixture_finding)
        elif not isinstance(fixture, dict):
            findings.append(
                workflow_finding(
                    root=root,
                    path=fixture_path,
                    message="Workflow fixture must be one YAML object document",
                )
            )
        else:
            findings.extend(
                workflow_document_findings(
                    root=root,
                    path=fixture_path,
                    fixture=fixture,
                    is_seed=is_seed,
                    validator=validator,
                    workflow_id_locations=workflow_id_locations,
                )
            )
    return findings


def workflow_document_findings(
    *,
    root: Path,
    path: Path,
    fixture: dict[str, Any],
    is_seed: bool,
    validator: Draft202012Validator | None,
    workflow_id_locations: dict[str, Path],
) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    if validator is not None:
        schema_messages = fixture_schema_error_messages(fixture=fixture, validator=validator)
        findings.extend(
            workflow_finding(root=root, path=path, message=message) for message in schema_messages
        )
        findings.extend(
            json_round_trip_findings(
                root=root,
                path=path,
                fixture=fixture,
                validator=validator,
                initial_schema_messages=schema_messages,
            )
        )

    members = tuple(iter_workflow_members(fixture))
    findings.extend(member_identity_findings(root=root, path=path, members=members))
    findings.extend(
        workflow_finding(root=root, path=path, message=message)
        for message in generic_guidance_messages(fixture=fixture, members=members)
    )
    if is_seed:
        findings.extend(portable_seed_findings(root=root, path=path, members=members))
        findings.extend(
            workflow_finding(root=root, path=path, message=message)
            for message in seed_dependency_messages(fixture)
        )
    workflow_id = fixture.get("id")
    if isinstance(workflow_id, str):
        if path.stem != workflow_id:
            findings.append(
                workflow_finding(
                    root=root,
                    path=path,
                    message=(
                        f"Workflow fixture filename stem {path.stem!r} "
                        f"must equal Workflow id {workflow_id!r}"
                    ),
                )
            )
        first_path = workflow_id_locations.setdefault(workflow_id, path)
        if first_path != path:
            findings.append(
                workflow_finding(
                    root=root,
                    path=path,
                    message=(
                        f"Workflow id {workflow_id!r} must be distinct across reference "
                        "examples and packaged seeds; first used by "
                        f"{first_path.relative_to(root)}"
                    ),
                )
            )
    return findings


def inventory_findings(root: Path) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for family_name, family_root, expected_names in (
        ("reference-example", WORKFLOW_EXAMPLE_ROOT, EXPECTED_WORKFLOW_EXAMPLE_FILES),
        ("packaged-seed", WORKFLOW_SEED_ROOT, EXPECTED_WORKFLOW_SEED_FILES),
    ):
        absolute_root = root / family_root
        actual_names = tuple(
            path.name
            for path in sorted(absolute_root.iterdir() if absolute_root.is_dir() else ())
            if path.is_file() and path.suffix in {".json", ".yaml", ".yml"}
        )
        if actual_names == expected_names:
            continue
        missing = sorted(set(expected_names) - set(actual_names))
        unexpected = sorted(set(actual_names) - set(expected_names))
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        findings.append(
            workflow_finding(
                root=root,
                path=absolute_root,
                message=f"{family_name} Workflow inventory mismatch; {'; '.join(details)}",
            )
        )
    return findings


def readme_inventory_findings(root: Path) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for family_name, readme_path, expected_names in (
        ("reference-example", WORKFLOW_EXAMPLE_README_PATH, EXPECTED_WORKFLOW_EXAMPLE_FILES),
    ):
        absolute_readme_path = root / readme_path
        if not absolute_readme_path.is_file():
            findings.append(
                workflow_finding(
                    root=root,
                    path=absolute_readme_path,
                    message=f"{family_name} Workflow README is missing",
                )
            )
            continue
        linked_names: list[str] = []
        nonlocal_targets: list[str] = []
        for link in iter_markdown_links(absolute_readme_path.read_text(encoding="utf-8")):
            parsed_target = urlparse(link.target)
            target_path = Path(parsed_target.path)
            if parsed_target.scheme or parsed_target.netloc or target_path.suffix != ".yaml":
                continue
            if target_path.parent != Path("."):
                nonlocal_targets.append(link.target)
                continue
            linked_names.append(target_path.name)

        missing = sorted(set(expected_names) - set(linked_names))
        unexpected = sorted(set(linked_names) - set(expected_names))
        duplicates = sorted(name for name in set(linked_names) if linked_names.count(name) > 1)
        if not (missing or unexpected or duplicates or nonlocal_targets):
            continue
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        if duplicates:
            details.append(f"duplicate: {', '.join(duplicates)}")
        if nonlocal_targets:
            details.append(f"nonlocal: {', '.join(sorted(nonlocal_targets))}")
        findings.append(
            workflow_finding(
                root=root,
                path=absolute_readme_path,
                message=f"{family_name} Workflow README inventory mismatch; {'; '.join(details)}",
            )
        )
    return findings


def distinct_inventory_findings(root: Path) -> list[ContractFinding]:
    overlapping_names = sorted(
        set(EXPECTED_WORKFLOW_EXAMPLE_FILES) & set(EXPECTED_WORKFLOW_SEED_FILES)
    )
    if not overlapping_names:
        return []
    return [
        workflow_finding(
            root=root,
            path=root / WORKFLOW_EXAMPLE_ROOT,
            message=(
                "reference examples and packaged seeds must use distinct paths; overlap: "
                + ", ".join(overlapping_names)
            ),
        )
    ]


def validate_schema(
    *,
    root: Path,
    path: Path,
    schema: dict[str, Any],
    findings: list[ContractFinding],
) -> bool:
    if schema.get("$schema") != DRAFT_2020_12_SCHEMA_URI:
        findings.append(
            workflow_finding(
                root=root,
                path=path,
                message=f"Workflow schema must declare {DRAFT_2020_12_SCHEMA_URI!r}",
            )
        )
        return False
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        findings.append(
            workflow_finding(
                root=root,
                path=path,
                message=f"Workflow schema is not valid Draft 2020-12: {error.message}",
            )
        )
        return False
    reference_findings = workflow_schema_reference_findings(
        root=root,
        path=path,
        schema=schema,
    )
    findings.extend(reference_findings)
    return not reference_findings


def fixture_schema_error_messages(
    *,
    fixture: dict[str, Any],
    validator: Draft202012Validator,
) -> tuple[str, ...]:
    try:
        errors = sorted(
            validator.iter_errors(fixture),
            key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
        )
    except Unresolvable as error:
        return (f"Workflow schema reference resolution failed without retrieval: {error}",)
    return tuple(
        f"Workflow fixture fails schema at {error.json_path}: {error.message}" for error in errors
    )


def json_round_trip_findings(
    *,
    root: Path,
    path: Path,
    fixture: dict[str, Any],
    validator: Draft202012Validator,
    initial_schema_messages: tuple[str, ...],
) -> list[ContractFinding]:
    try:
        serialized = json.dumps(
            fixture,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        round_tripped = json.loads(serialized)
    except (TypeError, ValueError) as error:
        return [
            workflow_finding(
                root=root,
                path=path,
                message=f"Workflow fixture cannot round-trip through strict JSON: {error}",
            )
        ]

    findings: list[ContractFinding] = []
    if round_tripped != fixture:
        findings.append(
            workflow_finding(
                root=root,
                path=path,
                message="Workflow fixture JSON round-trip changed its normalized value",
            )
        )
    repeated_schema_messages = fixture_schema_error_messages(
        fixture=round_tripped,
        validator=validator,
    )
    if repeated_schema_messages != initial_schema_messages:
        findings.append(
            workflow_finding(
                root=root,
                path=path,
                message="Workflow fixture JSON round-trip changed its schema validation result",
            )
        )
    return findings


def member_identity_findings(
    *,
    root: Path,
    path: Path,
    members: tuple[Mapping[str, Any], ...],
) -> list[ContractFinding]:
    seen: set[str] = set()
    findings: list[ContractFinding] = []
    for member in members:
        member_id = member.get("id")
        if not isinstance(member_id, str):
            continue
        if member_id in seen:
            findings.append(
                workflow_finding(
                    root=root,
                    path=path,
                    message=f"duplicate Member id {member_id!r} in one Workflow tree",
                )
            )
        seen.add(member_id)
    return findings


def portable_seed_findings(
    *,
    root: Path,
    path: Path,
    members: tuple[Mapping[str, Any], ...],
) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for member in members:
        member_id = member.get("id", "<unknown>")
        if "provider" in member:
            findings.append(
                workflow_finding(
                    root=root,
                    path=path,
                    message=(f"packaged seed Member {member_id!r} must omit 'provider'"),
                )
            )
    return findings


def iter_workflow_members(workflow: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    lead = workflow.get("lead")
    if not isinstance(lead, dict):
        return
    pending: list[Mapping[str, Any]] = [lead]
    while pending:
        member = pending.pop()
        yield member
        children = member.get("children")
        if not isinstance(children, list):
            continue
        pending.extend(reversed([child for child in children if isinstance(child, dict)]))


def load_workflow_yaml(
    *,
    root: Path,
    path: Path,
) -> tuple[object | None, ContractFinding | None]:
    if not path.is_file():
        return None, workflow_finding(
            root=root,
            path=path,
            message="required Workflow schema or fixture is missing",
        )
    try:
        return load_strict_yaml(path), None
    except (OSError, UnicodeDecodeError, yaml.YAMLError, StrictYamlError) as error:
        problem_mark = getattr(error, "problem_mark", None)
        return None, workflow_finding(
            root=root,
            path=path,
            message=f"strict YAML load failed: {describe_yaml_error(error)}",
            line=problem_mark.line + 1 if problem_mark is not None else 1,
        )


def describe_yaml_error(error: Exception) -> str:
    problem_mark = getattr(error, "problem_mark", None)
    if problem_mark is None:
        return str(error)
    return f"line {problem_mark.line + 1}, column {problem_mark.column + 1}: {error}"


def workflow_finding(
    *,
    root: Path,
    path: Path,
    message: str,
    line: int = 1,
) -> ContractFinding:
    return ContractFinding(
        category="workflow-fixture",
        path=path.relative_to(root),
        line=line,
        message=message,
    )


__all__ = [
    "EXPECTED_WORKFLOW_EXAMPLE_FILES",
    "EXPECTED_WORKFLOW_SEED_FILES",
    "WORKFLOW_SCHEMA_PATH",
    "load_strict_yaml",
    "workflow_fixture_findings",
]
