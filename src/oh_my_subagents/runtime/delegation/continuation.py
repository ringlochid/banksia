from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from oh_my_subagents.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    TaskModel,
)
from oh_my_subagents.runtime.assignment import read_assignment_file_references
from oh_my_subagents.runtime.checkpoint.reads import read_checkpoint_file_references
from oh_my_subagents.runtime.contracts.primitives import CheckpointOutcome
from oh_my_subagents.runtime.contracts.prompt import (
    DelegationWaveMemberResult,
    DelegationWaveSettledResult,
    DelegationWaveSettledSource,
    DelegationWaveSettledTrigger,
    PromptAssignment,
    PromptCheckpointSummary,
)
from oh_my_subagents.runtime.control_transitions import pause_task_for_runtime_transition_failure
from oh_my_subagents.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
)
from oh_my_subagents.runtime.dispatch.ordinary_continuation import (
    OrdinaryOpeningResult,
    open_ordinary_successor,
)
from oh_my_subagents.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
)
from oh_my_subagents.runtime.post_commit import DelegationWaveSettled

type DelegationWaveSettledHandler = Callable[
    [AsyncSession, DelegationWaveSettled],
    Awaitable[None],
]


@dataclass(frozen=True, slots=True)
class _SettledWaveMemberTruth:
    member: DelegationWaveMemberModel
    assignment: AssignmentModel
    boundary: AcceptedBoundaryModel
    checkpoint: AttemptCheckpointModel


def create_delegation_wave_settled_handler(
    dependencies: DispatchOpeningDependencies,
) -> DelegationWaveSettledHandler:
    """Create the idempotent settled-Wave continuation handler."""

    async def handle(session: AsyncSession, signal: DelegationWaveSettled) -> None:
        await open_delegation_wave_successor(
            session,
            signal=signal,
            dependencies=dependencies,
        )

    return handle


async def open_delegation_wave_successor(
    session: AsyncSession,
    *,
    signal: DelegationWaveSettled,
    dependencies: DispatchOpeningDependencies,
) -> OrdinaryOpeningResult:
    """Open at most one same-Attempt parent continuation for a settled Wave."""

    return await open_ordinary_successor(
        session,
        source_id=signal.delegation_wave_id,
        dependencies=dependencies,
        read_source=read_delegation_wave_continuation_basis,
        claim_source=claim_delegation_wave_continuation,
        record_failure=pause_failed_delegation_wave_continuation,
        default_failure_code="delegation_wave_dispatch_preparation_failed",
    )


async def read_delegation_wave_continuation_basis(
    session: AsyncSession,
    delegation_wave_id: str,
) -> OrdinaryContinuationBasis | None:
    """Read one settled, unconsumed Wave and its complete ordered member results."""

    wave = await session.scalar(
        select(DelegationWaveModel)
        .options(raiseload("*"))
        .where(
            DelegationWaveModel.delegation_wave_id == delegation_wave_id,
            DelegationWaveModel.status == "settled",
            DelegationWaveModel.successor_dispatch_id.is_(None),
        )
    )
    if wave is None:
        return None

    rows = await _read_settled_wave_member_truth(session, wave)
    member_count = await session.scalar(
        select(func.count())
        .select_from(DelegationWaveMemberModel)
        .where(DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id)
    )
    if member_count is None or member_count != len(rows):
        raise ValueError("settled Delegation Wave has incomplete terminal member truth")

    members = await _build_wave_member_results(session, rows)
    return OrdinaryContinuationBasis(
        task_id=wave.task_id,
        assignment_id=wave.parent_assignment_id,
        attempt_id=wave.parent_attempt_id,
        source_dispatch_id=wave.source_dispatch_id,
        source_dispatch_closed_reason="delegation",
        opened_reason="delegation_wave",
        trigger=DelegationWaveSettledTrigger(
            source=DelegationWaveSettledSource(
                delegation_wave_id=wave.delegation_wave_id,
                source_dispatch_id=wave.source_dispatch_id,
            ),
            result=DelegationWaveSettledResult(members=members),
        ),
        continuation_source_id=wave.delegation_wave_id,
    )


async def claim_delegation_wave_continuation(
    session: AsyncSession,
    snapshot: OrdinaryDispatchSnapshot,
    prepared: PreparedDispatchRequest,
) -> bool:
    """Conditionally record the exact same-Attempt Wave successor."""

    trigger = snapshot.basis.trigger
    if not isinstance(trigger, DelegationWaveSettledTrigger):
        return False
    wave_id = await session.scalar(
        update(DelegationWaveModel)
        .where(
            DelegationWaveModel.delegation_wave_id == trigger.source.delegation_wave_id,
            DelegationWaveModel.task_id == snapshot.prompt.task_id,
            DelegationWaveModel.parent_assignment_id == snapshot.prompt.assignment_id,
            DelegationWaveModel.parent_attempt_id == snapshot.prompt.attempt_id,
            DelegationWaveModel.source_dispatch_id == trigger.source.source_dispatch_id,
            DelegationWaveModel.status == "settled",
            DelegationWaveModel.successor_dispatch_id.is_(None),
        )
        .values(successor_dispatch_id=prepared.dispatch_id)
        .returning(DelegationWaveModel.delegation_wave_id)
    )
    return wave_id is not None


async def pause_failed_delegation_wave_continuation(
    session: AsyncSession,
    delegation_wave_id: str,
    paused_at: datetime,
    failure_code: str,
) -> tuple[str, ...]:
    """Pause the exact failed source and every runnable sibling Attempt lane."""

    source_is_unconsumed = exists(
        select(DelegationWaveModel.delegation_wave_id)
        .join(
            AttemptModel,
            (AttemptModel.task_id == DelegationWaveModel.task_id)
            & (AttemptModel.assignment_id == DelegationWaveModel.parent_assignment_id)
            & (AttemptModel.attempt_id == DelegationWaveModel.parent_attempt_id),
        )
        .where(
            DelegationWaveModel.delegation_wave_id == delegation_wave_id,
            DelegationWaveModel.task_id == TaskModel.task_id,
            DelegationWaveModel.status == "settled",
            DelegationWaveModel.successor_dispatch_id.is_(None),
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_(None),
            AttemptModel.current_wait_id.is_(None),
        )
    )
    return await pause_task_for_runtime_transition_failure(
        session,
        source_is_current=source_is_unconsumed,
        paused_at=paused_at,
        pause_details={
            "source": "delegation_wave",
            "delegation_wave_id": delegation_wave_id,
            "failure_code": failure_code,
        },
    )


async def _read_settled_wave_member_truth(
    session: AsyncSession,
    wave: DelegationWaveModel,
) -> tuple[_SettledWaveMemberTruth, ...]:
    rows = (
        await session.execute(
            select(
                DelegationWaveMemberModel,
                AssignmentModel,
                AcceptedBoundaryModel,
                AttemptCheckpointModel,
            )
            .options(raiseload("*"))
            .join(
                AssignmentModel,
                AssignmentModel.assignment_id == DelegationWaveMemberModel.child_assignment_id,
            )
            .join(
                AcceptedBoundaryModel,
                AcceptedBoundaryModel.accepted_boundary_id
                == DelegationWaveMemberModel.terminal_boundary_id,
            )
            .join(
                AttemptCheckpointModel,
                AttemptCheckpointModel.checkpoint_id == AcceptedBoundaryModel.checkpoint_id,
            )
            .where(
                DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id,
                DelegationWaveMemberModel.task_id == wave.task_id,
                DelegationWaveMemberModel.parent_assignment_id == wave.parent_assignment_id,
                DelegationWaveMemberModel.parent_attempt_id == wave.parent_attempt_id,
                DelegationWaveMemberModel.source_dispatch_id == wave.source_dispatch_id,
                DelegationWaveMemberModel.status == "settled",
                DelegationWaveMemberModel.terminal_outcome.in_(("green", "blocked")),
                AssignmentModel.task_id == wave.task_id,
                AcceptedBoundaryModel.task_id == wave.task_id,
                AcceptedBoundaryModel.assignment_id
                == DelegationWaveMemberModel.child_assignment_id,
                AcceptedBoundaryModel.outcome == DelegationWaveMemberModel.terminal_outcome,
                AttemptCheckpointModel.task_id == wave.task_id,
                AttemptCheckpointModel.assignment_id
                == DelegationWaveMemberModel.child_assignment_id,
                AttemptCheckpointModel.outcome == DelegationWaveMemberModel.terminal_outcome,
            )
            .order_by(DelegationWaveMemberModel.order_index)
        )
    ).all()
    return tuple(
        _SettledWaveMemberTruth(
            member=member,
            assignment=assignment,
            boundary=boundary,
            checkpoint=checkpoint,
        )
        for member, assignment, boundary, checkpoint in rows
    )


async def _build_wave_member_results(
    session: AsyncSession,
    rows: tuple[_SettledWaveMemberTruth, ...],
) -> tuple[DelegationWaveMemberResult, ...]:
    members: list[DelegationWaveMemberResult] = []
    for row in rows:
        member = row.member
        assignment = row.assignment
        boundary = row.boundary
        checkpoint = row.checkpoint
        if (
            boundary.checkpoint_id != checkpoint.checkpoint_id
            or boundary.attempt_id != checkpoint.attempt_id
            or checkpoint.authoring_dispatch_id != boundary.source_dispatch_id
            or checkpoint.outcome is None
        ):
            raise ValueError(
                "settled Delegation Wave member has inconsistent terminal Checkpoint truth"
            )
        assignment_files = await read_assignment_file_references(
            session,
            assignment_id=assignment.assignment_id,
        )
        checkpoint_files = await read_checkpoint_file_references(
            session,
            checkpoint_id=checkpoint.checkpoint_id,
        )
        terminal_outcome = cast(
            Literal[CheckpointOutcome.GREEN, CheckpointOutcome.BLOCKED],
            CheckpointOutcome(cast(str, member.terminal_outcome)),
        )
        members.append(
            DelegationWaveMemberResult(
                child_id=member.child_member_id,
                assignment=PromptAssignment(
                    id=assignment.assignment_id,
                    prompt=assignment.prompt,
                    files=assignment_files,
                ),
                outcome=terminal_outcome,
                checkpoint=PromptCheckpointSummary(
                    id=checkpoint.checkpoint_id,
                    summary=checkpoint.summary,
                    details=checkpoint.details,
                    files=checkpoint_files,
                    outcome=CheckpointOutcome(checkpoint.outcome),
                ),
            )
        )
    return tuple(members)


__all__ = [
    "DelegationWaveSettledHandler",
    "claim_delegation_wave_continuation",
    "create_delegation_wave_settled_handler",
    "open_delegation_wave_successor",
    "pause_failed_delegation_wave_continuation",
    "read_delegation_wave_continuation_basis",
]
