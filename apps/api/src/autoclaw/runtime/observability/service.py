from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    AttemptCheckpointModel,
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    FlowEdgeModel,
    FlowModel,
    FlowNodeModel,
)
from autoclaw.runtime.contracts import (
    BoundaryHistoryEntry,
    CheckpointHistoryEntry,
    CheckpointKind,
    CheckpointOutcome,
    DispatchHistoryEntry,
    EgressBoundary,
    OperatorFlowSnapshotResponse,
    OperatorFlowTraceResponse,
    OperatorSupportSurfaceRef,
    RuntimeFlowRead,
    TaskGraphDependencyEntry,
    TaskGraphNodeEntry,
    TopActionableItem,
)
from autoclaw.runtime.errors import invalid_request_shape_error
from autoclaw.runtime.flow.reads import effective_capability_readback, read_runtime_flow
from autoclaw.runtime.task_events import latest_task_event


async def operator_snapshot(
    session: AsyncSession,
    task_id: str,
) -> OperatorFlowSnapshotResponse:
    flow = await read_runtime_flow(session, task_id)
    latest_event = await latest_task_event(session, task_id=task_id)
    current_paths = (OperatorSupportSurfaceRef.model_validate(flow.workflow_manifest_ref),)
    return OperatorFlowSnapshotResponse(
        flow=flow,
        top_actionable_items=_actionable_items(flow, current_paths),
        current_paths=current_paths,
        stream_head_event_id=latest_event.event_id if latest_event is not None else None,
    )


async def operator_trace(
    session: AsyncSession,
    task_id: str,
    *,
    scope: str = "current",
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    sort: str = "occurred_at_desc",
) -> OperatorFlowTraceResponse:
    _validate_trace_query(scope=scope, limit=limit, sort=sort)
    offset = _parse_cursor(cursor)
    flow = await read_runtime_flow(session, task_id)
    flow_row = await session.scalar(
        select(FlowModel).options(raiseload("*")).where(FlowModel.task_id == task_id)
    )
    assert flow_row is not None and flow_row.active_flow_revision_id is not None

    graph_nodes, dependency_edges = await _read_graph(
        session,
        flow_id=flow_row.flow_id,
        flow_revision_id=flow_row.active_flow_revision_id,
    )
    dispatches = await _read_dispatch_page(
        session,
        task_id=task_id,
        attempt_id=flow.active_attempt_id if scope == "current" else None,
        q=q,
        offset=offset,
        limit=limit,
        sort=sort,
    )
    page = dispatches[:limit]
    checkpoint_history = await _read_checkpoints(
        session,
        task_id=task_id,
        attempt_id=flow.active_attempt_id if scope == "current" else None,
    )
    boundary_history = await _read_boundaries(
        session,
        task_id=task_id,
        attempt_id=flow.active_attempt_id if scope == "current" else None,
    )
    current_paths = (OperatorSupportSurfaceRef.model_validate(flow.workflow_manifest_ref),)
    return OperatorFlowTraceResponse(
        task_id=task_id,
        scope=cast(Literal["current", "whole"], scope),
        graph_nodes=graph_nodes,
        dependency_edges=dependency_edges,
        dispatch_history=tuple(_dispatch_history(row) for row in page),
        checkpoint_history=checkpoint_history,
        boundary_history=boundary_history,
        current_paths=current_paths,
        next_cursor=str(offset + limit) if len(dispatches) > limit else None,
    )


def _actionable_items(
    flow: RuntimeFlowRead,
    current_paths: tuple[OperatorSupportSurfaceRef, ...],
) -> tuple[TopActionableItem, ...]:
    if flow.current_human_request is not None:
        return (
            TopActionableItem(
                summary=flow.current_human_request.summary,
                node_key=flow.current_node_key,
                current_paths=current_paths,
                suggested_action="Resolve the current human request.",
            ),
        )
    if flow.current_command_run is not None:
        return (
            TopActionableItem(
                summary=flow.current_command_run.summary,
                node_key=flow.current_node_key,
                current_paths=current_paths,
                suggested_action="Inspect the current command run.",
            ),
        )
    if flow.status == "paused":
        return (
            TopActionableItem(
                summary=f"Task is paused: {flow.pause_reason}.",
                node_key=flow.current_node_key,
                current_paths=current_paths,
                suggested_action="Inspect current truth before continuing or cancelling.",
            ),
        )
    if flow.current_dispatch is not None and flow.current_dispatch.status == "starting":
        return (
            TopActionableItem(
                summary="Provider start is pending.",
                node_key=flow.current_node_key,
                current_paths=current_paths,
                suggested_action="Wait for the scheduled provider start attempt.",
            ),
        )
    if flow.current_plan is not None:
        step = next(
            (item for item in flow.current_plan.steps if item.status != "completed"),
            None,
        )
        if step is not None:
            return (
                TopActionableItem(
                    summary=step.step,
                    node_key=flow.current_node_key,
                    current_paths=current_paths,
                ),
            )
    return ()


async def _read_graph(
    session: AsyncSession,
    *,
    flow_id: str,
    flow_revision_id: str,
) -> tuple[tuple[TaskGraphNodeEntry, ...], tuple[TaskGraphDependencyEntry, ...]]:
    nodes = tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(
                FlowNodeModel.flow_id == flow_id,
                FlowNodeModel.flow_revision_id == flow_revision_id,
            )
            .order_by(FlowNodeModel.order_index)
        )
    )
    edges = tuple(
        await session.scalars(
            select(FlowEdgeModel)
            .options(raiseload("*"))
            .where(FlowEdgeModel.flow_revision_id == flow_revision_id)
            .order_by(FlowEdgeModel.order_index)
        )
    )
    depends_on: dict[str, list[str]] = {node.node_key: [] for node in nodes}
    depended_on_by: dict[str, list[str]] = {node.node_key: [] for node in nodes}
    for edge in edges:
        depends_on[edge.consumer_node_key].append(edge.provider_node_key)
        depended_on_by[edge.provider_node_key].append(edge.consumer_node_key)
    return (
        tuple(
            TaskGraphNodeEntry(
                node_key=node.node_key,
                parent_node_key=node.parent_node_key,
                node_kind=NodeKind(node.structural_kind),
                role=node.role_key,
                policy=node.policy_key,
                description=node.description,
                order_index=node.order_index,
                child_node_keys=tuple(node.child_node_keys_json),
                depends_on_node_keys=tuple(depends_on[node.node_key]),
                depended_on_by_node_keys=tuple(depended_on_by[node.node_key]),
            )
            for node in nodes
        ),
        tuple(TaskGraphDependencyEntry.model_validate(edge) for edge in edges),
    )


async def _read_dispatch_page(
    session: AsyncSession,
    *,
    task_id: str,
    attempt_id: str | None,
    q: str | None,
    offset: int,
    limit: int,
    sort: str,
) -> list[tuple[DispatchTurnModel, DispatchCapabilitySetModel]]:
    statement = (
        select(DispatchTurnModel, DispatchCapabilitySetModel)
        .join(
            DispatchCapabilitySetModel,
            DispatchCapabilitySetModel.dispatch_id == DispatchTurnModel.dispatch_id,
        )
        .options(raiseload("*"))
        .where(DispatchTurnModel.task_id == task_id)
    )
    if attempt_id is not None:
        statement = statement.where(DispatchTurnModel.attempt_id == attempt_id)
    normalized_q = (q or "").strip().casefold()
    if normalized_q:
        pattern = f"%{normalized_q}%"
        statement = statement.where(
            or_(
                func.lower(DispatchTurnModel.dispatch_id).like(pattern),
                func.lower(DispatchTurnModel.node_key).like(pattern),
                func.lower(DispatchTurnModel.opened_reason).like(pattern),
                func.lower(func.coalesce(DispatchTurnModel.closed_reason, "")).like(pattern),
            )
        )
    direction = (
        DispatchTurnModel.created_at.asc()
        if sort == "occurred_at_asc"
        else DispatchTurnModel.created_at.desc()
    )
    rows = await session.execute(statement.order_by(direction).offset(offset).limit(limit + 1))
    return [(dispatch, capabilities) for dispatch, capabilities in rows]


def _dispatch_history(
    row: tuple[DispatchTurnModel, DispatchCapabilitySetModel],
) -> DispatchHistoryEntry:
    dispatch, capabilities = row
    return DispatchHistoryEntry(
        dispatch_id=dispatch.dispatch_id,
        predecessor_dispatch_id=dispatch.predecessor_dispatch_id,
        assignment_id=dispatch.assignment_id,
        attempt_id=dispatch.attempt_id,
        node_key=dispatch.node_key,
        status=cast(Literal["starting", "open", "closed"], dispatch.status),
        opened_reason=dispatch.opened_reason,
        closed_reason=dispatch.closed_reason,
        requested_provider=cast(
            Literal["codex", "claude", "openclaw"], dispatch.requested_provider
        ),
        resolved_provider=cast(Literal["codex", "claude", "openclaw"], dispatch.resolved_provider),
        selection_basis=cast(Literal["explicit", "default"], dispatch.provider_selection_basis),
        adapter_started_at=_as_utc_optional(dispatch.adapter_started_at),
        last_node_activity_at=_as_utc_optional(dispatch.last_node_activity_at),
        node_activity_revision=dispatch.node_activity_revision,
        effective_capabilities=effective_capability_readback(capabilities),
        created_at=_as_utc(dispatch.created_at),
        closed_at=_as_utc_optional(dispatch.closed_at),
    )


async def _read_checkpoints(
    session: AsyncSession,
    *,
    task_id: str,
    attempt_id: str | None,
) -> tuple[CheckpointHistoryEntry, ...]:
    statement = (
        select(AttemptCheckpointModel)
        .options(raiseload("*"))
        .where(AttemptCheckpointModel.task_id == task_id)
    )
    if attempt_id is not None:
        statement = statement.where(AttemptCheckpointModel.attempt_id == attempt_id)
    rows = await session.scalars(statement.order_by(AttemptCheckpointModel.recorded_at))
    return tuple(
        CheckpointHistoryEntry(
            checkpoint_id=row.checkpoint_id,
            attempt_id=row.attempt_id,
            checkpoint_kind=CheckpointKind(row.checkpoint_kind),
            outcome=CheckpointOutcome(row.outcome) if row.outcome is not None else None,
            summary=row.summary,
            recorded_at=_as_utc(row.recorded_at),
        )
        for row in rows
    )


async def _read_boundaries(
    session: AsyncSession,
    *,
    task_id: str,
    attempt_id: str | None,
) -> tuple[BoundaryHistoryEntry, ...]:
    statement = (
        select(AcceptedBoundaryModel, DispatchTurnModel.node_key)
        .join(
            DispatchTurnModel,
            DispatchTurnModel.dispatch_id == AcceptedBoundaryModel.source_dispatch_id,
        )
        .options(raiseload("*"))
        .where(AcceptedBoundaryModel.task_id == task_id)
    )
    if attempt_id is not None:
        statement = statement.where(AcceptedBoundaryModel.attempt_id == attempt_id)
    rows = await session.execute(statement.order_by(AcceptedBoundaryModel.committed_at))
    return tuple(
        BoundaryHistoryEntry(
            source_dispatch_id=boundary.source_dispatch_id,
            node_key=node_key,
            boundary=EgressBoundary(boundary.outcome),
            checkpoint_id=boundary.checkpoint_id,
            successor_dispatch_id=boundary.successor_dispatch_id,
            occurred_at=_as_utc(boundary.committed_at),
        )
        for boundary, node_key in rows
    )


def _validate_trace_query(*, scope: str, limit: int, sort: str) -> None:
    if scope not in {"current", "whole"}:
        raise invalid_request_shape_error("trace scope must be current or whole")
    if sort not in {"occurred_at_desc", "occurred_at_asc"}:
        raise invalid_request_shape_error("unknown trace sort")
    if not 1 <= limit <= 200:
        raise invalid_request_shape_error("trace limit must be between 1 and 200")


def _parse_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise invalid_request_shape_error("trace cursor must be an integer offset") from exc
    if offset < 0:
        raise invalid_request_shape_error("trace cursor must be non-negative")
    return offset


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_utc_optional(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


__all__ = ["operator_snapshot", "operator_trace"]
