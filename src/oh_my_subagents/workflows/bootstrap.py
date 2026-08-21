from __future__ import annotations

from importlib.resources import files
from pathlib import PurePath

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.workflows.contracts import PublishedWorkflowRevision, WorkflowProvenance
from oh_my_subagents.workflows.ingest import parse_workflow
from oh_my_subagents.workflows.publication import publish_workflow_revision

STARTER_WORKFLOW_FILENAMES = (
    "decision-through-competing-prototypes.yaml",
    "deep-research-and-decision-brief.yaml",
    "experiment-and-replication-program.yaml",
    "idea-to-validated-demo.yaml",
    "incident-investigation-and-recovery.yaml",
    "migration-and-modernisation.yaml",
    "production-feature-delivery.yaml",
    "security-audit-and-hardening.yaml",
)


async def seed_starter_workflows(
    session: AsyncSession,
) -> tuple[PublishedWorkflowRevision, ...]:
    results: list[PublishedWorkflowRevision] = []
    root = files("oh_my_subagents.workflows.resources.starter_workflows")
    for filename in STARTER_WORKFLOW_FILENAMES:
        resource = root.joinpath(filename)
        workflow = parse_workflow(resource.read_bytes(), source_format="yaml")
        if PurePath(filename).stem != workflow.id:
            raise ValueError(
                f"Starter Workflow filename stem {PurePath(filename).stem!r} "
                f"must equal Workflow id {workflow.id!r}"
            )
        _verify_provider_neutral_seed(workflow.model_dump(mode="json", exclude_none=True))
        results.append(
            await publish_workflow_revision(
                session,
                workflow=workflow,
                provenance=WorkflowProvenance.STARTER_SEED,
                should_update_current=True,
                source_path=f"seed://starter-workflows/{filename}",
                current_provenance_guard=WorkflowProvenance.STARTER_SEED,
            )
        )
    return tuple(results)


def _verify_provider_neutral_seed(value: object) -> None:
    if isinstance(value, dict):
        if "provider" in value:
            raise ValueError("Starter Workflow contains non-portable field: provider")
        for child in value.values():
            _verify_provider_neutral_seed(child)
    elif isinstance(value, list):
        for child in value:
            _verify_provider_neutral_seed(child)


__all__ = ["STARTER_WORKFLOW_FILENAMES", "seed_starter_workflows"]
