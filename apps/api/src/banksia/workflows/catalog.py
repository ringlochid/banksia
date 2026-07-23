from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import WorkflowDefinitionModel, WorkflowRevisionModel
from banksia.workflows.contracts import (
    NormalizedWorkflow,
    PublishedWorkflowRevision,
    WorkflowProvenance,
    WorkflowRevisionSummary,
    WorkflowSummary,
)
from banksia.workflows.service_errors import WorkflowNotFoundError


async def read_published_workflow_revision(
    session: AsyncSession,
    *,
    workflow_id: str,
    revision_no: int,
) -> PublishedWorkflowRevision:
    row = await session.scalar(
        _target_revision_query().where(
            WorkflowRevisionModel.workflow_key == workflow_id,
            WorkflowRevisionModel.revision_no == revision_no,
        )
    )
    if row is None:
        raise WorkflowNotFoundError(
            f"published Workflow {workflow_id!r} revision {revision_no} does not exist"
        )
    return _published_revision(row)


async def read_current_published_workflow(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> PublishedWorkflowRevision:
    row = await session.scalar(
        _target_revision_query()
        .join(
            WorkflowDefinitionModel,
            (WorkflowDefinitionModel.workflow_key == WorkflowRevisionModel.workflow_key)
            & (WorkflowDefinitionModel.current_revision_no == WorkflowRevisionModel.revision_no),
        )
        .where(WorkflowDefinitionModel.workflow_key == workflow_id)
    )
    if row is None:
        raise WorkflowNotFoundError(f"published Workflow {workflow_id!r} does not exist")
    return _published_revision(row)


async def read_current_workflow_provenance(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> WorkflowProvenance:
    row = await session.scalar(
        _target_revision_query()
        .join(
            WorkflowDefinitionModel,
            (WorkflowDefinitionModel.workflow_key == WorkflowRevisionModel.workflow_key)
            & (WorkflowDefinitionModel.current_revision_no == WorkflowRevisionModel.revision_no),
        )
        .where(WorkflowDefinitionModel.workflow_key == workflow_id)
    )
    if row is None or row.provenance is None:
        raise WorkflowNotFoundError(f"published Workflow {workflow_id!r} does not exist")
    return WorkflowProvenance(row.provenance)


async def search_workflows(
    session: AsyncSession,
    *,
    query: str | None = None,
) -> tuple[WorkflowSummary, ...]:
    statement = (
        _target_revision_query()
        .join(
            WorkflowDefinitionModel,
            (WorkflowDefinitionModel.workflow_key == WorkflowRevisionModel.workflow_key)
            & (WorkflowDefinitionModel.current_revision_no == WorkflowRevisionModel.revision_no),
        )
        .order_by(WorkflowRevisionModel.workflow_key.asc())
    )
    rows = tuple((await session.scalars(statement)).all())
    normalized_query = query.casefold().strip() if query else None
    summaries: list[WorkflowSummary] = []
    for row in rows:
        if row.provenance is None:  # pragma: no cover - target query invariant
            raise RuntimeError("target Workflow revision has no provenance")
        published = _published_revision(row)
        if normalized_query and normalized_query not in (
            f"{published.workflow_id} {published.workflow.description}".casefold()
        ):
            continue
        summaries.append(
            WorkflowSummary(
                workflow_id=published.workflow_id,
                revision_no=published.revision_no,
                description=published.workflow.description,
                provenance=WorkflowProvenance(row.provenance),
            )
        )
    return tuple(summaries)


async def list_workflow_revisions(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> tuple[WorkflowRevisionSummary, ...]:
    rows = tuple(
        (
            await session.scalars(
                _target_revision_query()
                .where(WorkflowRevisionModel.workflow_key == workflow_id)
                .order_by(WorkflowRevisionModel.revision_no.desc())
            )
        ).all()
    )
    if not rows:
        raise WorkflowNotFoundError(f"published Workflow {workflow_id!r} does not exist")
    return tuple(
        WorkflowRevisionSummary(
            workflow_id=row.workflow_key,
            revision_no=row.revision_no,
            content_hash=row.content_hash,
            provenance=WorkflowProvenance(row.provenance),
        )
        for row in rows
        if row.provenance is not None
    )


def _published_revision(row: WorkflowRevisionModel) -> PublishedWorkflowRevision:
    if row.provenance is None:  # pragma: no cover - target query invariant
        raise RuntimeError("target Workflow revision has no provenance")
    workflow = NormalizedWorkflow.model_validate(row.content_json)
    return PublishedWorkflowRevision(
        workflow_id=row.workflow_key,
        revision_no=row.revision_no,
        content_hash=row.content_hash,
        workflow=workflow,
    )


def _target_revision_query() -> Select[tuple[WorkflowRevisionModel]]:
    return select(WorkflowRevisionModel).where(WorkflowRevisionModel.provenance.is_not(None))


__all__ = [
    "list_workflow_revisions",
    "read_current_published_workflow",
    "read_current_workflow_provenance",
    "read_published_workflow_revision",
    "search_workflows",
]
