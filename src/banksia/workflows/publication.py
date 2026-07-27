from __future__ import annotations

from typing import cast

from sqlalchemy import Table, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import WorkflowDefinitionModel, WorkflowRevisionModel
from banksia.workflows.canonical import canonical_workflow_hash
from banksia.workflows.catalog import read_published_workflow_revision
from banksia.workflows.contracts import (
    NormalizedWorkflow,
    PublishedWorkflowRevision,
    WorkflowProvenance,
)

_MAX_COLLISION_RETRIES = 8


async def publish_workflow_revision(
    session: AsyncSession,
    *,
    workflow: NormalizedWorkflow,
    provenance: WorkflowProvenance,
    should_update_current: bool,
    source_path: str | None = None,
    current_provenance_guard: WorkflowProvenance | None = None,
) -> PublishedWorkflowRevision:
    content_hash = canonical_workflow_hash(workflow)
    owner = await acquire_workflow_owner(session, workflow_id=workflow.id)
    should_select_revision = await _should_select_revision(
        session,
        owner=owner,
        requested=should_update_current,
        current_provenance_guard=current_provenance_guard,
    )
    matching = await _matching_revision(
        session,
        workflow_id=workflow.id,
        content_hash=content_hash,
        provenance=provenance,
    )
    if matching is not None:
        if should_select_revision:
            await _set_current(session, workflow_id=workflow.id, revision_no=matching.revision_no)
        return await read_published_workflow_revision(
            session,
            workflow_id=workflow.id,
            revision_no=matching.revision_no,
        )

    for _attempt in range(_MAX_COLLISION_RETRIES):
        revision_no = await _next_revision_no(session, workflow_id=workflow.id)
        try:
            async with session.begin_nested():
                session.add(
                    WorkflowRevisionModel(
                        workflow_revision_id=_workflow_revision_id(workflow.id, revision_no),
                        workflow_key=workflow.id,
                        revision_no=revision_no,
                        content_hash=content_hash,
                        content_json=workflow.model_dump(mode="json", exclude_none=True),
                        provenance=provenance.value,
                        source_path=source_path,
                    )
                )
                await session.flush()
        except IntegrityError:
            matching = await _matching_revision(
                session,
                workflow_id=workflow.id,
                content_hash=content_hash,
                provenance=provenance,
            )
            if matching is None:
                continue
            revision_no = matching.revision_no
        if should_select_revision:
            await _set_current(session, workflow_id=workflow.id, revision_no=revision_no)
        return await read_published_workflow_revision(
            session,
            workflow_id=workflow.id,
            revision_no=revision_no,
        )
    raise RuntimeError(f"could not allocate an immutable revision for Workflow {workflow.id!r}")


async def acquire_workflow_owner(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> WorkflowDefinitionModel:
    if session.get_bind().dialect.name == "sqlite":
        table = cast(Table, WorkflowDefinitionModel.__table__)
        await session.execute(
            update(table)
            .where(table.c.workflow_key == workflow_id)
            .values(workflow_key=table.c.workflow_key, updated_at=table.c.updated_at)
        )
    existing: WorkflowDefinitionModel | None = await session.scalar(
        select(WorkflowDefinitionModel)
        .where(WorkflowDefinitionModel.workflow_key == workflow_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        return existing
    created = WorkflowDefinitionModel(workflow_key=workflow_id)
    try:
        async with session.begin_nested():
            session.add(created)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(WorkflowDefinitionModel)
            .where(WorkflowDefinitionModel.workflow_key == workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing is None:
            raise
        return existing
    return created


async def _should_select_revision(
    session: AsyncSession,
    *,
    owner: WorkflowDefinitionModel,
    requested: bool,
    current_provenance_guard: WorkflowProvenance | None,
) -> bool:
    if not requested or current_provenance_guard is None:
        return requested
    if owner.current_revision_no is None:
        existing_revision = await session.scalar(
            select(WorkflowRevisionModel.revision_no)
            .where(WorkflowRevisionModel.workflow_key == owner.workflow_key)
            .limit(1)
        )
        return existing_revision is None
    current_provenance = await session.scalar(
        select(WorkflowRevisionModel.provenance).where(
            WorkflowRevisionModel.workflow_key == owner.workflow_key,
            WorkflowRevisionModel.revision_no == owner.current_revision_no,
        )
    )
    if current_provenance is None:
        raise RuntimeError(
            f"Workflow {owner.workflow_key!r} current revision has no publication provenance"
        )
    return current_provenance == current_provenance_guard.value


async def _matching_revision(
    session: AsyncSession,
    *,
    workflow_id: str,
    content_hash: str,
    provenance: WorkflowProvenance,
) -> WorkflowRevisionModel | None:
    return cast(
        WorkflowRevisionModel | None,
        await session.scalar(
            select(WorkflowRevisionModel).where(
                WorkflowRevisionModel.workflow_key == workflow_id,
                WorkflowRevisionModel.content_hash == content_hash,
                WorkflowRevisionModel.provenance == provenance.value,
            )
        ),
    )


def _workflow_revision_id(workflow_id: str, revision_no: int) -> str:
    return f"workflow-revision.{workflow_id}.{revision_no:03d}"


async def _next_revision_no(session: AsyncSession, *, workflow_id: str) -> int:
    current_max = await session.scalar(
        select(func.max(WorkflowRevisionModel.revision_no)).where(
            WorkflowRevisionModel.workflow_key == workflow_id
        )
    )
    return int(current_max or 0) + 1


async def _set_current(
    session: AsyncSession,
    *,
    workflow_id: str,
    revision_no: int,
) -> None:
    await session.execute(
        update(WorkflowDefinitionModel)
        .where(WorkflowDefinitionModel.workflow_key == workflow_id)
        .values(current_revision_no=revision_no)
    )


__all__ = ["acquire_workflow_owner", "publish_workflow_revision"]
