"""Startup discovery for Task, Replan, Dispatch-start, and watchdog sources."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    AssignmentModel,
    AttemptModel,
    CommandRunModel,
    DispatchTurnModel,
    HumanRequestModel,
    ReplanTransitionModel,
    TaskModel,
    TaskStartSourceModel,
)
from oh_my_subagents.runtime.post_commit.signals import (
    DispatchStartDue,
    ReplanCommitted,
    RuntimeEffectSignal,
    TaskStartCommitted,
    WatchdogDeadlineChanged,
)
from oh_my_subagents.runtime.startup_audit import (
    StartupAuditPage,
    StartupAuditPaginationError,
)
from oh_my_subagents.runtime.team.currentness import dispatch_team_selection_is_current
from oh_my_subagents.runtime.watchdog.deadline import calculate_watchdog_due_at

type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def read_task_start_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read runnable root sources that still have no committed root dispatch."""

    async with session_factory() as session:
        statement = (
            select(TaskStartSourceModel.task_id)
            .join(TaskModel, TaskModel.task_id == TaskStartSourceModel.task_id)
            .join(
                AssignmentModel,
                (AssignmentModel.task_id == TaskStartSourceModel.task_id)
                & (AssignmentModel.assignment_id == TaskStartSourceModel.root_assignment_id),
            )
            .join(
                AttemptModel,
                (AttemptModel.task_id == AssignmentModel.task_id)
                & (AttemptModel.assignment_id == AssignmentModel.assignment_id)
                & (AttemptModel.attempt_id == TaskStartSourceModel.root_attempt_id),
            )
            .where(
                TaskStartSourceModel.successor_dispatch_id.is_(None),
                TaskModel.status == "running",
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_(None),
                AttemptModel.current_wait_id.is_(None),
            )
            .order_by(TaskStartSourceModel.task_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(TaskStartSourceModel.task_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return _runtime_signal_page(
        source_ids,
        page_size=page_size,
        build_signal=TaskStartCommitted,
    )


async def read_replan_continuation_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read committed replans whose manifest or successor still needs repair."""

    async with session_factory() as session:
        statement = (
            select(ReplanTransitionModel.replan_transition_id)
            .where(ReplanTransitionModel.successor_state.not_in(("opened", "cancelled")))
            .order_by(ReplanTransitionModel.replan_transition_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(ReplanTransitionModel.replan_transition_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return _runtime_signal_page(
        source_ids,
        page_size=page_size,
        build_signal=ReplanCommitted,
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
                AttemptModel,
                (AttemptModel.attempt_id == DispatchTurnModel.attempt_id)
                & (AttemptModel.task_id == DispatchTurnModel.task_id)
                & (AttemptModel.assignment_id == DispatchTurnModel.assignment_id)
                & (AttemptModel.current_dispatch_id == DispatchTurnModel.dispatch_id),
            )
            .join(TaskModel, TaskModel.task_id == DispatchTurnModel.task_id)
            .where(
                DispatchTurnModel.status == "starting",
                AttemptModel.status == "running",
                AttemptModel.current_wait_id.is_(None),
                TaskModel.status == "running",
                dispatch_team_selection_is_current(),
            )
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
                AttemptModel,
                (AttemptModel.task_id == DispatchTurnModel.task_id)
                & (AttemptModel.assignment_id == DispatchTurnModel.assignment_id)
                & (AttemptModel.attempt_id == DispatchTurnModel.attempt_id)
                & (AttemptModel.current_dispatch_id == DispatchTurnModel.dispatch_id),
            )
            .join(TaskModel, TaskModel.task_id == DispatchTurnModel.task_id)
            .where(
                DispatchTurnModel.status == "open",
                AttemptModel.status == "running",
                AttemptModel.current_wait_id.is_(None),
                TaskModel.status == "running",
                dispatch_team_selection_is_current(),
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
    "read_dispatch_start_page",
    "read_replan_continuation_page",
    "read_task_start_page",
    "read_watchdog_deadline_page",
]
