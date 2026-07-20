from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, raiseload

from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    CommandRunModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    FlowStartSourceModel,
    HumanRequestModel,
)
from autoclaw.persistence.models.runtime.common import COMMAND_RUN_TERMINAL_STATE_VALUES
from autoclaw.runtime.boundary.target_resolution import resolve_boundary_target
from autoclaw.runtime.contracts import (
    CommandRunState,
    CommandRunSummary,
    HumanRequestKind,
    HumanRequestStatus,
    HumanRequestSummary,
)
from autoclaw.runtime.errors import illegal_state_error


@dataclass(frozen=True, slots=True)
class RuntimeFlowTarget:
    node_key: str
    assignment_id: str
    attempt_id: str


@dataclass(frozen=True, slots=True)
class RuntimeFlowCurrentSources:
    target: RuntimeFlowTarget | None = None
    human_request: HumanRequestSummary | None = None
    command_run: CommandRunSummary | None = None


@dataclass(frozen=True, slots=True)
class _RetainedContinuationSources:
    boundary: AcceptedBoundaryModel | None = None
    human_request: HumanRequestModel | None = None
    command_run: CommandRunModel | None = None


async def read_runtime_flow_current_sources(
    session: AsyncSession,
    flow: FlowModel,
) -> RuntimeFlowCurrentSources:
    """Resolve the exact controller source that currently explains one flow."""

    if flow.current_dispatch_id is not None:
        dispatch = await session.scalar(
            select(DispatchTurnModel)
            .options(raiseload("*"))
            .where(
                DispatchTurnModel.dispatch_id == flow.current_dispatch_id,
                DispatchTurnModel.task_id == flow.task_id,
                DispatchTurnModel.flow_id == flow.flow_id,
                DispatchTurnModel.status.in_(("starting", "open")),
            )
        )
        if dispatch is None:
            raise illegal_state_error("flow current-dispatch pointer is inconsistent")
        return RuntimeFlowCurrentSources(target=_target_from_dispatch(dispatch))

    if flow.waiting_cause == "human_request" and flow.waiting_source_id is not None:
        request = await session.scalar(
            select(HumanRequestModel)
            .options(raiseload("*"))
            .where(
                HumanRequestModel.request_id == flow.waiting_source_id,
                HumanRequestModel.task_id == flow.task_id,
                HumanRequestModel.flow_id == flow.flow_id,
                HumanRequestModel.status == "open",
            )
        )
        if request is None:
            raise illegal_state_error("flow human-request pointer is inconsistent")
        return RuntimeFlowCurrentSources(
            target=await _target_from_external_source(session, flow, request),
            human_request=_human_request_summary(request),
        )

    if flow.waiting_cause == "command_run" and flow.waiting_source_id is not None:
        run = await session.scalar(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.run_id == flow.waiting_source_id,
                CommandRunModel.task_id == flow.task_id,
                CommandRunModel.flow_id == flow.flow_id,
                CommandRunModel.state.not_in(COMMAND_RUN_TERMINAL_STATE_VALUES),
            )
        )
        if run is None:
            raise illegal_state_error("flow command-run pointer is inconsistent")
        return RuntimeFlowCurrentSources(
            target=await _target_from_external_source(session, flow, run),
            command_run=_command_run_summary(run),
        )

    if flow.waiting_cause != "none" or flow.waiting_source_id is not None:
        raise illegal_state_error("flow waiting pointer is inconsistent")
    if flow.status in {"completed", "cancelled"}:
        return RuntimeFlowCurrentSources()

    sources = await _read_retained_continuation_sources(session, flow)
    target: RuntimeFlowTarget | None
    if sources.boundary is not None:
        target = await _read_boundary_target(session, flow, sources.boundary)
    elif sources.human_request is not None:
        target = await _target_from_external_source(session, flow, sources.human_request)
    elif sources.command_run is not None:
        target = await _target_from_external_source(session, flow, sources.command_run)
    else:
        target = await _read_source_free_target(session, flow)
        if target is None:
            target = await _read_unconsumed_flow_start_target(session, flow)
    return RuntimeFlowCurrentSources(
        target=target,
        human_request=(
            _human_request_summary(sources.human_request)
            if sources.human_request is not None
            else None
        ),
        command_run=(
            _command_run_summary(sources.command_run) if sources.command_run is not None else None
        ),
    )


async def _read_retained_continuation_sources(
    session: AsyncSession,
    flow: FlowModel,
) -> _RetainedContinuationSources:
    boundaries = tuple(
        await session.scalars(
            select(AcceptedBoundaryModel)
            .options(raiseload("*"))
            .where(
                AcceptedBoundaryModel.flow_id == flow.flow_id,
                AcceptedBoundaryModel.task_id == flow.task_id,
                AcceptedBoundaryModel.successor_dispatch_id.is_(None),
            )
            .limit(2)
        )
    )
    human_requests = tuple(
        await session.scalars(
            select(HumanRequestModel)
            .options(raiseload("*"))
            .where(
                HumanRequestModel.flow_id == flow.flow_id,
                HumanRequestModel.task_id == flow.task_id,
                HumanRequestModel.successor_dispatch_id.is_(None),
            )
            .limit(2)
        )
    )
    command_runs = tuple(
        await session.scalars(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.flow_id == flow.flow_id,
                CommandRunModel.task_id == flow.task_id,
                CommandRunModel.successor_dispatch_id.is_(None),
            )
            .limit(2)
        )
    )
    if (
        len(boundaries) > 1
        or len(human_requests) > 1
        or len(command_runs) > 1
        or sum(bool(rows) for rows in (boundaries, human_requests, command_runs)) > 1
    ):
        raise illegal_state_error("flow has more than one retained continuation source")

    human_request = human_requests[0] if human_requests else None
    command_run = command_runs[0] if command_runs else None
    if human_request is not None and human_request.status == "open":
        raise illegal_state_error("open human request is missing its flow wait pointer")
    if command_run is not None and command_run.state not in COMMAND_RUN_TERMINAL_STATE_VALUES:
        raise illegal_state_error("nonterminal command run is missing its flow wait pointer")
    return _RetainedContinuationSources(
        boundary=boundaries[0] if boundaries else None,
        human_request=human_request,
        command_run=command_run,
    )


async def _read_boundary_target(
    session: AsyncSession,
    flow: FlowModel,
    boundary: AcceptedBoundaryModel,
) -> RuntimeFlowTarget:
    source_assignment = await session.scalar(
        select(AssignmentModel)
        .options(raiseload("*"))
        .where(
            AssignmentModel.assignment_id == boundary.assignment_id,
            AssignmentModel.task_id == boundary.task_id,
            AssignmentModel.flow_id == boundary.flow_id,
        )
    )
    if source_assignment is None:
        raise illegal_state_error("accepted boundary is missing its source assignment")
    try:
        target = await resolve_boundary_target(
            session,
            boundary=boundary,
            source_assignment=source_assignment,
        )
    except ValueError as exc:
        raise illegal_state_error("accepted boundary has no valid semantic target") from exc
    assignment = await session.scalar(
        select(AssignmentModel)
        .options(raiseload("*"))
        .where(
            AssignmentModel.assignment_id == target.assignment_id,
            AssignmentModel.task_id == flow.task_id,
            AssignmentModel.flow_id == flow.flow_id,
            AssignmentModel.current_attempt_id == target.attempt_id,
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if assignment is None:
        raise illegal_state_error("accepted boundary semantic target is no longer current")
    return RuntimeFlowTarget(
        node_key=assignment.node_key,
        assignment_id=target.assignment_id,
        attempt_id=target.attempt_id,
    )


async def _read_source_free_target(
    session: AsyncSession,
    flow: FlowModel,
) -> RuntimeFlowTarget | None:
    successor = aliased(DispatchTurnModel)
    rows = tuple(
        await session.scalars(
            select(DispatchTurnModel)
            .options(raiseload("*"))
            .where(
                DispatchTurnModel.task_id == flow.task_id,
                DispatchTurnModel.flow_id == flow.flow_id,
                DispatchTurnModel.status == "closed",
                DispatchTurnModel.closed_reason.in_(("paused", "control_failed")),
                ~exists().where(successor.predecessor_dispatch_id == DispatchTurnModel.dispatch_id),
            )
            .limit(2)
        )
    )
    if len(rows) > 1:
        raise illegal_state_error("flow has more than one retained lineage tail")
    return _target_from_dispatch(rows[0]) if rows else None


async def _read_unconsumed_flow_start_target(
    session: AsyncSession,
    flow: FlowModel,
) -> RuntimeFlowTarget | None:
    if flow.active_flow_revision_id is None:
        return None
    row = (
        await session.execute(
            select(FlowNodeModel, AssignmentModel)
            .select_from(FlowStartSourceModel)
            .join(FlowModel, FlowModel.flow_id == FlowStartSourceModel.flow_id)
            .join(
                FlowNodeModel,
                and_(
                    FlowNodeModel.flow_id == FlowModel.flow_id,
                    FlowNodeModel.flow_revision_id == FlowModel.active_flow_revision_id,
                ),
            )
            .join(
                AssignmentModel,
                AssignmentModel.assignment_id == FlowNodeModel.current_assignment_id,
            )
            .options(raiseload("*"))
            .where(
                FlowStartSourceModel.flow_id == flow.flow_id,
                FlowStartSourceModel.successor_dispatch_id.is_(None),
                FlowNodeModel.structural_kind == "root",
                FlowNodeModel.parent_node_key.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    node, assignment = row
    if assignment.current_attempt_id is None:
        raise illegal_state_error("unconsumed flow start has no current attempt")
    return RuntimeFlowTarget(
        node_key=node.node_key,
        assignment_id=assignment.assignment_id,
        attempt_id=assignment.current_attempt_id,
    )


async def _target_from_external_source(
    session: AsyncSession,
    flow: FlowModel,
    source: HumanRequestModel | CommandRunModel,
) -> RuntimeFlowTarget:
    node_key = await session.scalar(
        select(DispatchTurnModel.node_key).where(
            DispatchTurnModel.dispatch_id == source.source_dispatch_id,
            DispatchTurnModel.flow_id == flow.flow_id,
        )
    )
    if node_key is None:
        raise illegal_state_error("external source dispatch lineage is incomplete")
    return RuntimeFlowTarget(
        node_key=node_key,
        assignment_id=source.assignment_id,
        attempt_id=source.attempt_id,
    )


def _target_from_dispatch(dispatch: DispatchTurnModel) -> RuntimeFlowTarget:
    return RuntimeFlowTarget(
        node_key=dispatch.node_key,
        assignment_id=dispatch.assignment_id,
        attempt_id=dispatch.attempt_id,
    )


def _human_request_summary(request: HumanRequestModel) -> HumanRequestSummary:
    return HumanRequestSummary(
        request_id=request.request_id,
        source_dispatch_id=request.source_dispatch_id,
        kind=HumanRequestKind(request.request_kind),
        status=HumanRequestStatus(request.status),
        summary=request.request_summary,
        due_at=_optional_utc(request.due_at),
        opened_at=_as_utc(request.opened_at),
    )


def _command_run_summary(run: CommandRunModel) -> CommandRunSummary:
    return CommandRunSummary(
        run_id=run.run_id,
        source_dispatch_id=run.source_dispatch_id,
        state=CommandRunState(run.state),
        summary=run.summary,
        due_at=_optional_utc(run.due_at),
        created_at=_as_utc(run.created_at),
        started_at=_optional_utc(run.started_at),
    )


def _optional_utc(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "RuntimeFlowCurrentSources",
    "RuntimeFlowTarget",
    "read_runtime_flow_current_sources",
]
