from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import DispatchTurnModel, TaskModel
from banksia.runtime.dispatch.opening import StartingDispatchBasis, stage_starting_dispatch
from banksia.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from banksia.runtime.dispatch.prompt_snapshot import build_ordinary_dispatch_request
from banksia.runtime.post_commit import (
    DispatchCleanupRequested,
    WatchdogDue,
)
from banksia.runtime.providers import ProviderResolutionError
from banksia.runtime.watchdog.context import (
    WatchdogRecoverySnapshot,
    read_watchdog_recovery_snapshot,
)
from banksia.runtime.watchdog.pause import (
    pause_failed_watchdog_signal,
    pause_watchdog_snapshot,
)
from banksia.runtime.watchdog.predicates import (
    dispatch_has_no_external_source,
    dispatch_has_no_successor,
    nullable_datetime_matches,
    watchdog_context_is_current,
    watchdog_replacement_count_matches,
)

type WatchdogDueHandler = Callable[[AsyncSession, WatchdogDue], Awaitable[None]]
type WatchdogRecoveryOutcome = Literal["opened", "skipped", "paused"]


@dataclass(frozen=True, slots=True)
class WatchdogRecoveryResult:
    outcome: WatchdogRecoveryOutcome
    dispatch_id: str | None = None


def create_watchdog_due_handler(
    dependencies: DispatchOpeningDependencies,
) -> WatchdogDueHandler:
    """Create the exact stale-dispatch recovery route."""

    async def handle(session: AsyncSession, signal: WatchdogDue) -> None:
        await recover_stale_dispatch(
            session,
            signal=signal,
            dependencies=dependencies,
        )

    return handle


async def recover_stale_dispatch(
    session: AsyncSession,
    *,
    signal: WatchdogDue,
    dependencies: DispatchOpeningDependencies,
) -> WatchdogRecoveryResult:
    """Conditionally replace one exact stale dispatch or pause on its recovery cap."""

    observed_at = dependencies.clock()
    candidate_dispatch_id = f"dispatch.{uuid4().hex}"
    timeout_seconds = dependencies.settings.runtime.watchdog_inactivity_timeout_seconds
    replacement_limit = dependencies.settings.runtime.watchdog_same_attempt_replacement_limit
    try:
        snapshot = await read_watchdog_recovery_snapshot(
            session,
            signal=signal,
            candidate_dispatch_id=candidate_dispatch_id,
            dependencies=dependencies,
            now=observed_at,
            inactivity_timeout_seconds=timeout_seconds,
        )
        if snapshot is None:
            await session.rollback()
            return WatchdogRecoveryResult(outcome="skipped")
        if snapshot.same_attempt_replacement_count >= replacement_limit:
            await session.rollback()
            closed_dispatch_ids = await pause_watchdog_snapshot(
                session,
                snapshot=snapshot,
                paused_at=dependencies.clock(),
                pause_reason="runtime_recovery_exhausted",
                failure_code=None,
            )
            if closed_dispatch_ids is None:
                return WatchdogRecoveryResult(outcome="skipped")
            _publish_cleanups(dependencies, closed_dispatch_ids)
            return WatchdogRecoveryResult(outcome="paused")

        request = build_ordinary_dispatch_request(snapshot.dispatch.prompt)
        await session.rollback()
        prepared = prepare_dispatch_request(
            dependencies=dependencies,
            dispatch_id=candidate_dispatch_id,
            due_at=dependencies.clock(),
            provider=snapshot.dispatch.provider,
            capabilities=snapshot.dispatch.capabilities,
            request=request,
        )
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        failure_code = str(getattr(exc, "code", "watchdog_dispatch_preparation_failed"))
        closed_dispatch_ids = await pause_failed_watchdog_signal(
            session,
            signal=signal,
            paused_at=dependencies.clock(),
            inactivity_timeout_seconds=timeout_seconds,
            failure_code=failure_code,
        )
        if closed_dispatch_ids is not None:
            _publish_cleanups(dependencies, closed_dispatch_ids)
            return WatchdogRecoveryResult(outcome="paused")
        return WatchdogRecoveryResult(outcome="skipped")

    committed = await _commit_watchdog_replacement(
        session,
        snapshot=snapshot,
        prepared=prepared,
        committed_at=dependencies.clock(),
    )
    if not committed:
        return WatchdogRecoveryResult(outcome="skipped")
    _publish_cleanup(dependencies, signal.dispatch_id)
    _publish_dispatch_start(dependencies, prepared)
    return WatchdogRecoveryResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def _commit_watchdog_replacement(
    session: AsyncSession,
    *,
    snapshot: WatchdogRecoverySnapshot,
    prepared: PreparedDispatchRequest,
    committed_at: datetime,
) -> bool:
    dispatch = snapshot.dispatch
    prompt = dispatch.prompt
    if _as_utc(committed_at) < snapshot.authoritative_due_at:
        await session.rollback()
        return False

    if not await _claim_watchdog_replacement_task(
        session,
        snapshot=snapshot,
    ):
        return False
    if not await _close_watchdog_source_dispatch(
        session,
        snapshot=snapshot,
        closed_at=committed_at,
    ):
        return False

    await stage_starting_dispatch(
        session,
        basis=StartingDispatchBasis(
            task_id=prompt.task_id,
            assignment_id=prompt.assignment_id,
            team_revision_id=prompt.team_revision_id,
            member_id=prompt.member_id,
            member_configuration_id=prompt.member_configuration_id,
            member_branch_basis_id=prompt.member_branch_basis_id,
            attempt_id=prompt.attempt_id,
            opened_reason="watchdog_recovery",
            predecessor_dispatch_id=prompt.predecessor_dispatch_id,
            task_start_source_task_id=None,
        ),
        prepared=prepared,
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return True


async def _close_watchdog_source_dispatch(
    session: AsyncSession,
    *,
    snapshot: WatchdogRecoverySnapshot,
    closed_at: datetime,
) -> bool:
    prompt = snapshot.dispatch.prompt
    closed_dispatch_id = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == prompt.predecessor_dispatch_id,
            DispatchTurnModel.task_id == prompt.task_id,
            DispatchTurnModel.assignment_id == prompt.assignment_id,
            DispatchTurnModel.attempt_id == prompt.attempt_id,
            DispatchTurnModel.team_revision_id == snapshot.source_team_revision_id,
            DispatchTurnModel.member_id == prompt.member_id,
            DispatchTurnModel.status == "open",
            DispatchTurnModel.adapter_started_at == snapshot.adapter_started_at,
            nullable_datetime_matches(
                DispatchTurnModel.last_node_activity_at,
                snapshot.last_node_activity_at,
            ),
            DispatchTurnModel.node_activity_revision == snapshot.activity_revision,
            watchdog_context_is_current(snapshot),
            watchdog_replacement_count_matches(snapshot),
            dispatch_has_no_external_source(prompt.predecessor_dispatch_id),
            dispatch_has_no_successor(prompt.predecessor_dispatch_id),
        )
        .values(
            status="closed",
            closed_at=closed_at,
            closed_reason="watchdog_superseded",
            next_provider_start_at=None,
            provider_start_retry_kind=None,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    if closed_dispatch_id is None:
        await session.rollback()
        return False
    return True


async def _claim_watchdog_replacement_task(
    session: AsyncSession,
    *,
    snapshot: WatchdogRecoverySnapshot,
) -> bool:
    dispatch = snapshot.dispatch
    prompt = dispatch.prompt
    updated_task_id = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == prompt.task_id,
            TaskModel.status == "running",
            TaskModel.current_team_revision_id == prompt.team_revision_id,
            TaskModel.control_revision == dispatch.task_control_revision,
            watchdog_context_is_current(snapshot),
            watchdog_replacement_count_matches(snapshot),
            dispatch_has_no_external_source(prompt.predecessor_dispatch_id),
            dispatch_has_no_successor(prompt.predecessor_dispatch_id),
        )
        .values(updated_at=TaskModel.updated_at)
        .returning(TaskModel.task_id)
    )
    if updated_task_id is None:
        await session.rollback()
        return False
    return True


def _publish_dispatch_start(
    dependencies: DispatchOpeningDependencies,
    prepared: PreparedDispatchRequest,
) -> None:
    from banksia.runtime.dispatch.ordinary_continuation import publish_dispatch_start_due

    publish_dispatch_start_due(dependencies, prepared)


def _publish_cleanup(
    dependencies: DispatchOpeningDependencies,
    dispatch_id: str,
) -> None:
    try:
        dependencies.post_commit_publisher.publish(DispatchCleanupRequested(dispatch_id))
    except Exception:
        pass


def _publish_cleanups(
    dependencies: DispatchOpeningDependencies,
    dispatch_ids: tuple[str, ...],
) -> None:
    for dispatch_id in dispatch_ids:
        _publish_cleanup(dependencies, dispatch_id)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "WatchdogDueHandler",
    "WatchdogRecoveryResult",
    "create_watchdog_due_handler",
    "recover_stale_dispatch",
]
