"""Paused Task continuation source discovery."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, raiseload

from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    DelegationWaveModel,
    DispatchTurnModel,
    HumanRequestModel,
    ReplanTransitionModel,
    TaskModel,
    TaskStartSourceModel,
)
from banksia.persistence.models.runtime.common import COMMAND_RUN_TERMINAL_STATE_VALUES
from banksia.runtime.command_run.continuation import (
    claim_command_run_continuation,
    read_command_run_continuation_basis,
)
from banksia.runtime.contracts.prompt import (
    OperatorContinueResult,
    OperatorContinueTrigger,
)
from banksia.runtime.contracts.prompt import (
    OperatorContinueSource as PromptOperatorContinueSource,
)
from banksia.runtime.delegation.continuation import (
    claim_delegation_wave_continuation,
    read_delegation_wave_continuation_basis,
)
from banksia.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
)
from banksia.runtime.dispatch.preparation import PreparedDispatchRequest
from banksia.runtime.human_request.continuation import (
    claim_human_request_continuation,
    read_human_request_continuation_basis,
)
from banksia.runtime.replan.continuation import (
    claim_replan_continuation,
    ensure_replan_manifest_current,
    read_replan_continuation_basis,
)
from banksia.runtime.task_control.paused_continuation.contracts import (
    OperatorContinueSource,
    PausedAttemptLane,
    PausedTaskContinuationPlan,
    PausedTaskSnapshot,
    paused_continuation_conflict,
)


async def repair_paused_replan_manifests(
    session: AsyncSession,
    *,
    task_id: str,
    expected_team_revision_id: str,
    expected_control_revision: int,
) -> None:
    transition_ids = tuple(
        await session.scalars(
            select(ReplanTransitionModel.replan_transition_id)
            .join(TaskModel, TaskModel.task_id == ReplanTransitionModel.task_id)
            .where(
                ReplanTransitionModel.task_id == task_id,
                ReplanTransitionModel.successor_team_revision_id == expected_team_revision_id,
                ReplanTransitionModel.successor_state.not_in(("opened", "cancelled")),
                ReplanTransitionModel.successor_dispatch_id.is_(None),
                TaskModel.status == "paused",
                TaskModel.current_team_revision_id == expected_team_revision_id,
                TaskModel.control_revision == expected_control_revision,
            )
            .order_by(ReplanTransitionModel.replan_transition_id)
        )
    )
    for transition_id in transition_ids:
        if not await ensure_replan_manifest_current(session, transition_id):
            raise paused_continuation_conflict(
                f"paused replan '{transition_id}' could not make its manifest current"
            )


async def read_paused_task_continuation_plan(
    session: AsyncSession,
    *,
    task_id: str,
    expected_team_revision_id: str,
    expected_control_revision: int,
) -> PausedTaskContinuationPlan:
    """Enumerate every paused Attempt lane without inventing a global lane pointer."""

    task = await _read_paused_task_snapshot(
        session,
        task_id=task_id,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
    )
    sources = await _read_operator_continue_sources(session, task)
    sources_by_lane: dict[tuple[str, str], list[OperatorContinueSource]] = defaultdict(list)
    for source in sources:
        sources_by_lane[source.lane_key].append(source)

    lane_keys = {(lane.assignment_id, lane.attempt_id) for lane in task.lanes}
    if any(key not in lane_keys for key in sources_by_lane):
        raise paused_continuation_conflict(
            "paused Task retained a source outside its running Attempts"
        )
    has_task_start = await _has_unconsumed_task_start(session, task.task_id)
    await _validate_lane_sources(
        session,
        task=task,
        sources_by_lane=sources_by_lane,
        has_task_start=has_task_start,
    )
    return PausedTaskContinuationPlan(
        task=task,
        sources=tuple(sorted(sources, key=_source_sort_key)),
        has_unconsumed_task_start=has_task_start,
    )


async def claim_operator_continue_tail(
    session: AsyncSession,
    snapshot: OrdinaryDispatchSnapshot,
    prepared: PreparedDispatchRequest,
) -> bool:
    """Recheck one source-free closed Attempt lineage tail before batch commit."""

    del prepared
    source_dispatch_id = snapshot.basis.source_dispatch_id
    successor = aliased(DispatchTurnModel)
    is_available = await session.scalar(
        select(
            exists().where(
                DispatchTurnModel.dispatch_id == source_dispatch_id,
                DispatchTurnModel.task_id == snapshot.prompt.task_id,
                DispatchTurnModel.assignment_id == snapshot.prompt.assignment_id,
                DispatchTurnModel.attempt_id == snapshot.prompt.attempt_id,
                DispatchTurnModel.status == "closed",
                DispatchTurnModel.closed_reason == snapshot.basis.source_dispatch_closed_reason,
                ~exists().where(successor.predecessor_dispatch_id == source_dispatch_id),
                ~exists().where(
                    HumanRequestModel.source_dispatch_id == source_dispatch_id,
                    HumanRequestModel.successor_dispatch_id.is_(None),
                ),
                ~exists().where(
                    CommandRunModel.source_dispatch_id == source_dispatch_id,
                    CommandRunModel.successor_dispatch_id.is_(None),
                ),
                ~exists().where(
                    DelegationWaveModel.source_dispatch_id == source_dispatch_id,
                    DelegationWaveModel.successor_dispatch_id.is_(None),
                ),
                ~exists().where(
                    ReplanTransitionModel.source_dispatch_id == source_dispatch_id,
                    ReplanTransitionModel.successor_dispatch_id.is_(None),
                    ReplanTransitionModel.successor_state.not_in(("opened", "cancelled")),
                ),
            )
        )
    )
    return bool(is_available)


async def _read_paused_task_snapshot(
    session: AsyncSession,
    *,
    task_id: str,
    expected_team_revision_id: str,
    expected_control_revision: int,
) -> PausedTaskSnapshot:
    task = await session.scalar(
        select(TaskModel)
        .options(raiseload("*"))
        .where(
            TaskModel.task_id == task_id,
            TaskModel.status == "paused",
            TaskModel.current_team_revision_id == expected_team_revision_id,
            TaskModel.control_revision == expected_control_revision,
        )
        .execution_options(populate_existing=True)
    )
    if (
        task is None
        or task.current_team_revision_id is None
        or task.pause_reason
        not in {
            "paused_by_operator",
            "runtime_recovery_exhausted",
            "runtime_transition_failed",
        }
    ):
        raise paused_continuation_conflict("Task is not paused at the expected revision")
    rows = (
        await session.execute(
            select(
                AttemptModel.assignment_id,
                AttemptModel.attempt_id,
                AttemptModel.current_dispatch_id,
                AttemptModel.current_wait_id,
            )
            .where(
                AttemptModel.task_id == task.task_id,
                AttemptModel.status == "running",
            )
            .order_by(AttemptModel.assignment_id, AttemptModel.attempt_id)
        )
    ).all()
    if any(current_dispatch_id is not None for _, _, current_dispatch_id, _ in rows):
        raise paused_continuation_conflict("paused Task still owns a current Attempt Dispatch")
    return PausedTaskSnapshot(
        task_id=task.task_id,
        current_team_revision_id=task.current_team_revision_id,
        control_revision=task.control_revision,
        pause_reason=task.pause_reason,
        lanes=tuple(
            PausedAttemptLane(
                assignment_id=assignment_id,
                attempt_id=attempt_id,
                current_wait_id=current_wait_id,
            )
            for assignment_id, attempt_id, _, current_wait_id in rows
        ),
    )


async def _read_operator_continue_sources(
    session: AsyncSession,
    task: PausedTaskSnapshot,
) -> tuple[OperatorContinueSource, ...]:
    sources = [
        *await _read_human_request_sources(session, task),
        *await _read_command_run_sources(session, task),
        *await _read_delegation_wave_sources(session, task),
        *await _read_replan_sources(session, task),
        *await _read_closed_tail_sources(session, task),
    ]
    return tuple(sources)


async def _read_human_request_sources(
    session: AsyncSession,
    task: PausedTaskSnapshot,
) -> tuple[OperatorContinueSource, ...]:
    request_ids = tuple(
        await session.scalars(
            select(HumanRequestModel.request_id)
            .where(
                HumanRequestModel.task_id == task.task_id,
                HumanRequestModel.status.in_(("resolved", "timed_out", "cancelled")),
                HumanRequestModel.successor_dispatch_id.is_(None),
            )
            .order_by(
                HumanRequestModel.assignment_id,
                HumanRequestModel.attempt_id,
                HumanRequestModel.request_id,
            )
        )
    )
    sources = []
    for request_id in request_ids:
        basis = await read_human_request_continuation_basis(session, request_id)
        if basis is not None:
            sources.append(
                OperatorContinueSource(
                    basis=basis,
                    claim=claim_human_request_continuation,
                )
            )
    return tuple(sources)


async def _read_command_run_sources(
    session: AsyncSession,
    task: PausedTaskSnapshot,
) -> tuple[OperatorContinueSource, ...]:
    run_ids = tuple(
        await session.scalars(
            select(CommandRunModel.run_id)
            .where(
                CommandRunModel.task_id == task.task_id,
                CommandRunModel.state.in_(COMMAND_RUN_TERMINAL_STATE_VALUES),
                CommandRunModel.successor_dispatch_id.is_(None),
            )
            .order_by(
                CommandRunModel.assignment_id,
                CommandRunModel.attempt_id,
                CommandRunModel.run_id,
            )
        )
    )
    sources = []
    for run_id in run_ids:
        basis = await read_command_run_continuation_basis(session, run_id)
        if basis is not None:
            sources.append(
                OperatorContinueSource(
                    basis=basis,
                    claim=claim_command_run_continuation,
                )
            )
    return tuple(sources)


async def _read_delegation_wave_sources(
    session: AsyncSession,
    task: PausedTaskSnapshot,
) -> tuple[OperatorContinueSource, ...]:
    wave_ids = tuple(
        await session.scalars(
            select(DelegationWaveModel.delegation_wave_id)
            .where(
                DelegationWaveModel.task_id == task.task_id,
                DelegationWaveModel.status == "settled",
                DelegationWaveModel.successor_dispatch_id.is_(None),
            )
            .order_by(
                DelegationWaveModel.parent_assignment_id,
                DelegationWaveModel.parent_attempt_id,
                DelegationWaveModel.delegation_wave_id,
            )
        )
    )
    sources = []
    for wave_id in wave_ids:
        basis = await read_delegation_wave_continuation_basis(session, wave_id)
        if basis is not None:
            sources.append(
                OperatorContinueSource(
                    basis=basis,
                    claim=claim_delegation_wave_continuation,
                )
            )
    return tuple(sources)


async def _read_replan_sources(
    session: AsyncSession,
    task: PausedTaskSnapshot,
) -> tuple[OperatorContinueSource, ...]:
    transition_ids = tuple(
        await session.scalars(
            select(ReplanTransitionModel.replan_transition_id)
            .where(
                ReplanTransitionModel.task_id == task.task_id,
                ReplanTransitionModel.successor_team_revision_id == task.current_team_revision_id,
                ReplanTransitionModel.manifest_state == "current",
                ReplanTransitionModel.successor_state.in_(("pending", "opening_failed")),
                ReplanTransitionModel.successor_dispatch_id.is_(None),
            )
            .order_by(
                ReplanTransitionModel.assignment_id,
                ReplanTransitionModel.attempt_id,
                ReplanTransitionModel.replan_transition_id,
            )
        )
    )
    sources = []
    for transition_id in transition_ids:
        basis = await read_replan_continuation_basis(session, transition_id)
        if basis is not None:
            sources.append(
                OperatorContinueSource(
                    basis=basis,
                    claim=claim_replan_continuation,
                )
            )
    return tuple(sources)


async def _read_closed_tail_sources(
    session: AsyncSession,
    task: PausedTaskSnapshot,
) -> tuple[OperatorContinueSource, ...]:
    successor = aliased(DispatchTurnModel)
    tails = tuple(
        await session.scalars(
            select(DispatchTurnModel)
            .options(raiseload("*"))
            .where(
                DispatchTurnModel.task_id == task.task_id,
                DispatchTurnModel.status == "closed",
                DispatchTurnModel.closed_reason.in_(("paused", "control_failed")),
                ~exists().where(successor.predecessor_dispatch_id == DispatchTurnModel.dispatch_id),
            )
            .order_by(
                DispatchTurnModel.assignment_id,
                DispatchTurnModel.attempt_id,
                DispatchTurnModel.dispatch_id,
            )
        )
    )
    sources = []
    for tail in tails:
        if tail.closed_reason is None:
            raise paused_continuation_conflict("closed lineage tail is missing its close reason")
        sources.append(
            OperatorContinueSource(
                basis=OrdinaryContinuationBasis(
                    task_id=tail.task_id,
                    assignment_id=tail.assignment_id,
                    attempt_id=tail.attempt_id,
                    source_dispatch_id=tail.dispatch_id,
                    source_dispatch_closed_reason=tail.closed_reason,
                    opened_reason="operator_continue",
                    trigger=OperatorContinueTrigger(
                        source=PromptOperatorContinueSource(
                            source_dispatch_id=tail.dispatch_id,
                        ),
                        result=OperatorContinueResult(
                            control_revision=task.control_revision,
                            pause_reason=task.pause_reason,
                        ),
                    ),
                ),
                claim=claim_operator_continue_tail,
            )
        )
    return tuple(sources)


async def _validate_lane_sources(
    session: AsyncSession,
    *,
    task: PausedTaskSnapshot,
    sources_by_lane: dict[tuple[str, str], list[OperatorContinueSource]],
    has_task_start: bool,
) -> None:
    for lane in task.lanes:
        lane_sources = sources_by_lane.get((lane.assignment_id, lane.attempt_id), [])
        if lane.current_wait_id is not None:
            if lane_sources:
                raise paused_continuation_conflict(
                    "waiting Attempt also retained a runnable continuation source"
                )
            await _validate_current_attempt_wait(session, task, lane)
        elif len(lane_sources) > 1:
            raise paused_continuation_conflict(
                "paused Attempt retained more than one runnable continuation source"
            )
        elif not lane_sources and not has_task_start:
            raise paused_continuation_conflict("paused Attempt has no exact continuation source")
    if has_task_start:
        if len(task.lanes) != 1 or sources_by_lane or task.lanes[0].current_wait_id is not None:
            raise paused_continuation_conflict(
                "unconsumed Task start is not the exclusive initial Attempt source"
            )
    elif not task.lanes:
        raise paused_continuation_conflict("paused Task has no running Attempt lanes")


async def _validate_current_attempt_wait(
    session: AsyncSession,
    task: PausedTaskSnapshot,
    lane: PausedAttemptLane,
) -> None:
    wait = await session.scalar(
        select(AttemptWaitModel)
        .options(raiseload("*"))
        .where(
            AttemptWaitModel.wait_id == lane.current_wait_id,
            AttemptWaitModel.task_id == task.task_id,
            AttemptWaitModel.assignment_id == lane.assignment_id,
            AttemptWaitModel.attempt_id == lane.attempt_id,
        )
    )
    if wait is None:
        raise paused_continuation_conflict("Attempt current wait identity is inconsistent")
    current = await _wait_source_is_unresolved(session, wait)
    if not current:
        raise paused_continuation_conflict("Attempt wait source is no longer unresolved")


async def _wait_source_is_unresolved(
    session: AsyncSession,
    wait: AttemptWaitModel,
) -> bool:
    if wait.human_request_id is not None:
        predicate = exists().where(
            HumanRequestModel.request_id == wait.human_request_id,
            HumanRequestModel.status == "open",
            HumanRequestModel.successor_dispatch_id.is_(None),
        )
    elif wait.command_run_id is not None:
        predicate = exists().where(
            CommandRunModel.run_id == wait.command_run_id,
            CommandRunModel.state.not_in(COMMAND_RUN_TERMINAL_STATE_VALUES),
            CommandRunModel.successor_dispatch_id.is_(None),
        )
    elif wait.delegation_wave_id is not None:
        predicate = exists().where(
            DelegationWaveModel.delegation_wave_id == wait.delegation_wave_id,
            DelegationWaveModel.status == "open",
            DelegationWaveModel.successor_dispatch_id.is_(None),
        )
    else:
        raise paused_continuation_conflict("Attempt wait has no typed source")
    return bool(await session.scalar(select(predicate)))


async def _has_unconsumed_task_start(
    session: AsyncSession,
    task_id: str,
) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    TaskStartSourceModel.task_id == task_id,
                    TaskStartSourceModel.successor_dispatch_id.is_(None),
                )
            )
        )
    )


def _source_sort_key(source: OperatorContinueSource) -> tuple[str, str, str, str]:
    basis = source.basis
    return (
        basis.assignment_id,
        basis.attempt_id,
        basis.opened_reason,
        basis.continuation_source_id or basis.source_dispatch_id,
    )


__all__ = [
    "claim_operator_continue_tail",
    "read_paused_task_continuation_plan",
    "repair_paused_replan_manifests",
]
