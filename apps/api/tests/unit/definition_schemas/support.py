from __future__ import annotations

import re
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import yaml
from autoclaw.definitions.contracts import (
    PolicyDefinitionFile,
    PolicyDefinitionInput,
    RoleDefinitionFile,
    RoleDefinitionInput,
    WorkflowDefinitionFile,
)
from autoclaw.definitions.seeds import resolve_packaged_seed_definitions_root

REPO_ROOT = Path(__file__).resolve().parents[5]
REFERENCE_DEFINITIONS_ROOT = REPO_ROOT / "docs" / "reference" / "definitions"
ROLE_POLICY_SCHEMA_DOC = (
    REPO_ROOT
    / "docs-internal"
    / "design"
    / "v1"
    / "interfaces"
    / "role-and-policy-definition-schema.md"
)

EXPECTED_WORKFLOW_IDS = {
    "bugfix-review-release",
    "bounded-change",
    "core-only-build",
    "feature-implementation",
    "frontend-feature-slice",
    "idea-discovery",
    "delivery-batch",
    "marketing-campaign",
    "mvp-build",
    "planning-only",
    "project-management-delivery",
    "reviewed-change-release",
    "staged-delivery-release",
    "topic-research-brief",
}
EXPECTED_ROLE_IDS = {
    "architect",
    "bug_fix_engineer",
    "bug_triage",
    "code_reviewer",
    "core_architect",
    "engineer",
    "failure_analyst",
    "frontend_code_reviewer",
    "frontend_contract_integrator",
    "frontend_engineer",
    "frontend_visual_verifier",
    "market_researcher",
    "marketing_strategist",
    "planner",
    "planning_lead",
    "product_discovery_researcher",
    "product_planner",
    "product_reviewer",
    "product_story_strategist",
    "project_manager",
    "release_operator",
    "replan_planner",
    "researcher",
    "reviewer",
    "root_planning_lead",
    "scope_reviewer",
    "test_verifier",
    "delivery_planner",
}
EXPECTED_POLICY_IDS = {
    "standard-root",
    "standard-root-human-request",
    "standard-parent",
    "standard-parent-human-request",
    "standard-worker",
    "standard-worker-human-request",
    "standard-worker-command-run",
}

type RoleOrPolicyDefinitionModel = (
    type[RoleDefinitionInput]
    | type[RoleDefinitionFile]
    | type[PolicyDefinitionInput]
    | type[PolicyDefinitionFile]
)


def bounded_workflow_payload() -> dict[str, Any]:
    return {
        "id": "bounded-change",
        "description": (
            "Execute one small scoped change with one worker and root-owned evidence review."
        ),
        "root": {
            "node_key": "root",
            "kind": "root",
            "role_id": "planning_lead",
            "policy_id": "standard-root",
            "description": (
                "Verify one bounded worker and close only when current evidence is sufficient."
            ),
            "criteria": [
                {
                    "slot": "implementation_rules",
                    "description": "Root acceptance criteria for the bounded worker.",
                    "criteria": [
                        "the worker stays inside the current bounded assignment",
                        "publish patch and verification evidence only through declared "
                        "produce slots",
                    ],
                }
            ],
            "children": [
                {
                    "node_key": "implement_change",
                    "kind": "worker",
                    "role_id": "engineer",
                    "policy_id": "standard-worker",
                    "description": (
                        "Implement the change and publish patch plus verification evidence "
                        "only for the current bounded assignment."
                    ),
                    "criteria": [
                        {
                            "slot": "implement_change_delivery_criteria",
                            "description": "Delivery criteria for the bounded engineering change.",
                            "criteria": [
                                "patch is limited to the assigned path",
                                "verification evidence demonstrates the intended fix",
                            ],
                        }
                    ],
                    "produces": {
                        "artifacts": [
                            {
                                "slot": "change_patch",
                                "file_hint": "change_patch.diff",
                                "description": "Patch for the bounded change.",
                            },
                            {
                                "slot": "verification_report",
                                "file_hint": "verification_report.md",
                                "description": "Verification evidence for the bounded change.",
                            },
                        ]
                    },
                }
            ],
        },
    }


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def load_first_yaml_fence(path: Path) -> dict[str, Any]:
    match = re.search(r"```yaml\n(.*?)\n```", path.read_text(encoding="utf-8"), re.DOTALL)
    assert match is not None, f"expected a yaml fence in {path}"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return data


def load_yaml_fences(path: Path) -> list[str]:
    return re.findall(r"```yaml\n(.*?)\n```", path.read_text(encoding="utf-8"), re.DOTALL)


def load_role_policy_schema_examples() -> list[dict[str, Any]]:
    return [
        payload
        for yaml_fence in load_yaml_fences(ROLE_POLICY_SCHEMA_DOC)
        if isinstance((payload := yaml.safe_load(yaml_fence)), dict)
        and payload.get("id") != "string"
    ]


def load_registry_catalog(
    definitions_root: Path,
) -> tuple[dict[str, RoleDefinitionFile], dict[str, PolicyDefinitionFile]]:
    roles: dict[str, RoleDefinitionFile] = {}
    policies: dict[str, PolicyDefinitionFile] = {}

    for path in sorted((definitions_root / "roles").glob("*.yaml")):
        role = RoleDefinitionFile.model_validate(load_yaml(path))
        roles[role.id] = role

    for path in sorted((definitions_root / "policies").glob("*.yaml")):
        policy = PolicyDefinitionFile.model_validate(load_yaml(path))
        policies[policy.id] = policy

    return roles, policies


def load_workflow_ids(
    definitions_root: Path,
    *,
    roles: dict[str, RoleDefinitionFile],
    policies: dict[str, PolicyDefinitionFile],
) -> set[str]:
    validation_context = {"roles": roles, "policies": policies}
    return {
        WorkflowDefinitionFile.model_validate(
            load_yaml(path),
            context=validation_context,
        ).id
        for path in sorted((definitions_root / "workflows").glob("*.yaml"))
    }


def load_definition_tree(definitions_root: Path) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}

    for kind in ("roles", "policies", "workflows"):
        for path in sorted((definitions_root / kind).glob("*.yaml")):
            payloads[str(path.relative_to(definitions_root))] = load_yaml(path)

    return payloads


def resolve_committed_seed_definitions_root() -> AbstractContextManager[Path]:
    return resolve_packaged_seed_definitions_root()


def workflow_validation_context(definitions_root: Path) -> dict[str, Any]:
    roles, policies = load_registry_catalog(definitions_root)
    return {"roles": roles, "policies": policies}


def assert_expected_role_and_policy_ids(
    roles: dict[str, RoleDefinitionFile],
    policies: dict[str, PolicyDefinitionFile],
) -> None:
    assert EXPECTED_ROLE_IDS <= set(roles)
    assert EXPECTED_POLICY_IDS <= set(policies)
