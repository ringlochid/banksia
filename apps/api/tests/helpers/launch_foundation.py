from __future__ import annotations

from pathlib import Path

from autoclaw.definitions.compiler import (
    MappingRolePolicyLookup,
    PolicyRevisionDefinition,
    RoleRevisionDefinition,
    WorkflowRevisionMetadata,
    compile_workflow,
)
from autoclaw.definitions.contracts import (
    BudgetSpec,
    PolicyDefinitionInput,
    RoleDefinitionInput,
    WorkflowDefinitionInput,
)
from autoclaw.definitions.contracts.workflow import (
    CodexProviderSelection,
    NodeKind,
    ProviderKind,
    RootNodeDefinition,
)
from autoclaw.persistence import RuntimeBase
from autoclaw.runtime import TaskComposeInput
from autoclaw.runtime.contracts import RuntimeBootstrapInput
from sqlalchemy import Connection

from tests.helpers.catalog_seed import seed_catalog


def build_launch_foundation_definitions() -> tuple[
    RoleDefinitionInput,
    PolicyDefinitionInput,
    WorkflowDefinitionInput,
]:
    role = RoleDefinitionInput(
        id="role.target",
        description="Coordinate bounded work.",
        allowed_node_kinds=[NodeKind.ROOT],
    )
    policy = PolicyDefinitionInput(
        id="policy.target",
        description="Bound child assignment creation.",
        applies_to=[NodeKind.ROOT],
        budget_spec=BudgetSpec(child_assignment_limit=3),
    )
    workflow = WorkflowDefinitionInput(
        id="workflow.target",
        description="Launch one provider-pinned root.",
        root=RootNodeDefinition(
            node_key="root",
            kind=NodeKind.ROOT,
            role_id=role.id,
            policy_id=policy.id,
            provider=CodexProviderSelection(kind=ProviderKind.CODEX),
            description="Coordinate the task.",
        ),
    )
    return role, policy, workflow


def build_launch_foundation_input(
    tmp_path: Path,
    *,
    role: RoleDefinitionInput,
    policy: PolicyDefinitionInput,
    workflow: WorkflowDefinitionInput,
) -> RuntimeBootstrapInput:
    lookup = MappingRolePolicyLookup(
        roles={role.id: RoleRevisionDefinition(definition=role, revision_no=1)},
        policies={policy.id: PolicyRevisionDefinition(definition=policy, revision_no=1)},
    )
    compiled_plan = compile_workflow(
        workflow=workflow,
        workflow_revision=WorkflowRevisionMetadata(
            workflow_key=workflow.id,
            definition_revision_no=1,
        ),
        compiler_version="launch-foundation-test",
        lookup=lookup,
    )
    return RuntimeBootstrapInput(
        task_id="task.launch-foundation",
        active_flow_revision_id="flow-revision.launch-foundation.1",
        attempt_id="attempt.launch-foundation.root.1",
        assignment_key="task.launch-foundation.root.assignment.1",
        task_root=tmp_path / "task-root",
        task_compose=TaskComposeInput.model_validate(
            {
                "task": {
                    "key": "launch-foundation",
                    "title": "Launch foundation",
                    "summary": "Persist provider and budget truth.",
                },
                "workflow": {"key": workflow.id},
            }
        ),
        workflow_definition=workflow,
        compiled_plan=compiled_plan,
        role_policy_lookup=lookup,
    )


def seed_launch_foundation_catalog(
    connection: Connection,
    *,
    role: RoleDefinitionInput,
    policy: PolicyDefinitionInput,
    workflow: WorkflowDefinitionInput,
) -> None:
    seed_catalog(connection)
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["role_revisions"]
        .update()
        .where(tables["role_revisions"].c.role_key == role.id)
        .values(content_json=role.model_dump(mode="json"))
    )
    connection.execute(
        tables["policy_revisions"]
        .update()
        .where(tables["policy_revisions"].c.policy_key == policy.id)
        .values(content_json=policy.model_dump(mode="json"))
    )
    connection.execute(
        tables["workflow_revisions"]
        .update()
        .where(tables["workflow_revisions"].c.workflow_key == workflow.id)
        .values(content_json=workflow.model_dump(mode="json"))
    )


__all__ = [
    "build_launch_foundation_definitions",
    "build_launch_foundation_input",
    "seed_launch_foundation_catalog",
]
