from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchRequestModel,
    DispatchTurnModel,
)
from banksia.runtime.contracts.prompt import DelegationWaveSettledTrigger
from banksia.runtime.delegation import (
    open_delegation_wave_successor,
    settle_delegation_wave,
)
from banksia.runtime.delegation.continuation import (
    read_delegation_wave_continuation_basis,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import DelegationWaveSettled

type AsyncSessionSource = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class DelegationAssignment:
    child_id: str
    prompt: str


@dataclass(frozen=True, slots=True)
class OpenedDelegationMember:
    child_id: str
    assignment_id: str
    dispatch_id: str


@dataclass(frozen=True, slots=True)
class OpenedDelegationWave:
    wave_id: str
    source_dispatch_id: str
    response_must_stop: bool
    members: tuple[OpenedDelegationMember, ...]
    parent_wait_id: str | None

    def dispatch_for(self, child_id: str) -> str:
        matches = tuple(
            member.dispatch_id for member in self.members if member.child_id == child_id
        )
        if len(matches) != 1:
            raise AssertionError(
                f"expected one Delegation Wave member for {child_id!r}, found {len(matches)}"
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class DelegationWaveSettlementObservation:
    did_settle: bool
    member_results: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class DelegationWaveOpeningObservation:
    outcome: str
    dispatch_id: str | None
    persisted_successor_dispatch_id: str | None
    parent_current_dispatch_id: str | None
    parent_current_wait_id: str | None
    successor_request_input: str | None
    successor_count: int
    parent_wait_exists: bool


async def delegate_direct_team_for_e2e(
    executor: NodeOperationExecutor,
    session_source: AsyncSessionSource,
    *,
    task_id: str,
    parent_dispatch_id: str,
    assignments: tuple[DelegationAssignment, ...],
) -> OpenedDelegationWave:
    response = await executor.execute(
        scope=NodeOperationScope(
            task_id=task_id,
            dispatch_id=parent_dispatch_id,
        ),
        operation_name="delegate",
        arguments={
            "assignments": [
                {"child_id": assignment.child_id, "prompt": assignment.prompt}
                for assignment in assignments
            ]
        },
    )
    async with session_source() as session:
        wave = await session.scalar(
            select(DelegationWaveModel).where(
                DelegationWaveModel.source_dispatch_id == parent_dispatch_id
            )
        )
        assert wave is not None
        members = tuple(
            await session.scalars(
                select(DelegationWaveMemberModel)
                .where(DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id)
                .order_by(DelegationWaveMemberModel.order_index)
            )
        )
        wait = await session.scalar(
            select(AttemptWaitModel).where(
                AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id
            )
        )
        opened_members: list[OpenedDelegationMember] = []
        for member in members:
            opened_members.append(
                OpenedDelegationMember(
                    child_id=member.child_member_id,
                    assignment_id=member.child_assignment_id,
                    dispatch_id=await _current_assignment_dispatch(
                        session,
                        member.child_assignment_id,
                    ),
                )
            )
    return OpenedDelegationWave(
        wave_id=wave.delegation_wave_id,
        source_dispatch_id=wave.source_dispatch_id,
        response_must_stop=response.model_dump().get("must_stop") is True,
        members=tuple(opened_members),
        parent_wait_id=wait.wait_id if wait is not None else None,
    )


async def settle_delegation_wave_for_e2e(
    session_source: AsyncSessionSource,
    *,
    wave_id: str,
    dependencies: DispatchOpeningDependencies,
) -> DelegationWaveSettlementObservation:
    async with session_source() as session:
        did_settle = await settle_delegation_wave(
            session,
            delegation_wave_id=wave_id,
            settled_at=dependencies.clock(),
        )
    async with session_source() as session:
        basis = await read_delegation_wave_continuation_basis(session, wave_id)
    member_results: tuple[tuple[str, str], ...] = ()
    if basis is not None and isinstance(basis.trigger, DelegationWaveSettledTrigger):
        member_results = tuple(
            (member.child_id, member.checkpoint.summary) for member in basis.trigger.result.members
        )
    return DelegationWaveSettlementObservation(
        did_settle=did_settle,
        member_results=member_results,
    )


async def open_delegation_wave_successor_for_e2e(
    session_source: AsyncSessionSource,
    *,
    wave_id: str,
    dependencies: DispatchOpeningDependencies,
) -> DelegationWaveOpeningObservation:
    async with session_source() as session:
        opening = await open_delegation_wave_successor(
            session,
            signal=DelegationWaveSettled(wave_id),
            dependencies=dependencies,
        )
    async with session_source() as session:
        wave = await session.get(DelegationWaveModel, wave_id)
        assert wave is not None
        attempt = await session.get(AttemptModel, wave.parent_attempt_id)
        request = (
            await session.get(DispatchRequestModel, wave.successor_dispatch_id)
            if wave.successor_dispatch_id is not None
            else None
        )
        successor_count = int(
            await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(
                    DispatchTurnModel.assignment_id == wave.parent_assignment_id,
                    DispatchTurnModel.attempt_id == wave.parent_attempt_id,
                    DispatchTurnModel.predecessor_dispatch_id == wave.source_dispatch_id,
                    DispatchTurnModel.opened_reason == "delegation_wave",
                )
            )
            or 0
        )
        wait = await session.scalar(
            select(AttemptWaitModel).where(AttemptWaitModel.delegation_wave_id == wave_id)
        )
    return DelegationWaveOpeningObservation(
        outcome=opening.outcome,
        dispatch_id=opening.dispatch_id,
        persisted_successor_dispatch_id=wave.successor_dispatch_id,
        parent_current_dispatch_id=(attempt.current_dispatch_id if attempt is not None else None),
        parent_current_wait_id=attempt.current_wait_id if attempt is not None else None,
        successor_request_input=request.input if request is not None else None,
        successor_count=successor_count,
        parent_wait_exists=wait is not None,
    )


async def _current_assignment_dispatch(
    session: AsyncSession,
    assignment_id: str,
) -> str:
    assignment = await session.get(AssignmentModel, assignment_id)
    assert assignment is not None and assignment.current_attempt_id is not None
    attempt = await session.get(AttemptModel, assignment.current_attempt_id)
    assert attempt is not None and attempt.current_dispatch_id is not None
    return attempt.current_dispatch_id


__all__ = [
    "DelegationAssignment",
    "DelegationWaveOpeningObservation",
    "DelegationWaveSettlementObservation",
    "OpenedDelegationMember",
    "OpenedDelegationWave",
    "delegate_direct_team_for_e2e",
    "open_delegation_wave_successor_for_e2e",
    "settle_delegation_wave_for_e2e",
]
