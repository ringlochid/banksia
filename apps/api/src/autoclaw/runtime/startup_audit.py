from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    AssignmentModel,
    AttemptModel,
    FlowModel,
    FlowNodeModel,
    TransientLocalizationModel,
)
from autoclaw.runtime.projection.signals import (
    ArtifactProjection,
    AttemptAssignmentProjection,
    CriteriaProjection,
    LatestCheckpointProjection,
    SupportProjectionSignal,
    TransientProjection,
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


@dataclass(frozen=True, order=True, slots=True)
class CriteriaProjectionCursor:
    flow_node_id: str
    criterion_index: int


type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type SupportProjectionPublish = Callable[[SupportProjectionSignal], Awaitable[bool]]


async def audit_startup_support_projections(
    *,
    session_factory: AsyncSessionContextFactory,
    publish: SupportProjectionPublish,
) -> dict[str, int]:
    """Page every durable support source and republish its exact typed variant."""

    async def route(signal: SupportProjectionSignal) -> None:
        if not await publish(signal):
            raise StartupAuditRoutingError(
                f"startup audit could not publish {type(signal).__name__}"
            )

    families: tuple[
        tuple[
            str,
            Callable[
                [object | None, int],
                Awaitable[StartupAuditPage[SupportProjectionSignal, object]],
            ],
        ],
        ...,
    ] = (
        (
            "workflow_manifest_projection",
            lambda cursor, size: _fetch_workflow_projection_page(
                session_factory,
                _string_cursor(cursor),
                size,
            ),
        ),
        (
            "criteria_projection",
            lambda cursor, size: _fetch_criteria_projection_page(
                session_factory,
                _criteria_cursor(cursor),
                size,
            ),
        ),
        (
            "attempt_assignment_projection",
            lambda cursor, size: _fetch_assignment_projection_page(
                session_factory,
                _string_cursor(cursor),
                size,
            ),
        ),
        (
            "latest_checkpoint_projection",
            lambda cursor, size: _fetch_checkpoint_projection_page(
                session_factory,
                _string_cursor(cursor),
                size,
            ),
        ),
        (
            "artifact_projection",
            lambda cursor, size: _fetch_artifact_projection_page(
                session_factory,
                _string_cursor(cursor),
                size,
            ),
        ),
        (
            "transient_projection",
            lambda cursor, size: _fetch_transient_projection_page(
                session_factory,
                _string_cursor(cursor),
                size,
            ),
        ),
    )
    counts: dict[str, int] = {}
    for family_name, fetch_page in families:
        counts[family_name] = await audit_startup_source_family(
            family_name=family_name,
            fetch_page=fetch_page,
            route_source=route,
            cursor_advances=_support_cursor_advances,
        )
    return counts


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
    """Page one source family and route each exact row through its handler.

    ``cursor_advances`` receives the previous cursor followed by the candidate
    next cursor.
    """

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
        if cursor is not None and next_cursor is not None:
            if not cursor_advances(cursor, next_cursor):
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
) -> StartupAuditPage[SupportProjectionSignal, object]:
    async with session_factory() as session:
        statement = (
            select(FlowModel)
            .where(FlowModel.active_flow_revision_id.is_not(None))
            .order_by(FlowModel.flow_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(FlowModel.flow_id > cursor)
        rows = tuple((await session.scalars(statement)).all())
    signals = tuple(
        WorkflowManifestProjection(row.flow_id, row.active_flow_revision_id)
        for row in rows
        if row.active_flow_revision_id is not None
    )
    return StartupAuditPage(signals, rows[-1].flow_id if len(rows) == page_size else None)


async def _fetch_criteria_projection_page(
    session_factory: AsyncSessionContextFactory,
    cursor: CriteriaProjectionCursor | None,
    page_size: int,
) -> StartupAuditPage[SupportProjectionSignal, object]:
    signals: list[SupportProjectionSignal] = []
    scan_after_node_id: str | None = None
    resume_cursor = cursor
    while len(signals) < page_size:
        async with session_factory() as session:
            statement = (
                select(FlowNodeModel)
                .join(FlowModel, FlowModel.flow_id == FlowNodeModel.flow_id)
                .where(FlowModel.active_flow_revision_id == FlowNodeModel.flow_revision_id)
                .order_by(FlowNodeModel.flow_node_id)
                .limit(page_size)
            )
            if resume_cursor is not None:
                statement = statement.where(
                    FlowNodeModel.flow_node_id >= resume_cursor.flow_node_id
                )
            elif scan_after_node_id is not None:
                statement = statement.where(FlowNodeModel.flow_node_id > scan_after_node_id)
            rows = tuple((await session.scalars(statement)).all())
        if not rows:
            return StartupAuditPage(tuple(signals), None)
        for node in rows:
            first_index = (
                resume_cursor.criterion_index + 1
                if resume_cursor is not None and node.flow_node_id == resume_cursor.flow_node_id
                else 0
            )
            for criterion_index, value in enumerate(
                node.criteria_json[first_index:],
                start=first_index,
            ):
                signal = _criteria_signal(node, value)
                signals.append(signal)
                if len(signals) == page_size:
                    return StartupAuditPage(
                        tuple(signals),
                        CriteriaProjectionCursor(node.flow_node_id, criterion_index),
                    )
        scan_after_node_id = rows[-1].flow_node_id
        resume_cursor = None
        if len(rows) < page_size:
            return StartupAuditPage(tuple(signals), None)
    raise AssertionError("criteria projection page loop must return")


async def _fetch_assignment_projection_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[SupportProjectionSignal, object]:
    async with session_factory() as session:
        statement = (
            select(AttemptModel, AssignmentModel)
            .join(AssignmentModel, AssignmentModel.assignment_id == AttemptModel.assignment_id)
            .order_by(AttemptModel.attempt_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(AttemptModel.attempt_id > cursor)
        rows = tuple((await session.execute(statement)).all())
    signals = tuple(
        AttemptAssignmentProjection(
            assignment.assignment_id,
            attempt.attempt_id,
            assignment.flow_revision_id,
        )
        for attempt, assignment in rows
    )
    return StartupAuditPage(
        signals,
        rows[-1][0].attempt_id if len(rows) == page_size else None,
    )


async def _fetch_checkpoint_projection_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[SupportProjectionSignal, object]:
    async with session_factory() as session:
        statement = (
            select(AttemptModel)
            .where(AttemptModel.latest_checkpoint_id.is_not(None))
            .order_by(AttemptModel.attempt_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(AttemptModel.attempt_id > cursor)
        rows = tuple((await session.scalars(statement)).all())
    signals = tuple(
        LatestCheckpointProjection(row.attempt_id, row.latest_checkpoint_id)
        for row in rows
        if row.latest_checkpoint_id is not None
    )
    return StartupAuditPage(signals, rows[-1].attempt_id if len(rows) == page_size else None)


async def _fetch_artifact_projection_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[SupportProjectionSignal, object]:
    async with session_factory() as session:
        statement = (
            select(ArtifactCurrentPointerModel)
            .order_by(ArtifactCurrentPointerModel.artifact_current_pointer_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(
                ArtifactCurrentPointerModel.artifact_current_pointer_id > cursor
            )
        rows = tuple((await session.scalars(statement)).all())
    signals = tuple(
        ArtifactProjection(row.current_publication_id, row.current_version) for row in rows
    )
    return StartupAuditPage(
        signals,
        rows[-1].artifact_current_pointer_id if len(rows) == page_size else None,
    )


async def _fetch_transient_projection_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[SupportProjectionSignal, object]:
    async with session_factory() as session:
        statement = (
            select(TransientLocalizationModel)
            .order_by(TransientLocalizationModel.transient_localization_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(
                TransientLocalizationModel.transient_localization_id > cursor
            )
        rows = tuple((await session.scalars(statement)).all())
    signals = tuple(TransientProjection(row.transient_localization_id) for row in rows)
    return StartupAuditPage(
        signals,
        rows[-1].transient_localization_id if len(rows) == page_size else None,
    )


def _criteria_signal(
    node: FlowNodeModel,
    value: dict[str, object],
) -> CriteriaProjection:
    owner_node_key = value.get("owner_node_key")
    slot = value.get("slot")
    version = value.get("version")
    if not isinstance(owner_node_key, str) or not isinstance(slot, str):
        raise StartupAuditPaginationError("criteria source is missing its exact owner or slot")
    if not isinstance(version, int) or version < 1:
        raise StartupAuditPaginationError("criteria source is missing its positive version")
    return CriteriaProjection(
        flow_revision_id=node.flow_revision_id,
        owner_node_key=owner_node_key,
        slot=slot,
        version=version,
    )


def _string_cursor(value: object | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise TypeError("startup audit cursor is not a string")


def _criteria_cursor(value: object | None) -> CriteriaProjectionCursor | None:
    if value is None or isinstance(value, CriteriaProjectionCursor):
        return value
    raise TypeError("startup criteria cursor has the wrong type")


def _support_cursor_advances(previous: object, candidate: object) -> bool:
    if isinstance(previous, str) and isinstance(candidate, str):
        return candidate > previous
    if isinstance(previous, CriteriaProjectionCursor) and isinstance(
        candidate,
        CriteriaProjectionCursor,
    ):
        return candidate > previous
    raise TypeError("startup support cursor types do not match")


__all__ = [
    "STARTUP_AUDIT_PAGE_GUARD",
    "STARTUP_AUDIT_PAGE_SIZE",
    "StartupAuditPage",
    "StartupAuditPaginationError",
    "StartupAuditRoutingError",
    "audit_startup_source_family",
    "audit_startup_support_projections",
]
