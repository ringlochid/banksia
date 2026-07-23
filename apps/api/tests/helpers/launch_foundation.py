from __future__ import annotations

from pathlib import Path

from banksia.persistence import RuntimeBase
from banksia.runtime import TaskComposeInput
from banksia.runtime.contracts import RuntimeBootstrapInput
from banksia.runtime.launch.legacy_team_adapter import project_legacy_team_plan
from banksia.runtime.team import plan_initial_task_team
from banksia.workflows.canonical import canonical_workflow_hash
from banksia.workflows.contracts import (
    CodexProviderSelection,
    NormalizedMember,
    NormalizedWorkflow,
    PublishedWorkflowRevision,
)
from sqlalchemy import Connection


def build_launch_foundation_workflow_revision() -> PublishedWorkflowRevision:
    workflow = NormalizedWorkflow(
        kind="workflow",
        id="workflow-target",
        description="Launch one provider-pinned root Member.",
        lead=NormalizedMember(
            id="root",
            title="Root Member",
            description="Coordinate the task.",
            provider=CodexProviderSelection(kind="codex"),
        ),
    )
    return PublishedWorkflowRevision(
        workflow_id=workflow.id,
        revision_no=1,
        content_hash=canonical_workflow_hash(workflow),
        workflow=workflow,
    )


def build_launch_foundation_input(
    tmp_path: Path,
    *,
    workflow_revision: PublishedWorkflowRevision,
) -> RuntimeBootstrapInput:
    task_id = "task.launch-foundation"
    initial_team = plan_initial_task_team(workflow_revision, task_id)
    compiled_plan = project_legacy_team_plan(workflow_revision, initial_team)
    return RuntimeBootstrapInput(
        task_id=task_id,
        active_flow_revision_id="flow-revision.launch-foundation.1",
        attempt_id="attempt.launch-foundation.root.1",
        assignment_key="task.launch-foundation.root.assignment.1",
        task_root=tmp_path / "task-root",
        task_compose=TaskComposeInput.model_validate(
            {
                "task": {
                    "key": "launch-foundation",
                    "title": "Launch foundation",
                    "summary": "Persist provider, Team, and budget truth.",
                },
                "workflow": {"key": workflow_revision.workflow_id},
            }
        ),
        workflow_revision=workflow_revision,
        initial_team=initial_team,
        compiled_plan=compiled_plan,
    )


def seed_launch_foundation_workflow(
    connection: Connection,
    *,
    workflow_revision: PublishedWorkflowRevision,
) -> None:
    definitions = RuntimeBase.metadata.tables["workflow_definitions"]
    revisions = RuntimeBase.metadata.tables["workflow_revisions"]
    connection.execute(
        definitions.insert(),
        {
            "workflow_key": workflow_revision.workflow_id,
            "current_revision_no": None,
        },
    )
    connection.execute(
        revisions.insert(),
        {
            "workflow_revision_id": "workflow-revision.workflow-target.1",
            "workflow_key": workflow_revision.workflow_id,
            "revision_no": workflow_revision.revision_no,
            "content_hash": workflow_revision.content_hash,
            "content_json": workflow_revision.workflow.model_dump(
                mode="json",
                exclude_none=True,
            ),
            "provenance": "user",
            "source_path": None,
        },
    )
    connection.execute(
        definitions.update()
        .where(definitions.c.workflow_key == workflow_revision.workflow_id)
        .values(current_revision_no=workflow_revision.revision_no)
    )


__all__ = [
    "build_launch_foundation_input",
    "build_launch_foundation_workflow_revision",
    "seed_launch_foundation_workflow",
]
