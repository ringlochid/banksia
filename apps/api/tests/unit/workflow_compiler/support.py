from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from autoclaw.definitions.compiler import (
    MappingRolePolicyLookup,
    NormalizedCompiledPlan,
    PolicyRevisionDefinition,
    RoleRevisionDefinition,
    WorkflowRevisionMetadata,
    compile_workflow,
)
from autoclaw.definitions.contracts import (
    PolicyDefinitionFile,
    RoleDefinitionFile,
    WorkflowDefinitionFile,
    WorkflowDefinitionInput,
)
from autoclaw.definitions.seeds import resolve_packaged_seed_definitions_root

ROLE_REVISIONS = {
    "architect": 48,
    "bug_fix_engineer": 57,
    "bug_triage": 56,
    "code_reviewer": 58,
    "core_architect": 66,
    "engineer": 44,
    "failure_analyst": 60,
    "frontend_code_reviewer": 78,
    "frontend_contract_integrator": 79,
    "frontend_engineer": 80,
    "frontend_visual_verifier": 81,
    "market_researcher": 67,
    "marketing_strategist": 68,
    "planner": 47,
    "planning_lead": 42,
    "product_discovery_researcher": 82,
    "product_planner": 69,
    "product_reviewer": 70,
    "product_story_strategist": 83,
    "project_manager": 71,
    "release_operator": 46,
    "replan_planner": 62,
    "researcher": 43,
    "reviewer": 45,
    "root_planning_lead": 41,
    "scope_reviewer": 72,
    "test_verifier": 59,
    "delivery_planner": 61,
}

POLICY_REVISIONS = {
    "standard-root": 51,
    "standard-parent": 52,
    "standard-worker": 53,
    "standard-worker-command-run": 73,
    "standard-worker-human-request": 74,
    "standard-root-human-request": 75,
    "standard-parent-human-request": 76,
}

WORKFLOW_COMPILER_TEST_VERSION = "workflow-compiler-unit"


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def load_packaged_seed_lookup() -> MappingRolePolicyLookup:
    with resolve_packaged_seed_definitions_root() as packaged_seed_root:
        roles = {
            role.id: RoleRevisionDefinition(
                definition=role,
                revision_no=ROLE_REVISIONS[role.id],
            )
            for role in (
                RoleDefinitionFile.model_validate(load_yaml(path))
                for path in sorted((packaged_seed_root / "roles").glob("*.yaml"))
            )
        }
        policies = {
            policy.id: PolicyRevisionDefinition(
                definition=policy,
                revision_no=POLICY_REVISIONS[policy.id],
            )
            for policy in (
                PolicyDefinitionFile.model_validate(load_yaml(path))
                for path in sorted((packaged_seed_root / "policies").glob("*.yaml"))
            )
        }

    return MappingRolePolicyLookup(roles=roles, policies=policies)


def load_packaged_workflow_payload(name: str) -> dict[str, Any]:
    with resolve_packaged_seed_definitions_root() as packaged_seed_root:
        return load_yaml(packaged_seed_root / "workflows" / f"{name}.yaml")


def load_packaged_workflow_fixture(name: str) -> WorkflowDefinitionFile:
    return WorkflowDefinitionFile.model_validate(load_packaged_workflow_payload(name))


def compile_workflow_fixture(
    workflow: WorkflowDefinitionInput,
    revision_no: int,
) -> NormalizedCompiledPlan:
    return compile_workflow(
        workflow=workflow,
        workflow_revision=WorkflowRevisionMetadata(
            workflow_key=workflow.id,
            definition_revision_no=revision_no,
        ),
        compiler_version=WORKFLOW_COMPILER_TEST_VERSION,
        lookup=load_packaged_seed_lookup(),
    )


def compile_packaged_workflow_fixture(
    name: str,
    revision_no: int,
) -> NormalizedCompiledPlan:
    return compile_workflow_fixture(
        load_packaged_workflow_fixture(name),
        revision_no,
    )


def node_by_key(plan: Any, node_key: str) -> Any:
    return next(node for node in plan.nodes if node.node_key == node_key)
