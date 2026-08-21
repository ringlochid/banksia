from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.interfaces.http.contracts.operation_failure import OperationFailure
from oh_my_subagents.interfaces.http.errors import raise_runtime_exception
from oh_my_subagents.persistence.session import get_db_session, get_session_factory
from oh_my_subagents.runtime.contracts.task import TaskActivity, TaskActivityPage
from oh_my_subagents.runtime.product.activities import list_task_activities, project_task_events
from oh_my_subagents.runtime.task_control.service import runtime_task_read
from oh_my_subagents.runtime.task_events import (
    encode_task_event_cursor,
    latest_task_event,
    list_task_events,
)

router = APIRouter(tags=["task-activity"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type ActivityCursor = Annotated[str | None, Query(min_length=1)]
type ActivityLimit = Annotated[int, Query(ge=1, le=200)]
type LastEventId = Annotated[str | None, Header(alias="Last-Event-ID", min_length=1)]

_STREAM_POLL_SECONDS = 0.1
_STREAM_PAGE_SIZE = 100


@router.get(
    "/tasks/{task_id}/activities",
    response_model=TaskActivityPage,
    responses={410: {"model": OperationFailure}},
)
async def get_task_activities(
    task_id: str,
    session: DBSession,
    cursor: ActivityCursor = None,
    limit: ActivityLimit = 50,
) -> TaskActivityPage:
    try:
        await runtime_task_read(session, task_id)
        return await list_task_activities(
            session,
            task_id=task_id,
            cursor=cursor,
            limit=limit,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


@router.get(
    "/tasks/{task_id}/activities/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            }
        },
        410: {"model": OperationFailure},
    },
)
async def stream_task_activities(
    task_id: str,
    cursor: ActivityCursor = None,
    last_event_id: LastEventId = None,
) -> StreamingResponse:
    try:
        resume_cursor = _resolve_stream_cursor(cursor, last_event_id)
        async with get_session_factory()() as session:
            await runtime_task_read(session, task_id)
            stream_cursor = await _validated_stream_cursor(
                session,
                task_id=task_id,
                cursor=resume_cursor,
            )
        return StreamingResponse(
            stream_task_activity_records(task_id=task_id, cursor=stream_cursor),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


async def stream_task_activity_records(
    *,
    task_id: str,
    cursor: str | None,
) -> AsyncIterator[str]:
    current_cursor = cursor
    while True:
        async with get_session_factory()() as session:
            page = await list_task_events(
                session,
                task_id=task_id,
                cursor=current_cursor,
                limit=_STREAM_PAGE_SIZE,
            )
            projected = await project_task_events(session, page.items)
            frames = []
            for event in page.items:
                activity = projected.get(event.event_id)
                frames.append(
                    render_activity_frame(activity)
                    if activity is not None
                    else render_task_changed_frame(encode_task_event_cursor(event.event_id))
                )
        for event, frame in zip(page.items, frames, strict=True):
            yield frame
            current_cursor = encode_task_event_cursor(event.event_id)
        await asyncio.sleep(_STREAM_POLL_SECONDS)


def render_activity_frame(activity: TaskActivity) -> str:
    payload = json.dumps(activity.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {activity.id}\nevent: activity\ndata: {payload}\n\n"


def render_task_changed_frame(cursor: str) -> str:
    return f"id: {cursor}\nevent: task_changed\ndata: {{}}\n\n"


def _resolve_stream_cursor(
    query_cursor: str | None,
    last_event_id: str | None,
) -> str | None:
    return last_event_id if last_event_id is not None else query_cursor


async def _validated_stream_cursor(
    session: AsyncSession,
    *,
    task_id: str,
    cursor: str | None,
) -> str | None:
    if cursor is not None:
        await list_task_events(session, task_id=task_id, cursor=cursor, limit=1)
        return cursor
    head = await latest_task_event(session, task_id=task_id)
    return encode_task_event_cursor(head.event_id) if head is not None else None


__all__ = [
    "render_activity_frame",
    "render_task_changed_frame",
    "router",
    "stream_task_activity_records",
]
