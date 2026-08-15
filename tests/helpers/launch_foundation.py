from __future__ import annotations

from pathlib import Path

from sqlalchemy import Connection

from banksia.persistence import RuntimeBase
from banksia.platform.workspace_files import ensure_private_directory
from banksia.runtime.contracts import AssignmentBody, RuntimeBootstrapInput
from banksia.runtime.team import plan_initial_task_team
from banksia.workflows.canonical import canonical_workflow_hash
from banksia.workflows.contracts import (
    CodexProviderSelection,
    NormalizedMember,
    NormalizedWorkflow,
    PublishedWorkflowRevision,
)


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
    task_root = tmp_path / ".banksia" / task_id
    ensure_private_directory(task_root)
    return RuntimeBootstrapInput(
        task_id=task_id,
        attempt_id="attempt.launch-foundation.root.1",
        assignment_id="assignment.task.launch-foundation.root.assignment.1",
        task_root=task_root,
        workspace=tmp_path,
        assignment=AssignmentBody(
            prompt="Persist provider, Team, and budget truth.",
        ),
        workflow_revision=workflow_revision,
        initial_team=initial_team,
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
