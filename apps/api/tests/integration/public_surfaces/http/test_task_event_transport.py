from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import cast

import autoclaw.interfaces.http.routers.control as control_router_module
import httpx
import pytest
from autoclaw.interfaces.http.contracts.operation_failure import OperationFailure
from autoclaw.main import create_app
from autoclaw.persistence.models import TaskEventModel
from autoclaw.persistence.session import get_db_session
from autoclaw.runtime.contracts import TaskEventRecord
from autoclaw.runtime.task_events import append_task_event, encode_task_event_cursor
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import seed_runtime_scope
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


class _SessionAdapterFactory:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def __call__(self) -> SyncSessionAdapter:
        return SyncSessionAdapter(self._factory)


async def test_task_event_http_and_sse_preserve_cursor_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="task-event-http.sqlite")
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            task_a = seed_runtime_scope(connection, suffix="event-http-a")
            task_b = seed_runtime_scope(connection, suffix="event-http-b")
        events_a = [
            await _append_pause_event(factory, task_id=task_a.task_id, revision=revision)
            for revision in range(1, 4)
        ]
        event_b = await _append_pause_event(factory, task_id=task_b.task_id, revision=1)
        app = create_app(should_enable_mcp_mounts=False)

        async def session_dependency() -> AsyncIterator[AsyncSession]:
            async with SyncSessionAdapter(factory) as session:
                yield cast(AsyncSession, session)

        app.dependency_overrides[get_db_session] = session_dependency
        monkeypatch.setattr(
            control_router_module,
            "get_session_factory",
            lambda: _SessionAdapterFactory(factory),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url="http://127.0.0.1:18125",
        ) as client:
            page = await client.get(
                f"/control/tasks/{task_a.task_id}/events",
                params={
                    "cursor": encode_task_event_cursor(events_a[0].event_id),
                    "through_event_id": events_a[1].event_id,
                },
            )
            cross_task = await client.get(
                f"/control/tasks/{task_a.task_id}/events",
                params={"cursor": encode_task_event_cursor(event_b.event_id)},
            )
            cross_task_stream = await client.get(
                f"/control/tasks/{task_a.task_id}/events/stream",
                params={"cursor": encode_task_event_cursor(event_b.event_id)},
            )
            mismatched_resume = await client.get(
                f"/control/tasks/{task_a.task_id}/events/stream",
                params={"cursor": encode_task_event_cursor(events_a[0].event_id)},
                headers={"Last-Event-ID": encode_task_event_cursor(events_a[1].event_id)},
            )

        assert page.status_code == 200
        assert [item["event_id"] for item in page.json()["items"]] == [events_a[1].event_id]
        assert page.json()["through_event_id"] == events_a[1].event_id
        _assert_cursor_reset(cross_task)
        _assert_cursor_reset(cross_task_stream)
        assert mismatched_resume.status_code == 400
        assert mismatched_resume.json()["code"] == "invalid_request_shape"

        before = await _event_count(factory, task_id=task_a.task_id)
        stream = control_router_module.stream_task_event_records(
            task_id=task_a.task_id,
            cursor=encode_task_event_cursor(events_a[0].event_id),
        )
        frame = await anext(stream)
        await cast(AsyncGenerator[str, None], stream).aclose()
        after = await _event_count(factory, task_id=task_a.task_id)

        lines = frame.rstrip().splitlines()
        assert lines[:2] == [
            f"id: {events_a[1].event_id}",
            "event: task_paused",
        ]
        assert json.loads(lines[2].removeprefix("data: ")) == page.json()["items"][0]
        assert before == after == 3
    finally:
        engine.dispose()


def test_task_event_routes_declare_the_cursor_reset_response() -> None:
    openapi = create_app(should_enable_mcp_mounts=False).openapi()

    for path in (
        "/control/tasks/{task_id}/events",
        "/control/tasks/{task_id}/events/stream",
    ):
        schema = openapi["paths"][path]["get"]["responses"]["410"]["content"]["application/json"][
            "schema"
        ]
        assert schema == {"$ref": "#/components/schemas/OperationFailure"}


def test_public_operation_routes_declare_the_shared_failure_contract() -> None:
    openapi = create_app(should_enable_mcp_mounts=False).openapi()
    schemas = openapi["components"]["schemas"]

    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
    for path, path_item in openapi["paths"].items():
        if path in {"/healthz", "/readyz"}:
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            for status_code in ("400", "403", "404", "409", "422", "500"):
                schema = responses[status_code]["content"]["application/json"]["schema"]
                assert schema == {"$ref": "#/components/schemas/OperationFailure"}


async def _append_pause_event(
    factory: sessionmaker[Session],
    *,
    task_id: str,
    revision: int,
) -> TaskEventRecord:
    async with SyncSessionAdapter(factory) as session:
        event = await append_task_event(
            cast(AsyncSession, session),
            task_id=task_id,
            event_type="task_paused",
            event_source="control_api",
            actor_ref="local_operator",
            payload={
                "pause_reason": "paused_by_operator",
                "control_revision": revision,
                "actor_ref": "local_operator",
                "summary": f"Pause event {revision}.",
            },
        )
        await session.commit()
        return event


async def _event_count(factory: sessionmaker[Session], *, task_id: str) -> int:
    async with SyncSessionAdapter(factory) as session:
        count = await session.scalar(
            select(func.count())
            .select_from(TaskEventModel)
            .where(TaskEventModel.task_id == task_id)
        )
    return int(count or 0)


def _assert_cursor_reset(response: httpx.Response) -> None:
    assert response.status_code == 410
    failure = OperationFailure.model_validate(response.json())
    assert failure.code == "cursor_reset_required"
    assert failure.retryable is False
    assert failure.suggested_next_step is not None
