from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

import banksia.interfaces.http.support as support_module
import banksia.main as main_module
from banksia.config import Environment, Settings
from banksia.interfaces.http.support import create_support_app
from banksia.main import create_app
from banksia.persistence.session import get_db_session
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.task_events import (
    encode_task_event_cursor,
    list_task_events,
)
from tests.helpers.executor_harness import AsyncSessionFactory, seeded_async_executor

TOKEN = "support-test-token-" + "x" * 40


class _SupportStreamEndpoint(Protocol):
    async def __call__(
        self,
        *,
        task_id: str,
        cursor: str | None,
        last_event_id: str | None,
    ) -> StreamingResponse: ...


async def test_support_routes_are_disabled_without_a_credential() -> None:
    app = create_app(should_enable_mcp_mounts=False)

    assert app.state.support_app is None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.get("/support/tasks")

    assert response.status_code == 404
    assert not any(path.startswith("/support") for path in app.openapi()["paths"])


async def test_support_is_bearer_protected_no_origin_and_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        env=Environment.TEST,
        support_bearer_token=SecretStr(TOKEN),
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    async with seeded_async_executor(tmp_path, suffix="support-admission") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        app = create_app(should_enable_mcp_mounts=False)
        support_app = app.state.support_app
        assert support_app is not None

        async def session_dependency() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        support_app.dependency_overrides[get_db_session] = session_dependency
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url="http://127.0.0.1:18125",
        ) as client:
            missing = await client.get("/support/tasks")
            browser = await client.get(
                "/support/tasks",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Origin": "http://127.0.0.1:5173",
                },
            )
            admitted = await client.get(
                "/support/tasks",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            snapshot = await client.get(
                f"/support/tasks/{ids.task_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            openapi = await client.get(
                "/support/openapi.json",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert browser.status_code == 403
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["items"][0]["task_id"] == ids.task_id
    assert snapshot.status_code == 200, snapshot.text
    assert "current_team_revision_id" in snapshot.json()["task"]
    assert openapi.status_code == 200, openapi.text
    assert set(openapi.json()["paths"]) == {
        "/support/openapi.json",
        "/support/tasks",
        "/support/tasks/{task_id}",
        "/support/tasks/{task_id}/trace",
        "/support/tasks/{task_id}/events",
        "/support/tasks/{task_id}/events/stream",
    }
    serialized = json.dumps(
        {
            "settings": settings.model_dump(mode="json"),
            "settings_repr": repr(settings),
            "openapi": openapi.json(),
            "snapshot": snapshot.json(),
        },
        sort_keys=True,
    )
    assert TOKEN not in serialized
    assert "support_bearer_token" not in settings.model_dump(mode="json")
    assert TOKEN not in repr(support_app.state._state)


def test_support_openapi_declares_security_on_every_operation() -> None:
    app = create_support_app(credential=TOKEN)
    document = app.openapi()

    assert set(document["paths"]) == {
        "/support/openapi.json",
        "/support/tasks",
        "/support/tasks/{task_id}",
        "/support/tasks/{task_id}/trace",
        "/support/tasks/{task_id}/events",
        "/support/tasks/{task_id}/events/stream",
    }
    assert "HTTPBearer" in document["components"]["securitySchemes"]
    for path_item in document["paths"].values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "responses" in operation:
                assert operation["security"] == [{"HTTPBearer": []}]


async def test_support_trace_is_typed_bounded_filterable_and_keyset_stable(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="support-trace") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with _support_client(session_factory) as client:
            baseline = await client.get(
                f"/tasks/{ids.task_id}/trace",
                params={"limit": 200, "sort": "occurred_at_desc"},
                headers=_support_headers(),
            )
            first = await client.get(
                f"/tasks/{ids.task_id}/trace",
                params={"limit": 1, "sort": "occurred_at_desc"},
                headers=_support_headers(),
            )
            assert baseline.status_code == 200, baseline.text
            assert first.status_code == 200, first.text
            assert first.json()["next_cursor"] is not None

            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="checkpoint",
                arguments={"summary": "Concurrent trace insert marker."},
            )

            desc_entries = list(first.json()["entries"])
            cursor = first.json()["next_cursor"]
            while cursor is not None:
                page = await client.get(
                    f"/tasks/{ids.task_id}/trace",
                    params={
                        "cursor": cursor,
                        "limit": 1,
                        "sort": "occurred_at_desc",
                    },
                    headers=_support_headers(),
                )
                assert page.status_code == 200, page.text
                desc_entries.extend(page.json()["entries"])
                cursor = page.json()["next_cursor"]

            ascending = await client.get(
                f"/tasks/{ids.task_id}/trace",
                params={"limit": 200, "sort": "occurred_at_asc"},
                headers=_support_headers(),
            )
            filtered = await client.get(
                f"/tasks/{ids.task_id}/trace",
                params={"q": "Concurrent trace insert marker", "limit": 5},
                headers=_support_headers(),
            )

    baseline_entries = baseline.json()["entries"]
    assert len(baseline_entries) > 1
    assert [_trace_entry_key(entry) for entry in desc_entries] == [
        _trace_entry_key(entry) for entry in baseline_entries
    ]
    assert ascending.status_code == 200, ascending.text
    ascending_entries = ascending.json()["entries"]
    assert len(ascending_entries) == len(baseline_entries) + 1
    assert [_trace_timestamp(entry) for entry in ascending_entries] == sorted(
        _trace_timestamp(entry) for entry in ascending_entries
    )
    assert {entry["kind"] for entry in ascending_entries} >= {"dispatch", "checkpoint"}
    assert filtered.status_code == 200, filtered.text
    assert len(filtered.json()["entries"]) == 1
    assert filtered.json()["entries"][0]["kind"] == "checkpoint"
    assert filtered.json()["entries"][0]["summary"] == "Concurrent trace insert marker."


async def test_support_sse_backfill_reconnect_conflict_and_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="support-sse") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        for summary in ("First SSE backfill event.", "Second SSE reconnect event."):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="checkpoint",
                arguments={"summary": summary},
            )
        async with session_factory() as session:
            events = (
                await list_task_events(
                    session,
                    task_id=ids.task_id,
                    limit=100,
                )
            ).items
        assert len(events) >= 2
        reconnect_cursor = encode_task_event_cursor(events[0].event_id)
        next_cursor = encode_task_event_cursor(events[1].event_id)

        monkeypatch.setattr(
            support_module,
            "get_session_factory",
            lambda: session_factory,
        )
        support_app = create_support_app(credential=TOKEN)
        endpoint = _support_stream_endpoint(support_app)
        response = await endpoint(
            task_id=ids.task_id,
            cursor=None,
            last_event_id=reconnect_cursor,
        )
        stream = cast(AsyncGenerator[str, None], response.body_iterator)
        frame = await anext(stream)
        await stream.aclose()

        unknown_cursor = encode_task_event_cursor("task-event.does-not-exist")
        with pytest.raises(HTTPException) as conflict:
            await endpoint(
                task_id=ids.task_id,
                cursor=reconnect_cursor,
                last_event_id=next_cursor,
            )
        with pytest.raises(HTTPException) as reset:
            await endpoint(
                task_id=ids.task_id,
                cursor=unknown_cursor,
                last_event_id=None,
            )

    assert frame.startswith(f"id: {next_cursor}\nevent: task_event\n")
    assert f'"event_id":"{events[1].event_id}"' in frame
    assert conflict.value.status_code == 400
    assert reset.value.status_code == 410


@asynccontextmanager
async def _support_client(
    session_factory: AsyncSessionFactory,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_support_app(credential=TOKEN)

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = session_dependency
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        yield client


def _support_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _support_stream_endpoint(app: FastAPI) -> _SupportStreamEndpoint:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == "/tasks/{task_id}/events/stream":
            endpoint = cast(
                Callable[..., Awaitable[StreamingResponse]],
                route.endpoint,
            )
            return cast(_SupportStreamEndpoint, endpoint)
    raise AssertionError("support stream route is not registered")


def _trace_entry_key(entry: dict[str, object]) -> tuple[str, str]:
    kind = str(entry["kind"])
    identifier = {
        "dispatch": "dispatch_id",
        "checkpoint": "checkpoint_id",
        "boundary": "source_dispatch_id",
    }[kind]
    return kind, str(entry[identifier])


def _trace_timestamp(entry: dict[str, object]) -> datetime:
    timestamp_field = {
        "dispatch": "created_at",
        "checkpoint": "recorded_at",
        "boundary": "occurred_at",
    }[str(entry["kind"])]
    return datetime.fromisoformat(str(entry[timestamp_field]))
