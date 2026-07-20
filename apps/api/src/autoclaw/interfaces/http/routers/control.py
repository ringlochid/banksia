from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.interfaces.http.contracts.operation_failure import OperationFailure
from autoclaw.interfaces.http.dependencies import (
    read_control_actor_ref,
    read_dispatch_opening_dependencies,
    read_runtime_effect_publisher,
)
from autoclaw.interfaces.http.errors import raise_runtime_exception
from autoclaw.persistence.session import get_db_session, get_session_factory
from autoclaw.runtime.command_run.service import (
    cancel_command_run,
    list_command_runs,
    read_command_run,
    read_command_run_log,
)
from autoclaw.runtime.contracts import (
    CommandRunCancelResponse,
    CommandRunListResponse,
    CommandRunLogReadResponse,
    CommandRunRecord,
    HumanRequestListResponse,
    HumanRequestResolveRequest,
    HumanRequestResolveResponse,
    OperatorFlowSnapshotResponse,
    OperatorFlowTraceQuery,
    OperatorFlowTraceResponse,
    RuntimeFlowControlRequest,
    RuntimeFlowPauseResponse,
    RuntimeFlowRead,
    TaskEventListQuery,
    TaskEventListResponse,
    TaskEventRecord,
)
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.errors import invalid_request_shape_error
from autoclaw.runtime.flow.service import (
    cancel_runtime_flow,
    continue_runtime_flow,
    pause_runtime_flow,
    runtime_flow_read,
)
from autoclaw.runtime.human_request.service import list_human_requests, resolve_human_request
from autoclaw.runtime.observability import operator_snapshot, operator_trace
from autoclaw.runtime.post_commit import RuntimeEffectPublisher
from autoclaw.runtime.task_events import (
    decode_task_event_cursor,
    latest_task_event,
    list_task_events,
)

router = APIRouter(prefix="/control", tags=["control"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type ControlActorRefDep = Annotated[str | None, Depends(read_control_actor_ref)]
type RuntimeEffectPublisherDep = Annotated[
    RuntimeEffectPublisher | None,
    Depends(read_runtime_effect_publisher),
]
type DispatchOpeningDependenciesDep = Annotated[
    DispatchOpeningDependencies,
    Depends(read_dispatch_opening_dependencies),
]
type OperatorTraceParams = Annotated[OperatorFlowTraceQuery, Query()]
type TaskEventListParams = Annotated[TaskEventListQuery, Query()]
type CommandRunCursor = Annotated[str | None, Query(min_length=1)]
type CommandRunLimit = Annotated[int, Query(ge=1, le=200)]
type TaskEventStreamCursor = Annotated[str | None, Query(min_length=1)]
type LastEventIdHeader = Annotated[str | None, Header(alias="Last-Event-ID", min_length=1)]

_TASK_EVENT_STREAM_POLL_SECONDS = 0.1
_TASK_EVENT_STREAM_PAGE_SIZE = 100


@router.get("/tasks/{task_id}", response_model=RuntimeFlowRead)
async def get_control_task(
    task_id: str,
    session: DBSession,
) -> RuntimeFlowRead:
    try:
        return await runtime_flow_read(session, task_id)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post("/tasks/{task_id}/pause", response_model=RuntimeFlowPauseResponse)
async def pause_control_task(
    task_id: str,
    request: RuntimeFlowControlRequest,
    session: DBSession,
    actor_ref: ControlActorRefDep,
    runtime_effect_publisher: RuntimeEffectPublisherDep,
) -> RuntimeFlowPauseResponse:
    try:
        return await pause_runtime_flow(
            session,
            task_id,
            expected_active_flow_revision_id=request.expected_active_flow_revision_id,
            expected_control_revision=request.expected_control_revision,
            actor_ref=actor_ref,
            runtime_effect_publisher=runtime_effect_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post("/tasks/{task_id}/continue", response_model=RuntimeFlowRead)
async def continue_control_task(
    task_id: str,
    request: RuntimeFlowControlRequest,
    session: DBSession,
    actor_ref: ControlActorRefDep,
    dependencies: DispatchOpeningDependenciesDep,
) -> RuntimeFlowRead:
    try:
        return await continue_runtime_flow(
            session,
            task_id,
            expected_active_flow_revision_id=request.expected_active_flow_revision_id,
            expected_control_revision=request.expected_control_revision,
            dependencies=dependencies,
            actor_ref=actor_ref,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post("/tasks/{task_id}/cancel", response_model=RuntimeFlowRead)
async def cancel_control_task(
    task_id: str,
    request: RuntimeFlowControlRequest,
    session: DBSession,
    actor_ref: ControlActorRefDep,
    runtime_effect_publisher: RuntimeEffectPublisherDep,
) -> RuntimeFlowRead:
    try:
        return await cancel_runtime_flow(
            session,
            task_id,
            expected_active_flow_revision_id=request.expected_active_flow_revision_id,
            expected_control_revision=request.expected_control_revision,
            actor_ref=actor_ref,
            runtime_effect_publisher=runtime_effect_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/tasks/{task_id}/snapshot", response_model=OperatorFlowSnapshotResponse)
async def get_control_snapshot(
    task_id: str,
    session: DBSession,
) -> OperatorFlowSnapshotResponse:
    try:
        return await operator_snapshot(session, task_id)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/tasks/{task_id}/trace", response_model=OperatorFlowTraceResponse)
async def get_control_trace(
    task_id: str,
    session: DBSession,
    query: OperatorTraceParams,
) -> OperatorFlowTraceResponse:
    try:
        return await operator_trace(
            session,
            task_id,
            scope=query.scope,
            q=query.q,
            cursor=query.cursor,
            limit=query.limit,
            sort=query.sort,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/tasks/{task_id}/human-requests", response_model=HumanRequestListResponse)
async def get_control_human_requests(
    task_id: str,
    session: DBSession,
) -> HumanRequestListResponse:
    try:
        return await list_human_requests(session, task_id=task_id)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post(
    "/tasks/{task_id}/human-requests/{request_id}/resolve",
    response_model=HumanRequestResolveResponse,
)
async def resolve_control_human_request(
    task_id: str,
    request_id: str,
    resolve_request: HumanRequestResolveRequest,
    session: DBSession,
    actor_ref: ControlActorRefDep,
    runtime_effect_publisher: RuntimeEffectPublisherDep,
) -> HumanRequestResolveResponse:
    try:
        return await resolve_human_request(
            session,
            task_id=task_id,
            request_id=request_id,
            request=resolve_request,
            actor_ref=actor_ref,
            runtime_effect_publisher=runtime_effect_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/tasks/{task_id}/command-runs", response_model=CommandRunListResponse)
async def get_control_command_runs(
    task_id: str,
    session: DBSession,
    cursor: CommandRunCursor = None,
    limit: CommandRunLimit = 100,
) -> CommandRunListResponse:
    try:
        return await list_command_runs(
            session,
            task_id=task_id,
            cursor=cursor,
            limit=limit,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/tasks/{task_id}/command-runs/{run_id}", response_model=CommandRunRecord)
async def get_control_command_run(
    task_id: str,
    run_id: str,
    session: DBSession,
) -> CommandRunRecord:
    try:
        return await read_command_run(session, task_id=task_id, run_id=run_id)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get(
    "/tasks/{task_id}/command-runs/{run_id}/log",
    response_model=CommandRunLogReadResponse,
)
async def get_control_command_run_log(
    task_id: str,
    run_id: str,
    session: DBSession,
) -> CommandRunLogReadResponse:
    try:
        return await read_command_run_log(session, task_id=task_id, run_id=run_id)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post(
    "/tasks/{task_id}/command-runs/{run_id}/cancel",
    response_model=CommandRunCancelResponse,
)
async def cancel_control_command_run(
    task_id: str,
    run_id: str,
    session: DBSession,
    actor_ref: ControlActorRefDep,
    runtime_effect_publisher: RuntimeEffectPublisherDep,
) -> CommandRunCancelResponse:
    try:
        return await cancel_command_run(
            session,
            task_id=task_id,
            run_id=run_id,
            actor_ref=actor_ref,
            runtime_effect_publisher=runtime_effect_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get(
    "/tasks/{task_id}/events",
    response_model=TaskEventListResponse,
    responses={410: {"model": OperationFailure}},
)
async def get_control_task_events(
    task_id: str,
    session: DBSession,
    query: TaskEventListParams,
) -> TaskEventListResponse:
    try:
        await runtime_flow_read(session, task_id)
        return await list_task_events(
            session,
            task_id=task_id,
            cursor=query.cursor,
            limit=query.limit,
            through_event_id=query.through_event_id,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get(
    "/tasks/{task_id}/events/stream",
    responses={410: {"model": OperationFailure}},
)
async def stream_control_task_events(
    task_id: str,
    cursor: TaskEventStreamCursor = None,
    last_event_id: LastEventIdHeader = None,
) -> StreamingResponse:
    try:
        async with get_session_factory()() as session:
            await runtime_flow_read(session, task_id)
            resume_cursor = _resolve_task_event_stream_cursor(cursor, last_event_id)
            stream_cursor = await _validated_task_event_stream_cursor(
                session,
                task_id=task_id,
                resume_cursor=resume_cursor,
            )
        return StreamingResponse(
            stream_task_event_records(task_id=task_id, cursor=stream_cursor),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


async def stream_task_event_records(
    *,
    task_id: str,
    cursor: str | None,
) -> AsyncIterator[str]:
    current_cursor = cursor
    while True:
        async with get_session_factory()() as session:
            event_page = await list_task_events(
                session,
                task_id=task_id,
                cursor=current_cursor,
                limit=_TASK_EVENT_STREAM_PAGE_SIZE,
            )
        for event in event_page.items:
            yield _render_task_event_sse(event)
            current_cursor = event.event_id
        await asyncio.sleep(_TASK_EVENT_STREAM_POLL_SECONDS)


def _resolve_task_event_stream_cursor(
    query_cursor: str | None,
    last_event_id: str | None,
) -> str | None:
    if query_cursor is None:
        return last_event_id
    if last_event_id is None:
        return query_cursor
    if decode_task_event_cursor(query_cursor) != decode_task_event_cursor(last_event_id):
        raise invalid_request_shape_error(
            "cursor query parameter and Last-Event-ID header refer to different task events"
        )
    return query_cursor


async def _validated_task_event_stream_cursor(
    session: AsyncSession,
    *,
    task_id: str,
    resume_cursor: str | None,
) -> str | None:
    if resume_cursor is not None:
        await list_task_events(
            session,
            task_id=task_id,
            cursor=resume_cursor,
            limit=1,
        )
        return resume_cursor
    head = await latest_task_event(session, task_id=task_id)
    if head is None:
        return None
    return head.event_id


def _render_task_event_sse(event: TaskEventRecord) -> str:
    event_json = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.event_id}\nevent: {event.event_type.value}\ndata: {event_json}\n\n"
