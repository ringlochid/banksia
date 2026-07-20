from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

import httpx
from autoclaw.persistence.models import DispatchTurnModel, HumanRequestModel
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_mcp import IssuedDispatchMcpBinding
from autoclaw.runtime.node_operations import (
    ListFilesResponse,
    NodeActivitySignal,
    NodeOperationDescriptor,
    NodeOperationExecutor,
    NodeOperationName,
    NodeOperationScope,
)
from pydantic import BaseModel
from sqlalchemy import func, select
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.integration.mcp.node_server.transport_support import (
    RecordingNodeOperationExecutor,
    call_tool_result,
    call_tool_structured,
    create_test_node_mcp_apps,
    issue_test_binding,
    managed_headers,
    node_mcp_client_session,
    tool_failure,
    tool_names,
)

_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class _PausedNodeOperationExecutor(NodeOperationExecutor):
    def __init__(self, delegate: NodeOperationExecutor) -> None:
        self._delegate = delegate
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.error: RuntimeOperationError | None = None

    async def list_operations(
        self,
        scope: NodeOperationScope,
    ) -> tuple[NodeOperationDescriptor, ...]:
        return await self._delegate.list_operations(scope)

    async def execute(
        self,
        *,
        scope: NodeOperationScope,
        operation_name: str | NodeOperationName,
        arguments: Mapping[str, object],
    ) -> BaseModel:
        self.entered.set()
        await self.release.wait()
        try:
            return await self._delegate.execute(
                scope=scope,
                operation_name=operation_name,
                arguments=arguments,
            )
        except RuntimeOperationError as exc:
            self.error = exc
            raise
        finally:
            self.finished.set()


async def test_managed_call_scope_comes_only_from_the_authenticated_binding() -> None:
    executor = RecordingNodeOperationExecutor(
        results_by_name={NodeOperationName.LIST_FILES: ListFilesResponse(directory=".", entries=())}
    )
    applications, registry = create_test_node_mcp_apps(executor)
    issued = issue_test_binding(
        registry,
        task_id="task.managed-scope",
        dispatch_id="dispatch.managed-scope",
        exposure_ceiling=(NodeOperationName.LIST_FILES,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as session:
        result = await call_tool_structured(session, "list_files", {"directory": "."})

    assert result == {"directory": ".", "entries": []}
    assert len(executor.calls) == 1
    assert executor.calls[0].scope.task_id == "task.managed-scope"
    assert executor.calls[0].scope.dispatch_id == "dispatch.managed-scope"
    assert executor.calls[0].scope.provider_start_revision == 0
    assert executor.calls[0].arguments == {"directory": "."}


async def test_managed_call_rejects_model_visible_task_or_dispatch_selectors() -> None:
    executor = RecordingNodeOperationExecutor(
        results_by_name={NodeOperationName.LIST_FILES: ListFilesResponse(directory=".", entries=())}
    )
    applications, registry = create_test_node_mcp_apps(executor)
    issued = issue_test_binding(
        registry,
        task_id="task.managed-selector-rejection",
        dispatch_id="dispatch.managed-selector-rejection",
        exposure_ceiling=(NodeOperationName.LIST_FILES,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as session:
        result = await call_tool_result(
            session,
            "list_files",
            {
                "task_id": "task.spoofed",
                "dispatch_id": "dispatch.spoofed",
                "directory": ".",
            },
        )

    failure = tool_failure(result)
    assert failure["code"] == "invalid_request_shape"
    assert failure["retryable"] is False
    assert executor.calls == []


async def test_managed_binding_ceiling_rejects_an_unexposed_catalog_operation() -> None:
    executor = RecordingNodeOperationExecutor(
        results_by_name={NodeOperationName.LIST_FILES: ListFilesResponse(directory=".", entries=())}
    )
    applications, registry = create_test_node_mcp_apps(executor)
    issued = issue_test_binding(
        registry,
        task_id="task.managed-ceiling",
        dispatch_id="dispatch.managed-ceiling",
        exposure_ceiling=(NodeOperationName.GET_CURRENT_CONTEXT,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as session:
        result = await call_tool_result(session, "list_files", {"directory": "."})

    failure = tool_failure(result)
    assert failure["code"] == "illegal_caller"
    assert "does not expose" in failure["summary"]
    assert executor.calls == []


async def test_retry_binding_uses_a_fresh_credential_for_the_same_dispatch() -> None:
    executor = RecordingNodeOperationExecutor()
    applications, registry = create_test_node_mcp_apps(executor)
    old_binding = issue_test_binding(
        registry,
        task_id="task.managed-retry",
        dispatch_id="dispatch.managed-retry",
        provider_start_revision=0,
        exposure_ceiling=(NodeOperationName.GET_CURRENT_CONTEXT,),
    )
    registry.revoke_binding(old_binding.binding)
    retry_binding = issue_test_binding(
        registry,
        task_id="task.managed-retry",
        dispatch_id="dispatch.managed-retry",
        provider_start_revision=1,
        exposure_ceiling=(NodeOperationName.GET_CURRENT_CONTEXT,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(retry_binding),
    ) as session:
        names = set(tool_names(await session.list_tools()))

    assert old_binding.credential != retry_binding.credential
    assert registry.authenticate(old_binding.credential) is None
    assert retry_binding.binding.provider_start_revision == 1
    assert names == {"get_current_context"}


async def test_rotated_managed_generation_rejects_inflight_old_binding_before_admission(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="managed-generation-race") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        paused_executor = _PausedNodeOperationExecutor(executor)
        applications, registry = create_test_node_mcp_apps(paused_executor)
        exposure_ceiling = (
            NodeOperationName.GET_CURRENT_CONTEXT,
            NodeOperationName.OPEN_HUMAN_REQUEST,
        )
        old_binding = issue_test_binding(
            registry,
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
            provider_start_revision=0,
            exposure_ceiling=exposure_ceiling,
        )

        async with applications.managed.router.lifespan_context(applications.managed):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(
                    app=applications.managed,
                    client=("127.0.0.1", 43125),
                ),
                base_url="http://127.0.0.1:18125",
            ) as client:
                old_call = _start_human_request_call(client, old_binding)
                await asyncio.wait_for(paused_executor.entered.wait(), timeout=2)

                await _rotate_provider_start_generation(
                    session_factory,
                    dispatch_id=ids.current_dispatch_id,
                )

                await _assert_old_binding_list_is_stale(
                    client,
                    old_binding=old_binding,
                )

                assert registry.revoke_binding(old_binding.binding) is True
                new_binding = issue_test_binding(
                    registry,
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                    provider_start_revision=1,
                    exposure_ceiling=exposure_ceiling,
                )
                paused_executor.release.set()
                await asyncio.wait_for(paused_executor.finished.wait(), timeout=2)
                old_response = await asyncio.wait_for(old_call, timeout=2)

                await _assert_old_binding_rejected_without_admission(
                    old_response,
                    paused_executor=paused_executor,
                    session_factory=session_factory,
                    dispatch_id=ids.current_dispatch_id,
                    signals=signals,
                )

                new_response = await _post_node_request(
                    client,
                    issued=new_binding,
                    request_id=3,
                    method="tools/call",
                    params={"name": "get_current_context", "arguments": {}},
                )
                await _assert_new_binding_admitted(
                    new_response,
                    session_factory=session_factory,
                    dispatch_id=ids.current_dispatch_id,
                    signals=signals,
                )


async def test_compatibility_call_rejects_missing_explicit_scope_before_execution() -> None:
    executor = RecordingNodeOperationExecutor(
        results_by_name={NodeOperationName.LIST_FILES: ListFilesResponse(directory=".", entries=())}
    )
    applications, _registry = create_test_node_mcp_apps(executor)

    async with node_mcp_client_session(applications.compatibility) as session:
        result = await call_tool_result(
            session,
            "list_files",
            {"task_id": "task.compatibility-missing-dispatch", "directory": "."},
        )

    failure = tool_failure(result)
    assert failure["code"] == "invalid_request_shape"
    assert failure["field_path"] == "dispatch_id"
    assert executor.calls == []


async def _post_node_request(
    client: httpx.AsyncClient,
    *,
    issued: IssuedDispatchMcpBinding,
    request_id: int,
    method: str,
    params: dict[str, object],
) -> httpx.Response:
    return await client.post(
        "/mcp",
        headers={**_MCP_HEADERS, "Authorization": f"Bearer {issued.credential}"},
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        },
    )


def _start_human_request_call(
    client: httpx.AsyncClient,
    binding: IssuedDispatchMcpBinding,
) -> asyncio.Task[httpx.Response]:
    return asyncio.create_task(
        _post_node_request(
            client,
            issued=binding,
            request_id=1,
            method="tools/call",
            params={
                "name": "open_human_request",
                "arguments": _human_request_arguments(),
            },
        )
    )


async def _rotate_provider_start_generation(
    session_factory: SessionFactory,
    *,
    dispatch_id: str,
) -> None:
    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, dispatch_id)
        assert dispatch is not None
        dispatch.provider_start_revision = 1
        await session.commit()


async def _assert_old_binding_list_is_stale(
    client: httpx.AsyncClient,
    *,
    old_binding: IssuedDispatchMcpBinding,
) -> None:
    response = await _post_node_request(
        client,
        issued=old_binding,
        request_id=2,
        method="tools/list",
        params={},
    )
    assert response.status_code == 200
    assert response.json()["error"]["message"] == (
        "managed binding provider-start generation is no longer current"
    )


async def _assert_old_binding_rejected_without_admission(
    response: httpx.Response,
    *,
    paused_executor: _PausedNodeOperationExecutor,
    session_factory: SessionFactory,
    dispatch_id: str,
    signals: list[NodeActivitySignal],
) -> None:
    failure = response.json()["result"]
    assert response.status_code == 200
    assert failure["isError"] is True
    assert failure["structuredContent"]["code"] == "stale_dispatch"
    assert paused_executor.error is not None
    assert paused_executor.error.code == OperationFailureCode.STALE_DISPATCH

    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, dispatch_id)
        request_count = await session.scalar(select(func.count()).select_from(HumanRequestModel))
    assert dispatch is not None
    assert dispatch.status == "open"
    assert dispatch.node_activity_revision == 0
    assert int(request_count or 0) == 0
    assert signals == []


async def _assert_new_binding_admitted(
    response: httpx.Response,
    *,
    session_factory: SessionFactory,
    dispatch_id: str,
    signals: list[NodeActivitySignal],
) -> None:
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False

    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, dispatch_id)
    assert dispatch is not None
    assert dispatch.node_activity_revision == 1
    assert [signal.activity_revision for signal in signals] == [1]


def _human_request_arguments() -> dict[str, object]:
    return {
        "request": {
            "kind": "direction",
            "summary": "Choose one bounded direction.",
            "items": [
                {
                    "id": "direction",
                    "prompt": "Which direction?",
                    "options": [{"id": "a", "title": "A"}],
                }
            ],
        }
    }
