from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import Select, func, or_, select
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


class WorkflowSummaryPage(NamedTuple):
    items: tuple[WorkflowSummary, ...]
    next_workflow_id: str | None


class WorkflowRevisionSummaryPage(NamedTuple):
    items: tuple[WorkflowRevisionSummary, ...]
    next_revision_no: int | None


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
    after_workflow_id: str | None = None,
    limit: int = 50,
) -> WorkflowSummaryPage:
    if not 1 <= limit <= 100:
        raise ValueError("Workflow search limit must be between 1 and 100")
    description = WorkflowRevisionModel.content_json["description"].as_string()
    statement = (
        _target_revision_query()
        .join(
            WorkflowDefinitionModel,
            (WorkflowDefinitionModel.workflow_key == WorkflowRevisionModel.workflow_key)
            & (WorkflowDefinitionModel.current_revision_no == WorkflowRevisionModel.revision_no),
        )
        .order_by(WorkflowRevisionModel.workflow_key.asc())
        .limit(limit + 1)
    )
    normalized_query = (query or "").casefold().strip()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                func.lower(WorkflowRevisionModel.workflow_key).like(pattern),
                func.lower(description).like(pattern),
            )
        )
    if after_workflow_id is not None:
        statement = statement.where(WorkflowRevisionModel.workflow_key > after_workflow_id)
    rows = tuple((await session.scalars(statement)).all())
    page_rows = rows[:limit]
    summaries: list[WorkflowSummary] = []
    for row in page_rows:
        if row.provenance is None:  # pragma: no cover - target query invariant
            raise RuntimeError("target Workflow revision has no provenance")
        published = _published_revision(row)
        summaries.append(
            WorkflowSummary(
                workflow_id=published.workflow_id,
                revision_no=published.revision_no,
                description=published.workflow.description,
                provenance=WorkflowProvenance(row.provenance),
            )
        )
    return WorkflowSummaryPage(
        items=tuple(summaries),
        next_workflow_id=page_rows[-1].workflow_key if len(rows) > limit else None,
    )


async def list_workflow_revisions(
    session: AsyncSession,
    *,
    workflow_id: str,
    before_revision_no: int | None = None,
    limit: int = 20,
) -> WorkflowRevisionSummaryPage:
    if not 1 <= limit <= 100:
        raise ValueError("Workflow revision limit must be between 1 and 100")
    statement = _target_revision_query().where(WorkflowRevisionModel.workflow_key == workflow_id)
    if before_revision_no is not None:
        statement = statement.where(WorkflowRevisionModel.revision_no < before_revision_no)
    rows = tuple(
        (
            await session.scalars(
                statement.order_by(WorkflowRevisionModel.revision_no.desc()).limit(limit + 1)
            )
        ).all()
    )
    if not rows and before_revision_no is None:
        raise WorkflowNotFoundError(f"published Workflow {workflow_id!r} does not exist")
    page_rows = rows[:limit]
    return WorkflowRevisionSummaryPage(
        items=tuple(
            WorkflowRevisionSummary(
                workflow_id=row.workflow_key,
                revision_no=row.revision_no,
                content_hash=row.content_hash,
                provenance=WorkflowProvenance(row.provenance),
            )
            for row in page_rows
            if row.provenance is not None
        ),
        next_revision_no=page_rows[-1].revision_no if len(rows) > limit else None,
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
    "WorkflowRevisionSummaryPage",
    "WorkflowSummaryPage",
    "list_workflow_revisions",
    "read_current_published_workflow",
    "read_current_workflow_provenance",
    "read_published_workflow_revision",
    "search_workflows",
]
