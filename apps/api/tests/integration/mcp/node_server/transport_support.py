from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import httpx
from autoclaw.interfaces.mcp.node import NodeMcpApplications, create_node_mcp_apps
from autoclaw.interfaces.mcp.transport import node_mcp_transport_policy
from autoclaw.runtime.node_mcp import (
    DispatchMcpBindingRegistry,
    IssuedDispatchMcpBinding,
)
from autoclaw.runtime.node_operations import (
    NODE_OPERATION_CATALOG,
    NodeOperationDescriptor,
    NodeOperationExecutor,
    NodeOperationName,
    NodeOperationScope,
    get_node_operation_descriptor,
)
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel
from starlette.applications import Starlette


@dataclass(frozen=True, slots=True)
class RecordedNodeOperationCall:
    scope: NodeOperationScope
    operation_name: NodeOperationName
    arguments: dict[str, object]


class RecordingNodeOperationExecutor:
    def __init__(
        self,
        *,
        listed_names_by_dispatch: Mapping[str, Sequence[NodeOperationName]] | None = None,
        results_by_name: Mapping[NodeOperationName, BaseModel] | None = None,
    ) -> None:
        self._listed_names_by_dispatch = dict(listed_names_by_dispatch or {})
        self._results_by_name = dict(results_by_name or {})
        self.listed_scopes: list[NodeOperationScope] = []
        self.calls: list[RecordedNodeOperationCall] = []

    async def list_operations(
        self,
        scope: NodeOperationScope,
    ) -> tuple[NodeOperationDescriptor, ...]:
        self.listed_scopes.append(scope)
        names = self._listed_names_by_dispatch.get(
            scope.dispatch_id,
            tuple(descriptor.name for descriptor in NODE_OPERATION_CATALOG),
        )
        return tuple(get_node_operation_descriptor(name) for name in names)

    async def execute(
        self,
        *,
        scope: NodeOperationScope,
        operation_name: str | NodeOperationName,
        arguments: Mapping[str, object],
    ) -> BaseModel:
        normalized_name = NodeOperationName(operation_name)
        descriptor = get_node_operation_descriptor(normalized_name)
        descriptor.request_model.model_validate(dict(arguments))
        self.calls.append(
            RecordedNodeOperationCall(
                scope=scope,
                operation_name=normalized_name,
                arguments=dict(arguments),
            )
        )
        result = self._results_by_name.get(normalized_name)
        if result is None:
            raise AssertionError(f"missing test result for Node operation '{normalized_name}'")
        return result


def create_test_node_mcp_apps(
    executor: NodeOperationExecutor | RecordingNodeOperationExecutor,
    *,
    registry: DispatchMcpBindingRegistry | None = None,
) -> tuple[NodeMcpApplications, DispatchMcpBindingRegistry]:
    binding_registry = registry or DispatchMcpBindingRegistry()
    applications = create_node_mcp_apps(
        binding_registry=binding_registry,
        operation_executor=cast(NodeOperationExecutor, executor),
        transport_policy=node_mcp_transport_policy(
            host="127.0.0.1",
            port=18125,
            allowed_origins=("http://127.0.0.1:5173",),
        ),
    )
    return applications, binding_registry


def issue_test_binding(
    registry: DispatchMcpBindingRegistry,
    *,
    task_id: str,
    dispatch_id: str,
    provider_start_revision: int = 0,
    exposure_ceiling: Sequence[str | NodeOperationName],
) -> IssuedDispatchMcpBinding:
    return registry.issue_binding(
        task_id=task_id,
        dispatch_id=dispatch_id,
        provider_start_revision=provider_start_revision,
        exposure_ceiling=(str(name) for name in exposure_ceiling),
    )


def managed_headers(issued: IssuedDispatchMcpBinding) -> dict[str, str]:
    return {"Authorization": f"Bearer {issued.credential}"}


@asynccontextmanager
async def mcp_session_without_lifespan(
    app: Starlette,
    *,
    headers: Mapping[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
        headers=dict(headers or {}),
    ) as client:
        async with streamable_http_client(
            "http://127.0.0.1:18125/mcp",
            http_client=client,
        ) as streams:
            async with ClientSession(*streams[:2]) as session:
                await session.initialize()
                try:
                    yield session
                finally:
                    await asyncio.sleep(0.01)


@asynccontextmanager
async def node_mcp_client_session(
    app: Starlette,
    *,
    headers: Mapping[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    async with app.router.lifespan_context(app):
        async with mcp_session_without_lifespan(app, headers=headers) as session:
            yield session


def tool_names(result: Any) -> tuple[str, ...]:
    return tuple(tool.name for tool in result.tools)


def tool_input_schema(result: Any, tool_name: str) -> dict[str, Any]:
    for tool in result.tools:
        if tool.name == tool_name:
            return cast(dict[str, Any], tool.inputSchema)
    raise AssertionError(f"missing tool '{tool_name}'")


def tool_output_schema(result: Any, tool_name: str) -> dict[str, Any] | None:
    for tool in result.tools:
        if tool.name == tool_name:
            return cast(dict[str, Any] | None, getattr(tool, "outputSchema", None))
    raise AssertionError(f"missing tool '{tool_name}'")


def tool_description(result: Any, tool_name: str) -> str:
    for tool in result.tools:
        if tool.name == tool_name:
            return cast(str, tool.description or "")
    raise AssertionError(f"missing tool '{tool_name}'")


async def call_tool_result(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    return await session.call_tool(name, arguments or {})


async def call_tool_structured(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await call_tool_result(session, name, arguments)
    assert result.isError is False, {
        "content": result.content,
        "structured": result.structuredContent,
    }
    assert result.structuredContent is not None
    return cast(dict[str, Any], result.structuredContent)


def tool_failure(result: Any) -> dict[str, Any]:
    assert result.isError is True, {
        "content": result.content,
        "structured": result.structuredContent,
    }
    assert result.structuredContent is not None
    failure = cast(dict[str, Any], result.structuredContent)
    assert failure.get("ok") is False
    return failure


__all__ = [
    "RecordedNodeOperationCall",
    "RecordingNodeOperationExecutor",
    "call_tool_result",
    "call_tool_structured",
    "create_test_node_mcp_apps",
    "issue_test_binding",
    "managed_headers",
    "mcp_session_without_lifespan",
    "node_mcp_client_session",
    "tool_description",
    "tool_failure",
    "tool_input_schema",
    "tool_names",
    "tool_output_schema",
]
