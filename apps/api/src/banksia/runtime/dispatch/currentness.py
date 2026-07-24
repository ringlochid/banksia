"""Attempt-local current Dispatch ownership primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    DispatchTurnModel,
    FlowModel,
)


@dataclass(frozen=True, slots=True)
class AttemptDispatchIdentity:
    """Complete immutable owner tuple for one Dispatch in an Attempt lane."""

    task_id: str
    flow_id: str
    assignment_id: str
    attempt_id: str
    dispatch_id: str


class AttemptDispatchConflictError(RuntimeError):
    """Raised when another transition owns an Attempt's current lane."""


@dataclass(frozen=True, slots=True)
class AttemptWaitIdentity:
    """Complete immutable owner tuple for one wait selected by an Attempt."""

    task_id: str
    flow_id: str
    assignment_id: str
    attempt_id: str
    wait_id: str


def attempt_dispatch_is_current(
    identity: AttemptDispatchIdentity,
) -> ColumnElement[bool]:
    """Return the exact active Attempt-pointer predicate for a Dispatch."""

    return exists(
        select(AttemptModel.attempt_id).where(
            AttemptModel.attempt_id == identity.attempt_id,
            AttemptModel.task_id == identity.task_id,
            AttemptModel.flow_id == identity.flow_id,
            AttemptModel.assignment_id == identity.assignment_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id == identity.dispatch_id,
            AttemptModel.current_wait_id.is_(None),
        )
    )


def dispatch_attempt_is_current() -> ColumnElement[bool]:
    """Return a predicate correlated to the enclosing Dispatch row."""

    return exists(
        select(AttemptModel.attempt_id).where(
            AttemptModel.attempt_id == DispatchTurnModel.attempt_id,
            AttemptModel.task_id == DispatchTurnModel.task_id,
            AttemptModel.flow_id == DispatchTurnModel.flow_id,
            AttemptModel.assignment_id == DispatchTurnModel.assignment_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id == DispatchTurnModel.dispatch_id,
            AttemptModel.current_wait_id.is_(None),
        )
    )


async def select_starting_dispatch_for_attempt(
    session: AsyncSession,
    *,
    identity: AttemptDispatchIdentity,
    predecessor_dispatch_id: str | None,
) -> bool:
    """Conditionally select one newly staged Dispatch for its running Attempt."""

    expected_pointer: ColumnElement[bool] = AttemptModel.current_dispatch_id.is_(None)
    if predecessor_dispatch_id is not None:
        expected_pointer = or_(
            expected_pointer,
            AttemptModel.current_dispatch_id == predecessor_dispatch_id,
        )
    selected_attempt_id = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.attempt_id == identity.attempt_id,
            AttemptModel.task_id == identity.task_id,
            AttemptModel.flow_id == identity.flow_id,
            AttemptModel.assignment_id == identity.assignment_id,
            AttemptModel.status == "running",
            AttemptModel.current_wait_id.is_(None),
            expected_pointer,
        )
        .values(current_dispatch_id=identity.dispatch_id)
        .returning(AttemptModel.attempt_id)
    )
    return selected_attempt_id is not None


async def clear_current_attempt_dispatch(
    session: AsyncSession,
    *,
    identity: AttemptDispatchIdentity,
) -> bool:
    """Conditionally clear only the exact Dispatch selected by its Attempt."""

    cleared_attempt_id = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.attempt_id == identity.attempt_id,
            AttemptModel.task_id == identity.task_id,
            AttemptModel.flow_id == identity.flow_id,
            AttemptModel.assignment_id == identity.assignment_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id == identity.dispatch_id,
            AttemptModel.current_wait_id.is_(None),
        )
        .values(current_dispatch_id=None)
        .returning(AttemptModel.attempt_id)
    )
    return cleared_attempt_id is not None


async def close_current_attempt_dispatch(
    session: AsyncSession,
    *,
    identity: AttemptDispatchIdentity,
    expected_flow_revision_id: str,
    closed_at: datetime,
    closed_reason: str,
) -> bool:
    """Close and clear one exact current Dispatch without changing lane revisions."""

    claimed_flow_id = await session.scalar(
        update(FlowModel)
        .where(
            FlowModel.flow_id == identity.flow_id,
            FlowModel.task_id == identity.task_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == expected_flow_revision_id,
            attempt_dispatch_is_current(identity),
        )
        # Take the global lifecycle row first without changing semantic truth.
        # A concurrent pause/cancel therefore wins or loses before this local
        # Attempt transition mutates its lane.
        .values(updated_at=FlowModel.updated_at)
        .returning(FlowModel.flow_id)
    )
    if claimed_flow_id is None:
        return False

    closed_dispatch_id = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == identity.dispatch_id,
            DispatchTurnModel.task_id == identity.task_id,
            DispatchTurnModel.flow_id == identity.flow_id,
            DispatchTurnModel.assignment_id == identity.assignment_id,
            DispatchTurnModel.attempt_id == identity.attempt_id,
            DispatchTurnModel.flow_revision_id == expected_flow_revision_id,
            DispatchTurnModel.status.in_(("starting", "open")),
            attempt_dispatch_is_current(identity),
        )
        .values(
            status="closed",
            closed_at=closed_at,
            closed_reason=closed_reason,
            next_provider_start_at=None,
            provider_start_retry_kind=None,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    if closed_dispatch_id is None:
        return False
    return await clear_current_attempt_dispatch(session, identity=identity)


async def suspend_current_attempt_on_wait(
    session: AsyncSession,
    *,
    identity: AttemptDispatchIdentity,
    wait_id: str,
    expected_flow_revision_id: str,
    closed_at: datetime,
    closed_reason: str,
) -> bool:
    """Close one current Dispatch and select its exact typed Attempt wait."""

    claimed_flow_id = await session.scalar(
        update(FlowModel)
        .where(
            FlowModel.flow_id == identity.flow_id,
            FlowModel.task_id == identity.task_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == expected_flow_revision_id,
            attempt_dispatch_is_current(identity),
            exists(
                select(AttemptWaitModel.wait_id).where(
                    AttemptWaitModel.wait_id == wait_id,
                    AttemptWaitModel.task_id == identity.task_id,
                    AttemptWaitModel.flow_id == identity.flow_id,
                    AttemptWaitModel.assignment_id == identity.assignment_id,
                    AttemptWaitModel.attempt_id == identity.attempt_id,
                    AttemptWaitModel.source_dispatch_id == identity.dispatch_id,
                )
            ),
            exists(
                select(DispatchTurnModel.dispatch_id).where(
                    DispatchTurnModel.dispatch_id == identity.dispatch_id,
                    DispatchTurnModel.task_id == identity.task_id,
                    DispatchTurnModel.flow_id == identity.flow_id,
                    DispatchTurnModel.assignment_id == identity.assignment_id,
                    DispatchTurnModel.attempt_id == identity.attempt_id,
                    DispatchTurnModel.flow_revision_id == expected_flow_revision_id,
                    DispatchTurnModel.status.in_(("starting", "open")),
                )
            ),
        )
        .values(updated_at=FlowModel.updated_at)
        .returning(FlowModel.flow_id)
    )
    if claimed_flow_id is None:
        return False

    closed_dispatch_id = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == identity.dispatch_id,
            DispatchTurnModel.task_id == identity.task_id,
            DispatchTurnModel.flow_id == identity.flow_id,
            DispatchTurnModel.assignment_id == identity.assignment_id,
            DispatchTurnModel.attempt_id == identity.attempt_id,
            DispatchTurnModel.flow_revision_id == expected_flow_revision_id,
            DispatchTurnModel.status.in_(("starting", "open")),
            attempt_dispatch_is_current(identity),
        )
        .values(
            status="closed",
            closed_at=closed_at,
            closed_reason=closed_reason,
            next_provider_start_at=None,
            provider_start_retry_kind=None,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    if closed_dispatch_id is None:
        return False

    selected_attempt_id = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.attempt_id == identity.attempt_id,
            AttemptModel.task_id == identity.task_id,
            AttemptModel.flow_id == identity.flow_id,
            AttemptModel.assignment_id == identity.assignment_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id == identity.dispatch_id,
            AttemptModel.current_wait_id.is_(None),
        )
        .values(
            current_dispatch_id=None,
            current_wait_id=wait_id,
        )
        .returning(AttemptModel.attempt_id)
    )
    return selected_attempt_id is not None


async def clear_current_attempt_wait(
    session: AsyncSession,
    *,
    identity: AttemptWaitIdentity,
) -> bool:
    """Conditionally clear only the exact wait selected by its Attempt."""

    cleared_attempt_id = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.attempt_id == identity.attempt_id,
            AttemptModel.task_id == identity.task_id,
            AttemptModel.flow_id == identity.flow_id,
            AttemptModel.assignment_id == identity.assignment_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_(None),
            AttemptModel.current_wait_id == identity.wait_id,
        )
        .values(current_wait_id=None)
        .returning(AttemptModel.attempt_id)
    )
    return cleared_attempt_id is not None


__all__ = [
    "AttemptDispatchConflictError",
    "AttemptDispatchIdentity",
    "AttemptWaitIdentity",
    "attempt_dispatch_is_current",
    "clear_current_attempt_dispatch",
    "clear_current_attempt_wait",
    "close_current_attempt_dispatch",
    "dispatch_attempt_is_current",
    "select_starting_dispatch_for_attempt",
    "suspend_current_attempt_on_wait",
]
