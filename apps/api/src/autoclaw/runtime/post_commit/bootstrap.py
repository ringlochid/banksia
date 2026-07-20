from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    CommandRunModel,
    DispatchTurnModel,
    FlowModel,
    FlowStartSourceModel,
    HumanRequestModel,
    TransientLocalizationModel,
)
from autoclaw.persistence.models.runtime.common import COMMAND_RUN_TERMINAL_STATE_VALUES
from autoclaw.runtime.contracts import CommandRunState
from autoclaw.runtime.post_commit.signals import (
    BoundaryAccepted,
    CommandRunCancellationRequested,
    CommandRunPending,
    CommandRunTerminal,
    DispatchStartDue,
    FlowStartCommitted,
    HumanRequestOpened,
    HumanRequestTerminal,
    RuntimeEffectSignal,
    TransientCleanupRequested,
    WatchdogDeadlineChanged,
)
from autoclaw.runtime.startup_audit import (
    StartupAuditPage,
    StartupAuditPaginationError,
    StartupAuditRoutingError,
    audit_startup_source_family,
)
from autoclaw.runtime.watchdog.deadline import calculate_watchdog_due_at

type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type RuntimeEffectStartupPublish = Callable[[RuntimeEffectSignal], Awaitable[bool]]
type RuntimeEffectPageFetcher = Callable[
    [str | None, int],
    Awaitable[StartupAuditPage[RuntimeEffectSignal, str]],
]
type RuntimeEffectFamily = tuple[str, RuntimeEffectPageFetcher]

_HUMAN_REQUEST_TERMINAL_STATUSES = ("resolved", "timed_out", "cancelled")


@dataclass(frozen=True, slots=True)
class StartupRuntimeFamilyResult:
    """Discovered, routed, and deliberately deferred rows for one source family."""

    discovered_count: int
    routed_count: int
    deferred_count: int


async def audit_startup_runtime_effects(
    *,
    session_factory: AsyncSessionContextFactory,
    publish: RuntimeEffectStartupPublish,
    routed_signal_types: Collection[type[RuntimeEffectSignal]],
    watchdog_inactivity_timeout_seconds: int,
) -> dict[str, StartupRuntimeFamilyResult]:
    """Exhaust exact runtime pages and publish only routes with real handlers."""

    if watchdog_inactivity_timeout_seconds <= 0:
        raise ValueError("watchdog inactivity timeout must be positive")

    families = _startup_runtime_families(
        session_factory,
        watchdog_inactivity_timeout_seconds=watchdog_inactivity_timeout_seconds,
    )
    routable = frozenset(routed_signal_types)
    results: dict[str, StartupRuntimeFamilyResult] = {}
    for family_name, fetch_page in families:
        routed_count = 0
        deferred_count = 0

        async def route(signal: RuntimeEffectSignal) -> None:
            nonlocal routed_count, deferred_count
            if type(signal) not in routable:
                deferred_count += 1
                return
            if not await publish(signal):
                raise StartupAuditRoutingError(
                    f"startup audit could not publish {type(signal).__name__}"
                )
            routed_count += 1

        discovered_count = await audit_startup_source_family(
            family_name=family_name,
            fetch_page=fetch_page,
            route_source=route,
            cursor_advances=lambda previous, candidate: candidate > previous,
        )
        results[family_name] = StartupRuntimeFamilyResult(
            discovered_count=discovered_count,
            routed_count=routed_count,
            deferred_count=deferred_count,
        )
    return results


async def read_flow_start_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read runnable root sources that still have no committed root dispatch."""

    async with session_factory() as session:
        statement = (
            select(FlowStartSourceModel.flow_id)
            .join(FlowModel, FlowModel.flow_id == FlowStartSourceModel.flow_id)
            .where(
                FlowStartSourceModel.successor_dispatch_id.is_(None),
                FlowModel.status == "running",
                FlowModel.current_dispatch_id.is_(None),
                FlowModel.waiting_cause == "none",
            )
            .order_by(FlowStartSourceModel.flow_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(FlowStartSourceModel.flow_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return _runtime_signal_page(
        source_ids,
        page_size=page_size,
        build_signal=FlowStartCommitted,
    )


async def read_boundary_continuation_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read accepted boundaries that still have no committed successor."""

    async with session_factory() as session:
        statement = (
            select(AcceptedBoundaryModel.source_dispatch_id)
            .where(AcceptedBoundaryModel.successor_dispatch_id.is_(None))
            .order_by(AcceptedBoundaryModel.source_dispatch_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(AcceptedBoundaryModel.source_dispatch_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return _runtime_signal_page(
        source_ids,
        page_size=page_size,
        build_signal=BoundaryAccepted,
    )


async def read_human_continuation_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read terminal human sources that still have no committed successor."""

    async with session_factory() as session:
        statement = (
            select(HumanRequestModel.request_id)
            .where(
                HumanRequestModel.status.in_(_HUMAN_REQUEST_TERMINAL_STATUSES),
                HumanRequestModel.successor_dispatch_id.is_(None),
            )
            .order_by(HumanRequestModel.request_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(HumanRequestModel.request_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return _runtime_signal_page(
        source_ids,
        page_size=page_size,
        build_signal=HumanRequestTerminal,
    )


async def read_human_deadline_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read open human sources for exact deadline registration."""

    async with session_factory() as session:
        statement = (
            select(HumanRequestModel.request_id)
            .where(HumanRequestModel.status == "open")
            .order_by(HumanRequestModel.request_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(HumanRequestModel.request_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return _runtime_signal_page(
        source_ids,
        page_size=page_size,
        build_signal=HumanRequestOpened,
    )


async def read_command_continuation_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read terminal command sources that still have no committed successor."""

    async with session_factory() as session:
        statement = (
            select(CommandRunModel.run_id)
            .where(
                CommandRunModel.state.in_(COMMAND_RUN_TERMINAL_STATE_VALUES),
                CommandRunModel.successor_dispatch_id.is_(None),
            )
            .order_by(CommandRunModel.run_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(CommandRunModel.run_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return _runtime_signal_page(
        source_ids,
        page_size=page_size,
        build_signal=CommandRunTerminal,
    )


async def read_command_pending_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read unclaimed or ambiguously claimed pending command sources."""

    return await _read_command_state_page(
        session_factory,
        cursor,
        page_size,
        state=CommandRunState.PENDING_START,
    )


async def read_command_running_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read running commands for process-ownership loss recovery."""

    return await _read_command_state_page(
        session_factory,
        cursor,
        page_size,
        state=CommandRunState.RUNNING,
    )


async def read_command_cancellation_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read cancellation requests with their exact ownership generation."""

    async with session_factory() as session:
        statement = (
            select(CommandRunModel.run_id, CommandRunModel.ownership_revision)
            .where(CommandRunModel.state == CommandRunState.CANCELLATION_REQUESTED.value)
            .order_by(CommandRunModel.run_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(CommandRunModel.run_id > cursor)
        rows = tuple((await session.execute(statement)).all())
    return StartupAuditPage(
        tuple(
            CommandRunCancellationRequested(
                run_id=run_id,
                ownership_revision=ownership_revision,
            )
            for run_id, ownership_revision in rows
        ),
        rows[-1][0] if len(rows) == page_size else None,
    )


async def read_dispatch_start_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read exact current starting dispatches without consuming or replacing them."""

    async with session_factory() as session:
        statement = (
            select(
                DispatchTurnModel.dispatch_id,
                DispatchTurnModel.provider_start_revision,
                DispatchTurnModel.next_provider_start_at,
            )
            .join(
                FlowModel,
                (FlowModel.flow_id == DispatchTurnModel.flow_id)
                & (FlowModel.current_dispatch_id == DispatchTurnModel.dispatch_id),
            )
            .where(DispatchTurnModel.status == "starting")
            .order_by(DispatchTurnModel.dispatch_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(DispatchTurnModel.dispatch_id > cursor)
        rows = tuple((await session.execute(statement)).all())
    signals: list[RuntimeEffectSignal] = []
    for dispatch_id, provider_start_revision, due_at in rows:
        if due_at is None:
            raise StartupAuditPaginationError(
                f"current starting dispatch {dispatch_id!r} has no provider-start due time"
            )
        signals.append(DispatchStartDue(dispatch_id, provider_start_revision, due_at))
    return StartupAuditPage(
        tuple(signals),
        rows[-1][0] if len(rows) == page_size else None,
    )


async def read_transient_cleanup_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read exact inactive transient bodies that still need removal."""

    async with session_factory() as session:
        statement = (
            select(
                TransientLocalizationModel.transient_localization_id,
                TransientLocalizationModel.expires_at,
            )
            .where(TransientLocalizationModel.retention_status == "expired")
            .order_by(TransientLocalizationModel.transient_localization_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(
                TransientLocalizationModel.transient_localization_id > cursor
            )
        rows = tuple((await session.execute(statement)).all())
    signals: list[RuntimeEffectSignal] = []
    for transient_localization_id, expires_at in rows:
        if expires_at is None:
            raise StartupAuditPaginationError(
                f"expired transient {transient_localization_id!r} has no retention generation"
            )
        signals.append(
            TransientCleanupRequested(
                transient_localization_id=transient_localization_id,
                expires_at=expires_at,
            )
        )
    return StartupAuditPage(
        tuple(signals),
        rows[-1][0] if len(rows) == page_size else None,
    )


async def read_watchdog_deadline_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
    *,
    inactivity_timeout_seconds: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read current runnable open dispatches eligible for watchdog registration."""

    async with session_factory() as session:
        statement = (
            select(
                DispatchTurnModel.dispatch_id,
                DispatchTurnModel.node_activity_revision,
                DispatchTurnModel.adapter_started_at,
                DispatchTurnModel.last_node_activity_at,
            )
            .join(
                FlowModel,
                (FlowModel.flow_id == DispatchTurnModel.flow_id)
                & (FlowModel.current_dispatch_id == DispatchTurnModel.dispatch_id),
            )
            .where(
                DispatchTurnModel.status == "open",
                FlowModel.status == "running",
                FlowModel.waiting_cause == "none",
                ~exists().where(
                    HumanRequestModel.source_dispatch_id == DispatchTurnModel.dispatch_id
                ),
                ~exists().where(
                    CommandRunModel.source_dispatch_id == DispatchTurnModel.dispatch_id
                ),
            )
            .order_by(DispatchTurnModel.dispatch_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(DispatchTurnModel.dispatch_id > cursor)
        rows = tuple((await session.execute(statement)).all())

    signals: list[RuntimeEffectSignal] = []
    for dispatch_id, activity_revision, adapter_started_at, activity_at in rows:
        if adapter_started_at is None:
            raise StartupAuditPaginationError(
                f"current open dispatch {dispatch_id!r} has no adapter acceptance time"
            )
        due_at = calculate_watchdog_due_at(
            adapter_started_at=adapter_started_at,
            last_node_activity_at=activity_at,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
        )
        signals.append(
            WatchdogDeadlineChanged(
                dispatch_id=dispatch_id,
                activity_revision=activity_revision,
                due_at=due_at,
            )
        )
    return StartupAuditPage(
        tuple(signals),
        rows[-1][0] if len(rows) == page_size else None,
    )


def _startup_runtime_families(
    session_factory: AsyncSessionContextFactory,
    *,
    watchdog_inactivity_timeout_seconds: int,
) -> tuple[RuntimeEffectFamily, ...]:
    return (
        *_continuation_runtime_families(session_factory),
        *_command_runtime_families(session_factory),
        *_resource_runtime_families(
            session_factory,
            watchdog_inactivity_timeout_seconds=watchdog_inactivity_timeout_seconds,
        ),
    )


def _continuation_runtime_families(
    session_factory: AsyncSessionContextFactory,
) -> tuple[RuntimeEffectFamily, ...]:
    return (
        (
            "runnable_flow_start",
            lambda cursor, size: read_flow_start_page(session_factory, cursor, size),
        ),
        (
            "accepted_boundary",
            lambda cursor, size: read_boundary_continuation_page(session_factory, cursor, size),
        ),
        (
            "open_human_request",
            lambda cursor, size: read_human_deadline_page(session_factory, cursor, size),
        ),
        (
            "terminal_human_request",
            lambda cursor, size: read_human_continuation_page(session_factory, cursor, size),
        ),
    )


def _command_runtime_families(
    session_factory: AsyncSessionContextFactory,
) -> tuple[RuntimeEffectFamily, ...]:
    return (
        (
            "terminal_command_run",
            lambda cursor, size: read_command_continuation_page(session_factory, cursor, size),
        ),
        (
            "pending_command_run",
            lambda cursor, size: read_command_pending_page(session_factory, cursor, size),
        ),
        (
            "running_command_run",
            lambda cursor, size: read_command_running_page(session_factory, cursor, size),
        ),
        (
            "cancellation_requested_command_run",
            lambda cursor, size: read_command_cancellation_page(session_factory, cursor, size),
        ),
    )


def _resource_runtime_families(
    session_factory: AsyncSessionContextFactory,
    *,
    watchdog_inactivity_timeout_seconds: int,
) -> tuple[RuntimeEffectFamily, ...]:
    return (
        (
            "expired_transient_localization",
            lambda cursor, size: read_transient_cleanup_page(session_factory, cursor, size),
        ),
        (
            "current_starting_dispatch",
            lambda cursor, size: read_dispatch_start_page(session_factory, cursor, size),
        ),
        (
            "current_open_watchdog",
            lambda cursor, size: read_watchdog_deadline_page(
                session_factory,
                cursor,
                size,
                inactivity_timeout_seconds=watchdog_inactivity_timeout_seconds,
            ),
        ),
    )


async def _read_command_state_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
    *,
    state: CommandRunState,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    async with session_factory() as session:
        statement = (
            select(CommandRunModel.run_id)
            .where(CommandRunModel.state == state.value)
            .order_by(CommandRunModel.run_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(CommandRunModel.run_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return _runtime_signal_page(
        source_ids,
        page_size=page_size,
        build_signal=CommandRunPending,
    )


def _runtime_signal_page(
    source_ids: tuple[str, ...],
    *,
    page_size: int,
    build_signal: Callable[[str], RuntimeEffectSignal],
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    return StartupAuditPage(
        tuple(build_signal(source_id) for source_id in source_ids),
        source_ids[-1] if len(source_ids) == page_size else None,
    )


__all__ = [
    "StartupRuntimeFamilyResult",
    "audit_startup_runtime_effects",
    "read_boundary_continuation_page",
    "read_command_cancellation_page",
    "read_command_continuation_page",
    "read_command_pending_page",
    "read_command_running_page",
    "read_dispatch_start_page",
    "read_flow_start_page",
    "read_human_continuation_page",
    "read_human_deadline_page",
    "read_transient_cleanup_page",
    "read_watchdog_deadline_page",
]
