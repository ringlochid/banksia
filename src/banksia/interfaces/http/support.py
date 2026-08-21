from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Security, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.interfaces.http.errors import raise_runtime_exception
from banksia.persistence.session import get_db_session, get_session_factory
from banksia.runtime.contracts.support import (
    SupportTaskEventPage,
    SupportTaskSearchResponse,
    SupportTaskSnapshot,
    SupportTaskTracePage,
    SupportTaskTraceQuery,
)
from banksia.runtime.contracts.task_events import TaskEventRecord
from banksia.runtime.errors import invalid_request_shape_error
from banksia.runtime.observability import support_task_snapshot, support_task_trace
from banksia.runtime.task_control.service import list_runtime_tasks, runtime_task_read
from banksia.runtime.task_events import (
    decode_task_event_cursor,
    encode_task_event_cursor,
    latest_task_event,
    list_task_events,
)

type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type TraceParams = Annotated[SupportTaskTraceQuery, Query()]
type EventCursor = Annotated[str | None, Query(min_length=1)]
type EventLimit = Annotated[int, Query(ge=1, le=500)]
type LastEventId = Annotated[str | None, Header(alias="Last-Event-ID", min_length=1)]

_SUPPORT_MOUNT_PATH = "/support"
_STREAM_POLL_SECONDS = 0.1
_STREAM_PAGE_SIZE = 100
_bearer_scheme = HTTPBearer(auto_error=False)


def create_support_app(
    *,
    credential: SecretStr | str,
    version: str = "0.0.0",
) -> FastAPI:
    raw_credential = (
        credential.get_secret_value() if isinstance(credential, SecretStr) else credential
    )
    if len(raw_credential) < 32:
        raise ValueError("support credential must contain at least 32 characters")
    app = FastAPI(
        title="Oh My Subagents Support API",
        version=version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(_require_support_admission)],
    )
    app.state.support_credential_digest = _credential_digest(raw_credential)
    _register_support_routes(app)
    _register_support_exception_handlers(app)
    _prefix_support_openapi(app)
    return app


async def _require_support_admission(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_bearer_scheme),
    ],
) -> None:
    if request.headers.getlist("origin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="support access does not accept browser Origin requests",
        )
    expected = getattr(request.app.state, "support_credential_digest", b"")
    supplied = (
        credentials.credentials
        if credentials is not None and credentials.scheme.casefold() == "bearer"
        else ""
    )
    if not expected or not hmac.compare_digest(
        _credential_digest(supplied),
        expected,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="support authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _stream_support_event_records(
    *,
    task_id: str,
    cursor: str | None,
) -> AsyncGenerator[str, None]:
    current_cursor = cursor
    while True:
        async with get_session_factory()() as session:
            page = await list_task_events(
                session,
                task_id=task_id,
                cursor=current_cursor,
                limit=_STREAM_PAGE_SIZE,
            )
        for event in page.items:
            yield _render_support_event(event)
            current_cursor = encode_task_event_cursor(event.event_id)
        await asyncio.sleep(_STREAM_POLL_SECONDS)


def _render_support_event(event: TaskEventRecord) -> str:
    payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    cursor = encode_task_event_cursor(event.event_id)
    return f"id: {cursor}\nevent: task_event\ndata: {payload}\n\n"


def _register_support_routes(app: FastAPI) -> None:
    _register_support_openapi_route(app)
    _register_support_task_search_route(app)
    _register_support_task_snapshot_route(app)
    _register_support_task_trace_route(app)
    _register_support_task_event_routes(app)


def _register_support_openapi_route(app: FastAPI) -> None:
    @app.get("/openapi.json", response_model=dict[str, Any], tags=["support"])
    async def support_openapi() -> dict[str, Any]:
        return app.openapi()


def _register_support_task_search_route(app: FastAPI) -> None:
    @app.get("/tasks", response_model=SupportTaskSearchResponse, tags=["support"])
    async def search_support_tasks(
        session: DBSession,
        q: str | None = None,
        cursor: str | None = None,
        status_filter: Annotated[str, Query(alias="status")] = "any",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> SupportTaskSearchResponse:
        try:
            page = await list_runtime_tasks(
                session,
                q=q,
                cursor=cursor,
                status=status_filter,
                limit=limit,
            )
            return SupportTaskSearchResponse(
                items=page.items,
                next_cursor=page.next_cursor,
            )
        except Exception as exc:  # pragma: no cover - thin transport mapping
            raise_runtime_exception(exc)


def _register_support_task_snapshot_route(app: FastAPI) -> None:
    @app.get(
        "/tasks/{task_id}",
        response_model=SupportTaskSnapshot,
        tags=["support"],
    )
    async def get_support_task(
        task_id: str,
        session: DBSession,
    ) -> SupportTaskSnapshot:
        try:
            return await support_task_snapshot(session, task_id)
        except Exception as exc:  # pragma: no cover - thin transport mapping
            raise_runtime_exception(exc)


def _register_support_task_trace_route(app: FastAPI) -> None:
    @app.get(
        "/tasks/{task_id}/trace",
        response_model=SupportTaskTracePage,
        tags=["support"],
    )
    async def get_support_task_trace(
        task_id: str,
        session: DBSession,
        query: TraceParams,
    ) -> SupportTaskTracePage:
        try:
            return await support_task_trace(
                session,
                task_id,
                q=query.q,
                cursor=query.cursor,
                limit=query.limit,
                sort=query.sort,
            )
        except Exception as exc:  # pragma: no cover - thin transport mapping
            raise_runtime_exception(exc)


def _register_support_task_event_routes(app: FastAPI) -> None:
    @app.get(
        "/tasks/{task_id}/events",
        response_model=SupportTaskEventPage,
        tags=["support"],
    )
    async def get_support_task_events(
        task_id: str,
        session: DBSession,
        cursor: EventCursor = None,
        limit: EventLimit = 100,
    ) -> SupportTaskEventPage:
        try:
            await runtime_task_read(session, task_id)
            page = await list_task_events(
                session,
                task_id=task_id,
                cursor=cursor,
                limit=limit,
            )
            return SupportTaskEventPage(
                task_id=task_id,
                items=page.items,
                next_cursor=page.next_cursor,
            )
        except Exception as exc:  # pragma: no cover - thin transport mapping
            raise_runtime_exception(exc)

    @app.get("/tasks/{task_id}/events/stream", tags=["support"])
    async def stream_support_task_events(
        task_id: str,
        cursor: EventCursor = None,
        last_event_id: LastEventId = None,
    ) -> StreamingResponse:
        try:
            resume_cursor = _resolve_support_stream_cursor(cursor, last_event_id)
            async with get_session_factory()() as session:
                await runtime_task_read(session, task_id)
                stream_cursor = await _support_stream_cursor(
                    session,
                    task_id=task_id,
                    cursor=resume_cursor,
                )
            return StreamingResponse(
                _stream_support_event_records(task_id=task_id, cursor=stream_cursor),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        except Exception as exc:  # pragma: no cover - thin transport mapping
            raise_runtime_exception(exc)


async def _support_stream_cursor(
    session: AsyncSession,
    *,
    task_id: str,
    cursor: str | None,
) -> str | None:
    if cursor is not None:
        decode_task_event_cursor(cursor)
        await list_task_events(session, task_id=task_id, cursor=cursor, limit=1)
        return cursor
    head = await latest_task_event(session, task_id=task_id)
    return encode_task_event_cursor(head.event_id) if head is not None else None


def _resolve_support_stream_cursor(
    query_cursor: str | None,
    last_event_id: str | None,
) -> str | None:
    if query_cursor is None:
        return last_event_id
    if last_event_id is None:
        return query_cursor
    if decode_task_event_cursor(query_cursor) != decode_task_event_cursor(last_event_id):
        raise invalid_request_shape_error(
            "The cursor and Last-Event-ID refer to different update positions."
        )
    return query_cursor


def _credential_digest(credential: str) -> bytes:
    return hashlib.sha256(credential.encode("utf-8")).digest()


def _prefix_support_openapi(app: FastAPI) -> None:
    raw_openapi = app.openapi

    def mounted_openapi() -> dict[str, Any]:
        cached_schema = getattr(app.state, "mounted_openapi_schema", None)
        if cached_schema is not None:
            return cast(dict[str, Any], cached_schema)
        schema = raw_openapi()
        schema["paths"] = {
            f"{_SUPPORT_MOUNT_PATH}{path}": operation
            for path, operation in schema.get("paths", {}).items()
        }
        app.state.mounted_openapi_schema = schema
        return schema

    app.openapi = mounted_openapi  # type: ignore[method-assign]


def _register_support_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def support_http_exception(
        _request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc.detail)},
            headers=exc.headers,
        )


__all__ = [
    "create_support_app",
]
