from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    FlowNodeModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.currentness import (
    AttemptWaitIdentity,
    clear_current_attempt_wait,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import DelegationWaveSettled, WaveMemberSettled

type WaveMemberSettledHandler = Callable[
    [AsyncSession, WaveMemberSettled],
    Awaitable[None],
]


async def settle_wave_member_for_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    boundary_id: str,
    outcome: str,
    settled_at: datetime,
) -> str:
    """Settle the exact pending Wave member in its terminal Checkpoint transaction."""

    if outcome not in {"green", "blocked"}:
        raise ValueError("only green or blocked may settle a Delegation Wave member")
    wave_is_open = exists().where(
        DelegationWaveModel.delegation_wave_id == DelegationWaveMemberModel.delegation_wave_id,
        DelegationWaveModel.task_id == DelegationWaveMemberModel.task_id,
        DelegationWaveModel.flow_id == DelegationWaveMemberModel.flow_id,
        DelegationWaveModel.parent_assignment_id == DelegationWaveMemberModel.parent_assignment_id,
        DelegationWaveModel.parent_attempt_id == DelegationWaveMemberModel.parent_attempt_id,
        DelegationWaveModel.source_dispatch_id == DelegationWaveMemberModel.source_dispatch_id,
        DelegationWaveModel.status == "open",
        DelegationWaveModel.successor_dispatch_id.is_(None),
    )
    wave_id = await session.scalar(
        update(DelegationWaveMemberModel)
        .where(
            DelegationWaveMemberModel.task_id == authority.task_id,
            DelegationWaveMemberModel.flow_id == authority.flow_id,
            DelegationWaveMemberModel.child_assignment_id == authority.assignment_id,
            DelegationWaveMemberModel.child_member_id == authority.flow_node.member_id,
            DelegationWaveMemberModel.child_node_key == authority.node_key,
            DelegationWaveMemberModel.status == "pending",
            DelegationWaveMemberModel.terminal_boundary_id.is_(None),
            wave_is_open,
        )
        .values(
            status="settled",
            terminal_boundary_id=boundary_id,
            terminal_outcome=outcome,
            settled_at=settled_at,
            cancelled_at=None,
        )
        .returning(DelegationWaveMemberModel.delegation_wave_id)
    )
    if wave_id is None:
        raise _wave_conflict(
            "terminal child Checkpoint no longer owns one pending Delegation Wave member"
        )
    return wave_id


def create_wave_member_settled_handler(
    dependencies: DispatchOpeningDependencies,
) -> WaveMemberSettledHandler:
    """Create the idempotent all-members-terminal join handler."""

    async def handle(session: AsyncSession, signal: WaveMemberSettled) -> None:
        settled = await settle_delegation_wave(
            session,
            delegation_wave_id=signal.delegation_wave_id,
            settled_at=dependencies.clock(),
        )
        if not settled:
            return
        continuation_signal = DelegationWaveSettled(
            delegation_wave_id=signal.delegation_wave_id,
        )
        try:
            accepted = dependencies.post_commit_publisher.publish(continuation_signal)
        except Exception:
            accepted = False
        if not accepted:
            # A rejected chained hint must still converge during this recovery run.
            # Defer this import because checkpoint package initialization reaches
            # settlement while continuation reads checkpoint file references.
            from banksia.runtime.delegation.continuation import (
                open_delegation_wave_successor,
            )

            await open_delegation_wave_successor(
                session,
                signal=continuation_signal,
                dependencies=dependencies,
            )

    return handle


async def settle_delegation_wave(
    session: AsyncSession,
    *,
    delegation_wave_id: str,
    settled_at: datetime,
) -> bool:
    """Settle one complete Wave and clear only its exact parent Attempt wait."""

    wave = await _read_open_wave(session, delegation_wave_id)
    if wave is None:
        await session.rollback()
        return False

    wait = await _read_parent_wave_wait(session, wave)
    if wait is None:
        await session.rollback()
        raise _wave_conflict("open Delegation Wave is missing its exact parent wait")

    if not await _claim_complete_wave(session, wave, settled_at=settled_at):
        await session.rollback()
        return False
    if not await _clear_parent_wave_wait(session, wave, wait):
        await session.rollback()
        raise _wave_conflict("Delegation Wave parent wait changed before join settlement")
    if not await _resume_parent_wave_node(session, wave):
        await session.rollback()
        raise _wave_conflict("Delegation Wave parent node changed before join settlement")

    await session.commit()
    return True


async def _read_open_wave(
    session: AsyncSession,
    delegation_wave_id: str,
) -> DelegationWaveModel | None:
    wave: DelegationWaveModel | None = await session.scalar(
        select(DelegationWaveModel)
        .options(raiseload("*"))
        .where(
            DelegationWaveModel.delegation_wave_id == delegation_wave_id,
            DelegationWaveModel.status == "open",
            DelegationWaveModel.successor_dispatch_id.is_(None),
        )
    )
    return wave


async def _read_parent_wave_wait(
    session: AsyncSession,
    wave: DelegationWaveModel,
) -> AttemptWaitModel | None:
    wait: AttemptWaitModel | None = await session.scalar(
        select(AttemptWaitModel)
        .options(raiseload("*"))
        .where(
            AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id,
            AttemptWaitModel.task_id == wave.task_id,
            AttemptWaitModel.flow_id == wave.flow_id,
            AttemptWaitModel.assignment_id == wave.parent_assignment_id,
            AttemptWaitModel.attempt_id == wave.parent_attempt_id,
            AttemptWaitModel.source_dispatch_id == wave.source_dispatch_id,
        )
    )
    return wait


async def _claim_complete_wave(
    session: AsyncSession,
    wave: DelegationWaveModel,
    *,
    settled_at: datetime,
) -> bool:
    incomplete_member = exists().where(
        DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id,
        DelegationWaveMemberModel.status != "settled",
    )
    claimed = await session.scalar(
        update(DelegationWaveModel)
        .where(
            DelegationWaveModel.delegation_wave_id == wave.delegation_wave_id,
            DelegationWaveModel.task_id == wave.task_id,
            DelegationWaveModel.flow_id == wave.flow_id,
            DelegationWaveModel.parent_assignment_id == wave.parent_assignment_id,
            DelegationWaveModel.parent_attempt_id == wave.parent_attempt_id,
            DelegationWaveModel.source_dispatch_id == wave.source_dispatch_id,
            DelegationWaveModel.flow_revision_id == wave.flow_revision_id,
            DelegationWaveModel.parent_node_key == wave.parent_node_key,
            DelegationWaveModel.status == "open",
            DelegationWaveModel.successor_dispatch_id.is_(None),
            ~incomplete_member,
        )
        .values(status="settled", settled_at=settled_at)
        .returning(DelegationWaveModel.delegation_wave_id)
    )
    return claimed is not None


async def _clear_parent_wave_wait(
    session: AsyncSession,
    wave: DelegationWaveModel,
    wait: AttemptWaitModel,
) -> bool:
    cleared = await clear_current_attempt_wait(
        session,
        identity=AttemptWaitIdentity(
            task_id=wait.task_id,
            flow_id=wait.flow_id,
            assignment_id=wait.assignment_id,
            attempt_id=wait.attempt_id,
            wait_id=wait.wait_id,
        ),
    )
    if not cleared:
        return False
    deleted_wait = await session.scalar(
        delete(AttemptWaitModel)
        .where(
            AttemptWaitModel.wait_id == wait.wait_id,
            AttemptWaitModel.task_id == wait.task_id,
            AttemptWaitModel.flow_id == wait.flow_id,
            AttemptWaitModel.assignment_id == wait.assignment_id,
            AttemptWaitModel.attempt_id == wait.attempt_id,
            AttemptWaitModel.source_dispatch_id == wait.source_dispatch_id,
            AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id,
        )
        .returning(AttemptWaitModel.wait_id)
    )
    return deleted_wait is not None


async def _resume_parent_wave_node(
    session: AsyncSession,
    wave: DelegationWaveModel,
) -> bool:
    resumed_node_ids = tuple(
        await session.scalars(
            update(FlowNodeModel)
            .where(
                FlowNodeModel.task_id == wave.task_id,
                FlowNodeModel.flow_id == wave.flow_id,
                FlowNodeModel.node_key == wave.parent_node_key,
                FlowNodeModel.current_assignment_id == wave.parent_assignment_id,
                FlowNodeModel.state == "waiting",
            )
            .values(state="running")
            .returning(FlowNodeModel.flow_node_id)
        )
    )
    return bool(resumed_node_ids)


def _wave_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


__all__ = [
    "WaveMemberSettledHandler",
    "create_wave_member_settled_handler",
    "settle_delegation_wave",
    "settle_wave_member_for_checkpoint",
]
