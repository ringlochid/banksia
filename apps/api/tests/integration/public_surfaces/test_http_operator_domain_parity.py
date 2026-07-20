from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, cast

import autoclaw.interfaces.mcp.operator.runtime_tools as runtime_tools
import autoclaw.persistence.session_operations as session_operations
import httpx
import pytest
from autoclaw.interfaces.mcp.operator.server import (
    OperatorEffectPublishers,
    create_operator_mcp_server,
)
from autoclaw.main import create_app
from autoclaw.persistence.models import CommandRunModel, DispatchTurnModel, HumanRequestModel
from autoclaw.persistence.session import get_db_session
from autoclaw.runtime.contracts import (
    CommandRunCancelResponse,
    HumanRequestResolveResponse,
    RuntimeFlowPauseResponse,
    RuntimeFlowRead,
)
from autoclaw.runtime.flow.service import runtime_flow_read
from autoclaw.runtime.node_operations import NodeOperationScope
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    CommandRunCancellationRequested,
    HumanRequestTerminal,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)

type Surface = Literal["http", "operator_mcp"]


async def test_http_and_operator_mcp_share_registry_and_runtime_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="public-read-parity") as (
        _executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        monkeypatch.setattr(
            session_operations,
            "get_session_factory",
            lambda: session_factory,
        )
        server = create_operator_mcp_server()
        async with _http_client(session_factory) as client:
            http_flow = await client.get(f"/control/tasks/{ids.task_id}")
            http_snapshot = await client.get(f"/control/tasks/{ids.task_id}/snapshot")
            http_trace = await client.get(f"/control/tasks/{ids.task_id}/trace")

        mcp_flow = await server.call_tool("get_runtime_task", {"task_id": ids.task_id})
        mcp_snapshot = await server.call_tool("get_operator_snapshot", {"task_id": ids.task_id})
        mcp_trace = await server.call_tool("get_operator_trace", {"task_id": ids.task_id})

    assert http_flow.status_code == 200
    assert http_snapshot.status_code == 200
    assert http_trace.status_code == 200
    assert (
        RuntimeFlowRead.model_validate(_mcp_payload(mcp_flow)).model_dump(mode="json")
        == http_flow.json()
    )
    assert _mcp_payload(mcp_snapshot) == http_snapshot.json()
    assert _mcp_payload(mcp_trace) == http_trace.json()


@pytest.mark.parametrize("surface", ("http", "operator_mcp"))
async def test_http_and_operator_mcp_pause_the_same_controller_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: Surface,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix=f"pause-parity-{surface}") as (
        _executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        current = await _read_flow(session_factory, ids.task_id)
        payload = {
            "task_id": ids.task_id,
            "expected_active_flow_revision_id": current.active_flow_revision_id,
            "expected_control_revision": current.control_revision,
        }
        result = await _call_pause(
            surface,
            session_factory,
            monkeypatch,
            publisher,
            payload,
        )
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

    assert result.flow.status.value == "paused"
    assert result.flow.control_revision == current.control_revision + 1
    assert dispatch is not None and dispatch.closed_reason == "paused"


@pytest.mark.parametrize("surface", ("http", "operator_mcp"))
async def test_http_and_operator_mcp_resolve_the_same_human_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: Surface,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix=f"human-parity-{surface}") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        opened = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="open_human_request",
            arguments={
                "request": {
                    "kind": "direction",
                    "summary": "Choose one public-surface answer.",
                    "items": [
                        {
                            "id": "direction",
                            "prompt": "Which answer?",
                            "options": [{"id": "a", "title": "A"}],
                        }
                    ],
                }
            },
        )
        request_id = str(opened.model_dump()["request_id"])
        result = await _call_human_resolve(
            surface,
            session_factory,
            monkeypatch,
            publisher,
            task_id=ids.task_id,
            request_id=request_id,
        )
        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)

    assert result.resolution.resolution_kind.value == "answered"
    assert source is not None and source.status == "resolved"
    assert publisher.signals == (HumanRequestTerminal(request_id),)


@pytest.mark.parametrize("surface", ("http", "operator_mcp"))
async def test_http_and_operator_mcp_request_the_same_command_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: Surface,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix=f"command-parity-{surface}") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        opened = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="start_command_run",
            arguments={
                "request": {
                    "command": {"kind": "argv", "argv": ["python", "-V"]},
                    "summary": "Create one cancellable public-surface command.",
                }
            },
        )
        run_id = str(opened.model_dump()["run_id"])
        result = await _call_command_cancel(
            surface,
            session_factory,
            monkeypatch,
            publisher,
            task_id=ids.task_id,
            run_id=run_id,
        )
        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)

    assert result.run.state.value == "cancellation_requested"
    assert source is not None and source.state == "cancellation_requested"
    assert publisher.signals == (
        CommandRunCancellationRequested(run_id, source.ownership_revision),
    )


async def _call_pause(
    surface: Surface,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    publisher: CapturedRuntimeEffectPublisher,
    payload: dict[str, object],
) -> RuntimeFlowPauseResponse:
    if surface == "http":
        async with _http_client(session_factory, publisher=publisher) as client:
            response = await client.post(
                f"/control/tasks/{payload['task_id']}/pause",
                json={key: value for key, value in payload.items() if key != "task_id"},
            )
        assert response.status_code == 200
        return RuntimeFlowPauseResponse.model_validate(response.json())
    _patch_mcp_sessions(monkeypatch, session_factory)
    result = await create_operator_mcp_server(
        effect_publishers=OperatorEffectPublishers(runtime_effect_publisher=publisher)
    ).call_tool("pause_task", payload)
    return RuntimeFlowPauseResponse.model_validate(_mcp_payload(result))


async def _call_human_resolve(
    surface: Surface,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    publisher: CapturedRuntimeEffectPublisher,
    *,
    task_id: str,
    request_id: str,
) -> HumanRequestResolveResponse:
    if surface == "http":
        async with _http_client(session_factory, publisher=publisher) as client:
            response = await client.post(
                f"/control/tasks/{task_id}/human-requests/{request_id}/resolve",
                json={"item_responses": {"direction": "a"}},
            )
        assert response.status_code == 200
        return HumanRequestResolveResponse.model_validate(response.json())
    _patch_mcp_sessions(monkeypatch, session_factory)
    result = await create_operator_mcp_server(
        effect_publishers=OperatorEffectPublishers(runtime_effect_publisher=publisher)
    ).call_tool(
        "resolve_human_request",
        {
            "task_id": task_id,
            "request_id": request_id,
            "item_responses": {"direction": "a"},
        },
    )
    return HumanRequestResolveResponse.model_validate(_mcp_payload(result))


async def _call_command_cancel(
    surface: Surface,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    publisher: CapturedRuntimeEffectPublisher,
    *,
    task_id: str,
    run_id: str,
) -> CommandRunCancelResponse:
    if surface == "http":
        async with _http_client(session_factory, publisher=publisher) as client:
            response = await client.post(f"/control/tasks/{task_id}/command-runs/{run_id}/cancel")
        assert response.status_code == 200
        return CommandRunCancelResponse.model_validate(response.json())
    _patch_mcp_sessions(monkeypatch, session_factory)
    result = await create_operator_mcp_server(
        effect_publishers=OperatorEffectPublishers(runtime_effect_publisher=publisher)
    ).call_tool("cancel_command_run", {"task_id": task_id, "run_id": run_id})
    return CommandRunCancelResponse.model_validate(_mcp_payload(result))


async def _read_flow(session_factory: SessionFactory, task_id: str) -> RuntimeFlowRead:
    async with session_factory() as session:
        return await runtime_flow_read(cast(AsyncSession, session), task_id)


def _patch_mcp_sessions(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
) -> None:
    monkeypatch.setattr(session_operations, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(runtime_tools, "get_session_factory", lambda: session_factory)


def _mcp_payload(result: object) -> object:
    assert isinstance(result, tuple) and len(result) == 2
    return result[1]


@asynccontextmanager
async def _http_client(
    session_factory: SessionFactory,
    *,
    publisher: CapturedRuntimeEffectPublisher | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(should_enable_mcp_mounts=False)
    if publisher is not None:
        app.state.runtime_effect_publisher = publisher

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield cast(AsyncSession, session)

    app.dependency_overrides[get_db_session] = session_dependency
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        yield client
