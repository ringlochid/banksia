from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import FlowModel
from banksia.runtime.projection.signals import (
    SupportProjectionSignal,
    WorkflowManifestProjection,
)

STARTUP_AUDIT_PAGE_SIZE = 200
STARTUP_AUDIT_PAGE_GUARD = 10_000


class StartupAuditPaginationError(RuntimeError):
    """The finite startup audit cannot prove that indexed paging is progressing."""


@dataclass(frozen=True)
class StartupAuditPage[SourceT, CursorT]:
    """One bounded page of exact recoverable source rows."""

    sources: tuple[SourceT, ...]
    next_cursor: CursorT | None


class StartupAuditRoutingError(RuntimeError):
    """The finite startup audit could not publish one discovered exact source."""


type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type SupportProjectionPublish = Callable[[SupportProjectionSignal], Awaitable[bool]]


async def audit_startup_support_projections(
    *,
    session_factory: AsyncSessionContextFactory,
    publish: SupportProjectionPublish,
) -> dict[str, int]:
    """Republish every retained Workflow manifest projection."""

    async def route(signal: SupportProjectionSignal) -> None:
        if not await publish(signal):
            raise StartupAuditRoutingError(
                f"startup audit could not publish {type(signal).__name__}"
            )

    count = await audit_startup_source_family(
        family_name="workflow_manifest_projection",
        fetch_page=lambda cursor, size: _fetch_workflow_projection_page(
            session_factory,
            cursor,
            size,
        ),
        route_source=route,
        cursor_advances=lambda previous, candidate: candidate > previous,
    )
    return {"workflow_manifest_projection": count}


async def audit_startup_source_family[SourceT, CursorT](
    *,
    family_name: str,
    fetch_page: Callable[
        [CursorT | None, int],
        Awaitable[StartupAuditPage[SourceT, CursorT]],
    ],
    route_source: Callable[[SourceT], Awaitable[None]],
    cursor_advances: Callable[[CursorT, CursorT], bool],
) -> int:
    """Page one source family and route each exact row through its handler."""

    cursor: CursorT | None = None
    pages_read = 0
    sources_routed = 0

    while True:
        page = await fetch_page(cursor, STARTUP_AUDIT_PAGE_SIZE)
        pages_read += 1
        if pages_read >= STARTUP_AUDIT_PAGE_GUARD:
            raise StartupAuditPaginationError(
                f"startup audit family {family_name!r} reached the "
                f"{STARTUP_AUDIT_PAGE_GUARD}-page bug guard"
            )
        if len(page.sources) > STARTUP_AUDIT_PAGE_SIZE:
            raise StartupAuditPaginationError(
                f"startup audit family {family_name!r} returned "
                f"{len(page.sources)} sources for a {STARTUP_AUDIT_PAGE_SIZE}-row page"
            )

        next_cursor = page.next_cursor
        if (
            cursor is not None
            and next_cursor is not None
            and not cursor_advances(cursor, next_cursor)
        ):
            raise StartupAuditPaginationError(
                f"startup audit family {family_name!r} returned a non-advancing cursor"
            )

        for source in page.sources:
            await route_source(source)
            sources_routed += 1

        if next_cursor is None:
            return sources_routed
        cursor = next_cursor


async def _fetch_workflow_projection_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[SupportProjectionSignal, str]:
    async with session_factory() as session:
        statement = (
            select(FlowModel)
            .where(FlowModel.active_flow_revision_id.is_not(None))
            .order_by(FlowModel.flow_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(FlowModel.flow_id > cursor)
        rows = tuple(await session.scalars(statement))
    signals = tuple(
        WorkflowManifestProjection(row.flow_id, row.active_flow_revision_id)
        for row in rows
        if row.active_flow_revision_id is not None
    )
    return StartupAuditPage(
        signals,
        rows[-1].flow_id if len(rows) == page_size else None,
    )


__all__ = [
    "STARTUP_AUDIT_PAGE_GUARD",
    "STARTUP_AUDIT_PAGE_SIZE",
    "StartupAuditPage",
    "StartupAuditPaginationError",
    "StartupAuditRoutingError",
    "audit_startup_source_family",
    "audit_startup_support_projections",
]
