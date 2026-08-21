"""Delegation-Wave startup recovery page readers."""

from __future__ import annotations

from sqlalchemy import exists, select

from oh_my_subagents.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    TaskModel,
)
from oh_my_subagents.runtime.post_commit.router import AsyncSessionContextFactory
from oh_my_subagents.runtime.post_commit.signals import (
    DelegationWaveSettled,
    RuntimeEffectSignal,
    WaveMemberSettled,
)
from oh_my_subagents.runtime.startup_audit import StartupAuditPage


async def read_wave_settlement_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read open Waves whose exact ordered members are all settled."""

    async with session_factory() as session:
        incomplete_member = exists().where(
            DelegationWaveMemberModel.delegation_wave_id == DelegationWaveModel.delegation_wave_id,
            DelegationWaveMemberModel.status != "settled",
        )
        statement = (
            select(DelegationWaveModel.delegation_wave_id)
            .join(TaskModel, TaskModel.task_id == DelegationWaveModel.task_id)
            .join(
                AttemptWaitModel,
                (AttemptWaitModel.task_id == DelegationWaveModel.task_id)
                & (AttemptWaitModel.assignment_id == DelegationWaveModel.parent_assignment_id)
                & (AttemptWaitModel.attempt_id == DelegationWaveModel.parent_attempt_id)
                & (AttemptWaitModel.source_dispatch_id == DelegationWaveModel.source_dispatch_id)
                & (AttemptWaitModel.delegation_wave_id == DelegationWaveModel.delegation_wave_id),
            )
            .join(
                AttemptModel,
                (AttemptModel.task_id == AttemptWaitModel.task_id)
                & (AttemptModel.assignment_id == AttemptWaitModel.assignment_id)
                & (AttemptModel.attempt_id == AttemptWaitModel.attempt_id)
                & (AttemptModel.current_wait_id == AttemptWaitModel.wait_id),
            )
            .where(
                DelegationWaveModel.status == "open",
                DelegationWaveModel.successor_dispatch_id.is_(None),
                TaskModel.status.in_(("running", "paused")),
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_(None),
                ~incomplete_member,
            )
            .order_by(DelegationWaveModel.delegation_wave_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(DelegationWaveModel.delegation_wave_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return StartupAuditPage(
        tuple(WaveMemberSettled(source_id) for source_id in source_ids),
        source_ids[-1] if len(source_ids) == page_size else None,
    )


async def read_wave_continuation_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[RuntimeEffectSignal, str]:
    """Read settled Waves whose parent continuation is still unconsumed."""

    async with session_factory() as session:
        statement = (
            select(DelegationWaveModel.delegation_wave_id)
            .join(TaskModel, TaskModel.task_id == DelegationWaveModel.task_id)
            .join(
                AttemptModel,
                (AttemptModel.task_id == DelegationWaveModel.task_id)
                & (AttemptModel.assignment_id == DelegationWaveModel.parent_assignment_id)
                & (AttemptModel.attempt_id == DelegationWaveModel.parent_attempt_id),
            )
            .where(
                DelegationWaveModel.status == "settled",
                DelegationWaveModel.successor_dispatch_id.is_(None),
                TaskModel.status == "running",
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_(None),
                AttemptModel.current_wait_id.is_(None),
            )
            .order_by(DelegationWaveModel.delegation_wave_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(DelegationWaveModel.delegation_wave_id > cursor)
        source_ids = tuple((await session.scalars(statement)).all())
    return StartupAuditPage(
        tuple(DelegationWaveSettled(source_id) for source_id in source_ids),
        source_ids[-1] if len(source_ids) == page_size else None,
    )


__all__ = [
    "read_wave_continuation_page",
    "read_wave_settlement_page",
]
