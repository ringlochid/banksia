"""Startup discovery for Human Request and Command Run wait sources."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    HumanRequestModel,
)
from banksia.persistence.models.runtime.common import COMMAND_RUN_TERMINAL_STATE_VALUES
from banksia.runtime.contracts import CommandRunState
from banksia.runtime.post_commit.signals import (
    CommandRunCancellationRequested,
    CommandRunPending,
    CommandRunTerminal,
    HumanRequestOpened,
    HumanRequestTerminal,
    RuntimeEffectSignal,
)
from banksia.runtime.startup_audit import StartupAuditPage

type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_HUMAN_REQUEST_TERMINAL_STATUSES = ("resolved", "timed_out", "cancelled")


async def read_human_continuation_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read terminal human sources that still have no committed successor."""

    async with session_factory() as session:
        statement = (
            select(HumanRequestModel.request_id)
            .join(
                AttemptModel,
                (AttemptModel.task_id == HumanRequestModel.task_id)
                & (AttemptModel.assignment_id == HumanRequestModel.assignment_id)
                & (AttemptModel.attempt_id == HumanRequestModel.attempt_id),
            )
            .where(
                HumanRequestModel.status.in_(_HUMAN_REQUEST_TERMINAL_STATUSES),
                HumanRequestModel.successor_dispatch_id.is_(None),
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_(None),
                AttemptModel.current_wait_id.is_(None),
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
            .join(
                AttemptWaitModel,
                (AttemptWaitModel.task_id == HumanRequestModel.task_id)
                & (AttemptWaitModel.assignment_id == HumanRequestModel.assignment_id)
                & (AttemptWaitModel.attempt_id == HumanRequestModel.attempt_id)
                & (AttemptWaitModel.source_dispatch_id == HumanRequestModel.source_dispatch_id)
                & (AttemptWaitModel.human_request_id == HumanRequestModel.request_id),
            )
            .join(
                AttemptModel,
                (AttemptModel.task_id == AttemptWaitModel.task_id)
                & (AttemptModel.assignment_id == AttemptWaitModel.assignment_id)
                & (AttemptModel.attempt_id == AttemptWaitModel.attempt_id)
                & (AttemptModel.current_wait_id == AttemptWaitModel.wait_id),
            )
            .where(
                HumanRequestModel.status == "open",
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_(None),
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
            .join(
                AttemptModel,
                (AttemptModel.task_id == CommandRunModel.task_id)
                & (AttemptModel.assignment_id == CommandRunModel.assignment_id)
                & (AttemptModel.attempt_id == CommandRunModel.attempt_id),
            )
            .where(
                CommandRunModel.state.in_(COMMAND_RUN_TERMINAL_STATE_VALUES),
                CommandRunModel.successor_dispatch_id.is_(None),
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_(None),
                AttemptModel.current_wait_id.is_(None),
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
            .join(
                AttemptWaitModel,
                (AttemptWaitModel.task_id == CommandRunModel.task_id)
                & (AttemptWaitModel.assignment_id == CommandRunModel.assignment_id)
                & (AttemptWaitModel.attempt_id == CommandRunModel.attempt_id)
                & (AttemptWaitModel.source_dispatch_id == CommandRunModel.source_dispatch_id)
                & (AttemptWaitModel.command_run_id == CommandRunModel.run_id),
            )
            .join(
                AttemptModel,
                (AttemptModel.task_id == AttemptWaitModel.task_id)
                & (AttemptModel.assignment_id == AttemptWaitModel.assignment_id)
                & (AttemptModel.attempt_id == AttemptWaitModel.attempt_id)
                & (AttemptModel.current_wait_id == AttemptWaitModel.wait_id),
            )
            .where(
                CommandRunModel.state == state.value,
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_(None),
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
    "read_command_cancellation_page",
    "read_command_continuation_page",
    "read_command_pending_page",
    "read_command_running_page",
    "read_human_continuation_page",
    "read_human_deadline_page",
]
