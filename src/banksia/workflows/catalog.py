from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from banksia.persistence.models import (
    WorkflowDefinitionModel,
    WorkflowDraftModel,
    WorkflowRevisionModel,
)
from banksia.workflows.authoring_contracts import WorkflowDraftReadback
from banksia.workflows.contracts import (
    PublishedWorkflowRevision,
    WorkflowProvenance,
    WorkflowRevisionSummary,
    WorkflowSummary,
)
from banksia.workflows.integrity import (
    read_persisted_workflow,
    validate_persisted_workflow_identity,
)
from banksia.workflows.service_errors import WorkflowNotFoundError


class WorkflowSummaryPage(NamedTuple):
    items: tuple[WorkflowSummary, ...]
    next_workflow_id: str | None


class WorkflowRevisionSummaryPage(NamedTuple):
    items: tuple[WorkflowRevisionSummary, ...]
    next_revision_no: int | None


@dataclass(frozen=True, slots=True)
class WorkflowDraftSnapshot:
    workflow_id: str
    draft_id: str
    base_revision_no: int | None
    etag: str


@dataclass(frozen=True, slots=True)
class WorkflowCatalogSnapshot:
    summary: WorkflowSummary
    active_draft: WorkflowDraftSnapshot | None
    maximum_revision_no: int | None


@dataclass(frozen=True, slots=True)
class WorkflowDetailSnapshot:
    summary: WorkflowSummary
    selected_published_revision: PublishedWorkflowRevision | None
    active_draft: WorkflowDraftReadback | None
    maximum_revision_no: int | None


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
    read_persisted_workflow(
        row.content_json,
        expected_workflow_id=row.workflow_key,
        source="published Workflow",
    )
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
    normalized_query = (query or "").strip()
    rows = tuple(
        (
            await session.execute(
                _workflow_library_query(
                    query=normalized_query or None,
                    after_workflow_id=after_workflow_id,
                ).limit(limit + 1)
            )
        )
        .mappings()
        .all()
    )
    page_rows = rows[:limit]
    return WorkflowSummaryPage(
        items=tuple(_workflow_summary(row) for row in page_rows),
        next_workflow_id=str(page_rows[-1]["workflow_id"]) if len(rows) > limit else None,
    )


async def read_workflow_detail_snapshot(
    session: AsyncSession,
    *,
    workflow_id: str,
    revision_no: int | None = None,
) -> WorkflowDetailSnapshot:
    row = (
        (
            await session.execute(
                _workflow_detail_query(
                    workflow_id=workflow_id,
                    selected_revision_no=revision_no,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise WorkflowNotFoundError(f"Workflow {workflow_id!r} does not exist")
    snapshot = _workflow_detail_snapshot(row)
    if revision_no is not None and snapshot.selected_published_revision is None:
        raise WorkflowNotFoundError(
            f"published Workflow {workflow_id!r} revision {revision_no} does not exist"
        )
    return snapshot


async def read_workflow_catalog_snapshot(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> WorkflowCatalogSnapshot:
    row = (
        (
            await session.execute(
                _workflow_catalog_query(
                    workflow_id=workflow_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise WorkflowNotFoundError(f"Workflow {workflow_id!r} does not exist")
    return _workflow_catalog_snapshot(row)


async def list_workflow_revisions(
    session: AsyncSession,
    *,
    workflow_id: str,
    before_revision_no: int | None = None,
    maximum_revision_no: int | None = None,
    limit: int = 20,
) -> WorkflowRevisionSummaryPage:
    if not 1 <= limit <= 100:
        raise ValueError("Workflow revision limit must be between 1 and 100")
    statement = _workflow_revision_summary_query().where(
        WorkflowRevisionModel.workflow_key == workflow_id
    )
    if before_revision_no is not None:
        statement = statement.where(WorkflowRevisionModel.revision_no < before_revision_no)
    if maximum_revision_no is not None:
        statement = statement.where(WorkflowRevisionModel.revision_no <= maximum_revision_no)
    rows = tuple(
        (
            await session.execute(
                statement.order_by(WorkflowRevisionModel.revision_no.desc()).limit(limit + 1)
            )
        )
        .mappings()
        .all()
    )
    if not rows and before_revision_no is None:
        raise WorkflowNotFoundError(f"published Workflow {workflow_id!r} does not exist")
    page_rows = rows[:limit]
    for row in page_rows:
        validate_persisted_workflow_identity(
            row["content_workflow_id"],
            expected_workflow_id=row["workflow_id"],
            source="published Workflow revision",
        )
    return WorkflowRevisionSummaryPage(
        items=tuple(
            WorkflowRevisionSummary(
                workflow_id=row["workflow_id"],
                revision_no=row["revision_no"],
                content_hash=row["content_hash"],
                provenance=WorkflowProvenance(row["provenance"]),
            )
            for row in page_rows
        ),
        next_revision_no=page_rows[-1]["revision_no"] if len(rows) > limit else None,
    )


def _published_revision(row: WorkflowRevisionModel) -> PublishedWorkflowRevision:
    if row.provenance is None:  # pragma: no cover - target query invariant
        raise RuntimeError("target Workflow revision has no provenance")
    workflow = read_persisted_workflow(
        row.content_json,
        expected_workflow_id=row.workflow_key,
        source="published Workflow",
    )
    return PublishedWorkflowRevision(
        workflow_id=row.workflow_key,
        revision_no=row.revision_no,
        content_hash=row.content_hash,
        workflow=workflow,
    )


def _target_revision_query() -> Select[tuple[WorkflowRevisionModel]]:
    return select(WorkflowRevisionModel).where(WorkflowRevisionModel.provenance.is_not(None))


def _workflow_revision_summary_query() -> Select[Any]:
    return select(
        WorkflowRevisionModel.workflow_key.label("workflow_id"),
        WorkflowRevisionModel.revision_no.label("revision_no"),
        WorkflowRevisionModel.content_hash.label("content_hash"),
        WorkflowRevisionModel.provenance.label("provenance"),
        WorkflowRevisionModel.content_json["id"].as_string().label("content_workflow_id"),
    ).where(WorkflowRevisionModel.provenance.is_not(None))


def _workflow_library_query(
    *,
    query: str | None = None,
    after_workflow_id: str | None = None,
    workflow_id: str | None = None,
) -> Select[Any]:
    library_ids = _workflow_library_ids()
    draft_description = WorkflowDraftModel.content_json["description"].as_string()
    published_description = WorkflowRevisionModel.content_json["description"].as_string()
    current_description = func.coalesce(draft_description, published_description)
    visible_updated_at = _visible_workflow_updated_at()
    statement = (
        select(
            library_ids.c.workflow_id.label("workflow_id"),
            current_description.label("description"),
            visible_updated_at.label("updated_at"),
            WorkflowDefinitionModel.current_revision_no.label("published_revision_no"),
            WorkflowRevisionModel.provenance.label("published_provenance"),
            WorkflowDraftModel.draft_id.is_not(None).label("has_active_draft"),
            WorkflowDraftModel.content_json["id"].as_string().label("draft_content_workflow_id"),
            WorkflowRevisionModel.content_json["id"]
            .as_string()
            .label("published_content_workflow_id"),
        )
        .outerjoin(
            WorkflowDraftModel,
            WorkflowDraftModel.workflow_key == library_ids.c.workflow_id,
        )
        .outerjoin(
            WorkflowDefinitionModel,
            WorkflowDefinitionModel.workflow_key == library_ids.c.workflow_id,
        )
        .outerjoin(
            WorkflowRevisionModel,
            (WorkflowRevisionModel.workflow_key == WorkflowDefinitionModel.workflow_key)
            & (WorkflowRevisionModel.revision_no == WorkflowDefinitionModel.current_revision_no),
        )
        .order_by(library_ids.c.workflow_id.asc())
    )
    if query is not None:
        statement = statement.where(
            or_(
                library_ids.c.workflow_id.icontains(query, autoescape=True),
                current_description.icontains(query, autoescape=True),
            )
        )
    if after_workflow_id is not None:
        statement = statement.where(library_ids.c.workflow_id > after_workflow_id)
    if workflow_id is not None:
        statement = statement.where(library_ids.c.workflow_id == workflow_id)
    return statement


def _workflow_catalog_query(*, workflow_id: str) -> Select[Any]:
    history_revision = aliased(
        WorkflowRevisionModel,
        name="workflow_catalog_history_revision",
    )
    maximum_revision_no = (
        select(func.max(history_revision.revision_no))
        .where(
            history_revision.workflow_key == workflow_id,
            history_revision.provenance.is_not(None),
        )
        .scalar_subquery()
    )
    return _workflow_library_query(workflow_id=workflow_id).add_columns(
        WorkflowDraftModel.draft_id.label("draft_id"),
        WorkflowDraftModel.base_revision_no.label("draft_base_revision_no"),
        WorkflowDraftModel.etag.label("draft_etag"),
        maximum_revision_no.label("maximum_revision_no"),
    )


def _workflow_detail_query(
    *,
    workflow_id: str,
    selected_revision_no: int | None,
) -> Select[Any]:
    library_ids = _workflow_library_ids()
    current_revision = aliased(
        WorkflowRevisionModel,
        name="workflow_detail_current_revision",
    )
    selected_revision = aliased(
        WorkflowRevisionModel,
        name="workflow_detail_selected_revision",
    )
    history_revision = aliased(
        WorkflowRevisionModel,
        name="workflow_detail_history_revision",
    )
    draft_description = WorkflowDraftModel.content_json["description"].as_string()
    published_description = current_revision.content_json["description"].as_string()
    current_description = func.coalesce(draft_description, published_description)
    visible_updated_at = _visible_workflow_updated_at()
    maximum_revision_no = (
        select(func.max(history_revision.revision_no))
        .where(
            history_revision.workflow_key == library_ids.c.workflow_id,
            history_revision.provenance.is_not(None),
        )
        .scalar_subquery()
    )
    selected_revision_target = (
        selected_revision_no
        if selected_revision_no is not None
        else WorkflowDefinitionModel.current_revision_no
    )
    return (
        select(
            library_ids.c.workflow_id.label("workflow_id"),
            current_description.label("description"),
            visible_updated_at.label("updated_at"),
            WorkflowDefinitionModel.current_revision_no.label("published_revision_no"),
            current_revision.provenance.label("published_provenance"),
            WorkflowDraftModel.draft_id.is_not(None).label("has_active_draft"),
            WorkflowDraftModel.content_json["id"].as_string().label("draft_content_workflow_id"),
            current_revision.content_json["id"].as_string().label("published_content_workflow_id"),
            WorkflowDraftModel.draft_id.label("draft_id"),
            WorkflowDraftModel.base_revision_no.label("draft_base_revision_no"),
            WorkflowDraftModel.etag.label("draft_etag"),
            WorkflowDraftModel.content_json.label("draft_content_json"),
            selected_revision.revision_no.label("selected_revision_no"),
            selected_revision.content_hash.label("selected_content_hash"),
            selected_revision.content_json.label("selected_content_json"),
            maximum_revision_no.label("maximum_revision_no"),
        )
        .outerjoin(
            WorkflowDraftModel,
            WorkflowDraftModel.workflow_key == library_ids.c.workflow_id,
        )
        .outerjoin(
            WorkflowDefinitionModel,
            WorkflowDefinitionModel.workflow_key == library_ids.c.workflow_id,
        )
        .outerjoin(
            current_revision,
            (current_revision.workflow_key == WorkflowDefinitionModel.workflow_key)
            & (current_revision.revision_no == WorkflowDefinitionModel.current_revision_no)
            & current_revision.provenance.is_not(None),
        )
        .outerjoin(
            selected_revision,
            (selected_revision.workflow_key == library_ids.c.workflow_id)
            & (selected_revision.revision_no == selected_revision_target)
            & selected_revision.provenance.is_not(None),
        )
        .where(library_ids.c.workflow_id == workflow_id)
    )


def _workflow_library_ids() -> Subquery:
    active_draft_ids = select(WorkflowDraftModel.workflow_key.label("workflow_id"))
    current_published_ids = select(WorkflowDefinitionModel.workflow_key.label("workflow_id")).where(
        WorkflowDefinitionModel.current_revision_no.is_not(None)
    )
    return active_draft_ids.union(current_published_ids).subquery("workflow_library_ids")


def _visible_workflow_updated_at() -> ColumnElement[datetime]:
    draft_updated_at = WorkflowDraftModel.updated_at
    workflow_updated_at = WorkflowDefinitionModel.updated_at
    return case(
        (draft_updated_at.is_(None), workflow_updated_at),
        (workflow_updated_at.is_(None), draft_updated_at),
        (draft_updated_at >= workflow_updated_at, draft_updated_at),
        else_=workflow_updated_at,
    )


def _workflow_detail_snapshot(row: RowMapping) -> WorkflowDetailSnapshot:
    summary = _workflow_summary(row)
    draft_id = row["draft_id"]
    if draft_id is None:
        active_draft = None
    else:
        draft_etag = row["draft_etag"]
        draft_content = row["draft_content_json"]
        if not isinstance(draft_id, str) or not isinstance(draft_etag, str):
            raise RuntimeError(f"Workflow {summary.workflow_id!r} has an invalid active draft")
        active_draft = WorkflowDraftReadback(
            draft_id=draft_id,
            workflow_id=summary.workflow_id,
            base_revision_no=row["draft_base_revision_no"],
            etag=draft_etag,
            workflow=read_persisted_workflow(
                draft_content,
                expected_workflow_id=summary.workflow_id,
                source="Workflow draft",
            ),
        )

    selected_revision_no = row["selected_revision_no"]
    if selected_revision_no is None:
        selected_published_revision = None
    else:
        selected_content_hash = row["selected_content_hash"]
        if not isinstance(selected_revision_no, int) or not isinstance(
            selected_content_hash,
            str,
        ):
            raise RuntimeError(
                f"Workflow {summary.workflow_id!r} has an invalid selected publication"
            )
        selected_published_revision = PublishedWorkflowRevision(
            workflow_id=summary.workflow_id,
            revision_no=selected_revision_no,
            content_hash=selected_content_hash,
            workflow=read_persisted_workflow(
                row["selected_content_json"],
                expected_workflow_id=summary.workflow_id,
                source="published Workflow",
            ),
        )

    maximum_revision_no = row["maximum_revision_no"]
    if maximum_revision_no is not None and not isinstance(maximum_revision_no, int):
        raise RuntimeError(f"Workflow {summary.workflow_id!r} has invalid revision history")
    return WorkflowDetailSnapshot(
        summary=summary,
        selected_published_revision=selected_published_revision,
        active_draft=active_draft,
        maximum_revision_no=maximum_revision_no,
    )


def _workflow_catalog_snapshot(row: RowMapping) -> WorkflowCatalogSnapshot:
    summary = _workflow_summary(row)
    draft_id = row["draft_id"]
    if draft_id is None:
        active_draft = None
    else:
        draft_etag = row["draft_etag"]
        if not isinstance(draft_id, str) or not isinstance(draft_etag, str):
            raise RuntimeError(f"Workflow {summary.workflow_id!r} has an invalid active draft")
        active_draft = WorkflowDraftSnapshot(
            workflow_id=summary.workflow_id,
            draft_id=draft_id,
            base_revision_no=row["draft_base_revision_no"],
            etag=draft_etag,
        )

    maximum_revision_no = row["maximum_revision_no"]
    if maximum_revision_no is not None and not isinstance(maximum_revision_no, int):
        raise RuntimeError(f"Workflow {summary.workflow_id!r} has invalid revision history")
    return WorkflowCatalogSnapshot(
        summary=summary,
        active_draft=active_draft,
        maximum_revision_no=maximum_revision_no,
    )


def _workflow_summary(row: RowMapping) -> WorkflowSummary:
    workflow_id = row["workflow_id"]
    description = row["description"]
    updated_at = row["updated_at"]
    published_revision_no = row["published_revision_no"]
    published_provenance = row["published_provenance"]
    if not isinstance(workflow_id, str) or not isinstance(description, str):
        raise RuntimeError("Workflow library row has invalid identity or description")
    if not isinstance(updated_at, datetime):
        raise RuntimeError(f"Workflow {workflow_id!r} has no controller update time")
    if published_revision_no is not None and not isinstance(published_revision_no, int):
        raise RuntimeError(f"Workflow {workflow_id!r} has an invalid current revision")
    has_active_draft = bool(row["has_active_draft"])
    if has_active_draft:
        validate_persisted_workflow_identity(
            row["draft_content_workflow_id"],
            expected_workflow_id=workflow_id,
            source="Workflow draft",
        )
    if published_revision_no is not None:
        validate_persisted_workflow_identity(
            row["published_content_workflow_id"],
            expected_workflow_id=workflow_id,
            source="published Workflow",
        )
    if published_revision_no is None:
        provenance = WorkflowProvenance.USER
    elif isinstance(published_provenance, str):
        provenance = WorkflowProvenance(published_provenance)
    else:  # pragma: no cover - current publication invariant
        raise RuntimeError(f"Workflow {workflow_id!r} has no current provenance")
    return WorkflowSummary(
        workflow_id=workflow_id,
        description=description,
        updated_at=updated_at,
        provenance=provenance,
        published_revision_no=published_revision_no,
        has_active_draft=has_active_draft,
    )


__all__ = [
    "WorkflowCatalogSnapshot",
    "WorkflowDetailSnapshot",
    "WorkflowDraftSnapshot",
    "WorkflowRevisionSummaryPage",
    "WorkflowSummaryPage",
    "list_workflow_revisions",
    "read_current_published_workflow",
    "read_current_workflow_provenance",
    "read_published_workflow_revision",
    "read_workflow_catalog_snapshot",
    "read_workflow_detail_snapshot",
    "search_workflows",
]
