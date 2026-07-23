from __future__ import annotations

from importlib.resources import files

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.workflows.contracts import PublishedWorkflowRevision, WorkflowProvenance
from banksia.workflows.ingest import parse_workflow
from banksia.workflows.publication import publish_workflow_revision

STARTER_WORKFLOW_FILENAMES = (
    "autonomous-delivery.yaml",
    "evidence-research.yaml",
    "reviewed-delivery.yaml",
)


async def seed_starter_workflows(
    session: AsyncSession,
) -> tuple[PublishedWorkflowRevision, ...]:
    results: list[PublishedWorkflowRevision] = []
    root = files("banksia.workflows.resources.starter_workflows")
    for filename in STARTER_WORKFLOW_FILENAMES:
        resource = root.joinpath(filename)
        workflow = parse_workflow(resource.read_bytes(), source_format="yaml")
        _verify_portable_seed(workflow.model_dump(mode="json", exclude_none=True))
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


def _verify_portable_seed(value: object) -> None:
    if isinstance(value, dict):
        forbidden = {"provider", "capabilities"} & value.keys()
        if forbidden:
            raise ValueError(
                "Starter Workflow contains non-portable fields: " + ", ".join(sorted(forbidden))
            )
        for child in value.values():
            _verify_portable_seed(child)
    elif isinstance(value, list):
        for child in value:
            _verify_portable_seed(child)


__all__ = ["STARTER_WORKFLOW_FILENAMES", "seed_starter_workflows"]
