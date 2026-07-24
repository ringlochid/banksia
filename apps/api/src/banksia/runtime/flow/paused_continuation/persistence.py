from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import AttemptModel, FlowModel
from banksia.runtime.contracts import TaskEventType
from banksia.runtime.dispatch.opening import (
    StartingDispatchBasis,
    TaskResumeEventBasis,
    stage_starting_dispatch,
)
from banksia.runtime.dispatch.ordinary_context import (
    OrdinaryDispatchSnapshot,
    ordinary_context_is_current,
    read_ordinary_dispatch_snapshot,
)
from banksia.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    prepare_dispatch_request,
)
from banksia.runtime.dispatch.prompt_snapshot import build_ordinary_dispatch_request
from banksia.runtime.flow.paused_continuation.contracts import (
    OperatorContinueSource,
    PausedFlowContinuationPlan,
    PreparedPausedContinuation,
    paused_continuation_conflict,
)
from banksia.runtime.task_events import append_task_event


async def prepare_paused_continuations(
    session: AsyncSession,
    *,
    plan: PausedFlowContinuationPlan,
    dependencies: DispatchOpeningDependencies,
) -> tuple[PreparedPausedContinuation, ...]:
    candidates: list[tuple[OrdinaryDispatchSnapshot, OperatorContinueSource, str, datetime]] = []
    for source in plan.sources:
        dispatch_id = f"dispatch.{uuid4().hex}"
        due_at = dependencies.clock()
        snapshot = await read_ordinary_dispatch_snapshot(
            session,
            basis=source.basis,
            dispatch_id=dispatch_id,
            dependencies=dependencies,
            expected_flow_status="paused",
            expected_control_revision=plan.flow.control_revision,
        )
        if snapshot is None:
            raise paused_continuation_conflict("paused Attempt continuation is no longer current")
        candidates.append((snapshot, source, dispatch_id, due_at))

    await session.rollback()
    prepared: list[PreparedPausedContinuation] = []
    for snapshot, source, dispatch_id, due_at in candidates:
        prepared_request = prepare_dispatch_request(
            dependencies=dependencies,
            dispatch_id=dispatch_id,
            due_at=due_at,
            provider=snapshot.provider,
            capabilities=snapshot.capabilities,
            request=build_ordinary_dispatch_request(snapshot.prompt),
        )
        prepared.append(
            PreparedPausedContinuation(
                snapshot=snapshot,
                prepared=prepared_request,
                claim=source.claim,
            )
        )
    return tuple(prepared)


async def commit_paused_continuations(
    session: AsyncSession,
    *,
    plan: PausedFlowContinuationPlan,
    prepared: tuple[PreparedPausedContinuation, ...],
    resume_event: TaskResumeEventBasis,
    resumed_at: datetime,
) -> None:
    if resume_event.control_revision != plan.flow.control_revision + 1:
        raise paused_continuation_conflict("resume event revision does not match the paused Flow")
    flow_id = await session.scalar(
        update(FlowModel)
        .where(
            *_paused_flow_is_current(plan),
            *(ordinary_context_is_current(item.snapshot) for item in prepared),
        )
        .values(
            status="running",
            pause_reason=None,
            pause_details=None,
            paused_at=None,
            paused_by_actor_ref=None,
            control_revision=FlowModel.control_revision + 1,
            updated_at=resumed_at,
        )
        .returning(FlowModel.flow_id)
    )
    if flow_id is None:
        raise paused_continuation_conflict("another controller transition won during continue")
    for item in prepared:
        if not await item.claim(session, item.snapshot, item.prepared):
            raise paused_continuation_conflict("a paused Attempt source changed during continue")
        await stage_starting_dispatch(
            session,
            basis=_starting_dispatch_basis(item),
            prepared=item.prepared,
        )
    await _append_resume_event(
        session,
        plan=plan,
        prepared=prepared,
        resume_event=resume_event,
        resumed_at=resumed_at,
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def _paused_flow_is_current(
    plan: PausedFlowContinuationPlan,
) -> tuple[ColumnElement[bool], ...]:
    flow = plan.flow
    attempt_count = (
        select(func.count())
        .select_from(AttemptModel)
        .where(
            AttemptModel.task_id == flow.task_id,
            AttemptModel.flow_id == flow.flow_id,
            AttemptModel.status == "running",
        )
        .scalar_subquery()
    )
    predicates: list[ColumnElement[bool]] = [
        FlowModel.flow_id == flow.flow_id,
        FlowModel.task_id == flow.task_id,
        FlowModel.compiled_plan_id == flow.compiled_plan_id,
        FlowModel.status == "paused",
        FlowModel.active_flow_revision_id == flow.active_flow_revision_id,
        FlowModel.control_revision == flow.control_revision,
        FlowModel.pause_reason == flow.pause_reason,
        attempt_count == len(flow.lanes),
    ]
    for lane in flow.lanes:
        lane_predicates: list[ColumnElement[bool]] = [
            AttemptModel.task_id == flow.task_id,
            AttemptModel.flow_id == flow.flow_id,
            AttemptModel.assignment_id == lane.assignment_id,
            AttemptModel.attempt_id == lane.attempt_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_(None),
            (
                AttemptModel.current_wait_id.is_(None)
                if lane.current_wait_id is None
                else AttemptModel.current_wait_id == lane.current_wait_id
            ),
        ]
        predicates.append(exists().where(*lane_predicates))
    return tuple(predicates)


def _starting_dispatch_basis(item: PreparedPausedContinuation) -> StartingDispatchBasis:
    snapshot = item.snapshot
    prompt = snapshot.prompt
    return StartingDispatchBasis(
        task_id=prompt.task_id,
        flow_id=prompt.flow_id,
        assignment_id=prompt.assignment_id,
        flow_revision_id=prompt.flow_revision_id,
        flow_node_id=prompt.flow_node_id,
        team_revision_id=prompt.team_revision_id,
        member_id=prompt.member_id,
        member_configuration_id=prompt.member_configuration_id,
        member_branch_basis_id=prompt.member_branch_basis_id,
        attempt_id=prompt.attempt_id,
        node_key=prompt.node_key,
        opened_reason=snapshot.basis.opened_reason,
        predecessor_dispatch_id=prompt.predecessor_dispatch_id,
        flow_start_source_flow_id=None,
    )


async def _append_resume_event(
    session: AsyncSession,
    *,
    plan: PausedFlowContinuationPlan,
    prepared: tuple[PreparedPausedContinuation, ...],
    resume_event: TaskResumeEventBasis,
    resumed_at: datetime,
) -> None:
    lane_count = len(prepared)
    await append_task_event(
        session,
        task_id=plan.flow.task_id,
        event_type=TaskEventType.TASK_RESUMED,
        event_source=resume_event.event_source,
        occurred_at=resumed_at,
        flow_revision_id=plan.flow.active_flow_revision_id,
        actor_ref=resume_event.actor_ref,
        payload={
            "control_revision": resume_event.control_revision,
            "actor_ref": resume_event.actor_ref,
            "summary": (
                f"Resumed by operator with {lane_count} runnable "
                f"Attempt lane{'s' if lane_count != 1 else ''}."
            ),
        },
    )


__all__ = [
    "commit_paused_continuations",
    "prepare_paused_continuations",
]
