from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import ValidationError as PydanticValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from banksia.interfaces.http.contracts.operation_failure import ProductFailureCode
from banksia.interfaces.http.errors import operation_failure
from banksia.interfaces.mcp.mcp_operation_failures import (
    operation_failure_tool_result,
    runtime_operation_failure,
    validation_operation_failure,
)
from banksia.interfaces.mcp.transport import NodeMcpTransportPolicy
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError, illegal_caller_error
from banksia.runtime.node_mcp import DispatchMcpBindingRegistry
from banksia.runtime.node_operations import (
    NODE_OPERATION_CATALOG,
    NodeOperationDescriptor,
    NodeOperationExecutor,
    NodeOperationMutationKind,
    NodeOperationScope,
)
from banksia.runtime.node_operations.catalog import select_node_operation_descriptors

from .http_admission import ManagedNodeMcpHttpAdmission, current_managed_binding
from .schema_projection import managed_input_schema, operation_output_schema

NODE_TOOL_NAMES: tuple[str, ...] = tuple(
    str(descriptor.name) for descriptor in select_node_operation_descriptors()
)


class _StreamableHttpRequestApp:
    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._session_manager.handle_request(scope, receive, send)


class _NodeMcpProjection:
    def __init__(
        self,
        *,
        operation_executor: NodeOperationExecutor,
        binding_registry: DispatchMcpBindingRegistry,
    ) -> None:
        self._operation_executor = operation_executor
        self._binding_registry = binding_registry
        self._descriptors_by_name = {
            str(descriptor.name): descriptor for descriptor in NODE_OPERATION_CATALOG
        }
        self.server = Server("banksia-node", instructions=_server_instructions())
        self.server.list_tools()(self.list_tools)
        self.server.call_tool(validate_input=False)(self.call_tool)

    async def list_tools(self) -> list[types.Tool]:
        descriptors = await self._listed_descriptors()
        binding = current_managed_binding()
        scope = NodeOperationScope(
            task_id=binding.task_id,
            dispatch_id=binding.dispatch_id,
            provider_start_revision=binding.provider_start_revision,
        )
        human_request_kinds = await self._operation_executor.allowed_human_request_kinds(scope)
        return [
            self._tool_from_descriptor(
                descriptor,
                human_request_kinds=human_request_kinds,
            )
            for descriptor in descriptors
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        descriptor = self._descriptors_by_name.get(name)
        if descriptor is None:
            return operation_failure_tool_result(
                operation_failure(
                    code=ProductFailureCode.INVALID_REQUEST,
                    summary="That tool is not available.",
                    is_retryable=False,
                    field_path="name",
                    suggested_next_step="Use one of the tools currently listed for this session.",
                )
            )

        try:
            scope, semantic_arguments = self._resolve_call_scope(
                descriptor=descriptor,
                arguments=arguments,
            )
            result = await self._operation_executor.execute(
                scope=scope,
                operation_name=descriptor.name,
                arguments=semantic_arguments,
            )
        except PydanticValidationError as exc:
            return operation_failure_tool_result(validation_operation_failure(exc))
        except Exception as exc:
            return operation_failure_tool_result(runtime_operation_failure(exc))
        return _success_tool_result(result.model_dump(mode="json"))

    async def _listed_descriptors(self) -> tuple[NodeOperationDescriptor, ...]:
        binding = current_managed_binding()
        if not self._binding_registry.is_active(binding):
            return ()
        scope = NodeOperationScope(
            task_id=binding.task_id,
            dispatch_id=binding.dispatch_id,
            provider_start_revision=binding.provider_start_revision,
        )
        descriptors = await self._operation_executor.list_operations(scope)
        return tuple(
            descriptor
            for descriptor in descriptors
            if str(descriptor.name) in binding.exposure_ceiling
        )

    def _resolve_call_scope(
        self,
        *,
        descriptor: NodeOperationDescriptor,
        arguments: Mapping[str, object],
    ) -> tuple[NodeOperationScope, dict[str, object]]:
        binding = current_managed_binding()
        if not self._binding_registry.is_active(binding):
            raise _managed_authentication_error()
        if str(descriptor.name) not in binding.exposure_ceiling:
            raise illegal_caller_error(
                f"managed binding does not expose Node operation '{descriptor.name}'"
            )
        scope = NodeOperationScope(
            task_id=binding.task_id,
            dispatch_id=binding.dispatch_id,
            provider_start_revision=binding.provider_start_revision,
        )
        semantic_arguments = dict(arguments)
        if not self._binding_registry.is_active(binding):
            raise _managed_authentication_error()
        return scope, semantic_arguments

    def _tool_from_descriptor(
        self,
        descriptor: NodeOperationDescriptor,
        *,
        human_request_kinds: tuple[str, ...] | None = None,
    ) -> types.Tool:
        is_read_only = descriptor.mutation_kind is NodeOperationMutationKind.READ
        input_schema = managed_input_schema(
            descriptor,
            human_request_kinds=human_request_kinds,
        )
        return types.Tool(
            name=str(descriptor.name),
            title=descriptor.title,
            description=descriptor.description,
            inputSchema=input_schema,
            outputSchema=operation_output_schema(descriptor),
            annotations=types.ToolAnnotations(
                readOnlyHint=is_read_only,
                destructiveHint=False if is_read_only else None,
            ),
        )


def create_managed_node_mcp_app(
    *,
    binding_registry: DispatchMcpBindingRegistry,
    operation_executor: NodeOperationExecutor,
    transport_policy: NodeMcpTransportPolicy,
) -> Starlette:
    projection = _NodeMcpProjection(
        operation_executor=operation_executor,
        binding_registry=binding_registry,
    )
    return _create_projection_app(
        projection=projection,
        transport_policy=transport_policy,
        binding_registry=binding_registry,
    )


def _create_projection_app(
    *,
    projection: _NodeMcpProjection,
    transport_policy: NodeMcpTransportPolicy,
    binding_registry: DispatchMcpBindingRegistry,
) -> Starlette:
    session_manager = StreamableHTTPSessionManager(
        app=projection.server,
        json_response=True,
        stateless=True,
        security_settings=transport_policy.as_sdk_settings(),
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            try:
                yield
            finally:
                binding_registry.revoke_all()

    middleware = [
        Middleware(
            ManagedNodeMcpHttpAdmission,
            binding_registry=binding_registry,
        )
    ]
    return Starlette(
        routes=[Route("/mcp", endpoint=_StreamableHttpRequestApp(session_manager))],
        middleware=middleware,
        lifespan=lifespan,
    )


def _managed_authentication_error() -> ValueError:
    return RuntimeOperationError(
        code=OperationFailureCode.AUTHENTICATION_FAILED,
        summary="managed Node MCP authentication failed",
        is_retryable=False,
    )


def _success_tool_result(payload: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, indent=2))],
        structuredContent=payload,
        isError=False,
    )


def _server_instructions() -> str:
    return (
        "Dispatch-scoped Oh My Subagents Node tools. Scope and exposure come from the private "
        "managed binding; tool arguments contain semantic fields only."
    )


__all__ = [
    "NODE_TOOL_NAMES",
    "create_managed_node_mcp_app",
]
