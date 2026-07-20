from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from autoclaw.interfaces.http.errors import operation_failure
from autoclaw.interfaces.mcp.mcp_operation_failures import (
    operation_failure_tool_result,
    runtime_operation_failure,
    validation_operation_failure,
)
from autoclaw.interfaces.mcp.transport import NodeMcpTransportPolicy
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError, illegal_caller_error
from autoclaw.runtime.node_mcp import DispatchMcpBindingRegistry
from autoclaw.runtime.node_operations import (
    NODE_OPERATION_CATALOG,
    NodeOperationDescriptor,
    NodeOperationExecutor,
    NodeOperationMutationKind,
    NodeOperationScope,
)

from .http_admission import ManagedNodeMcpHttpAdmission, current_managed_binding
from .schema_projection import (
    compatibility_input_schema,
    managed_input_schema,
    operation_output_schema,
)

NODE_TOOL_NAMES: tuple[str, ...] = tuple(
    str(descriptor.name) for descriptor in NODE_OPERATION_CATALOG
)


class NodeMcpProjectionKind(StrEnum):
    MANAGED = "managed"
    COMPATIBILITY = "compatibility"


@dataclass(frozen=True, slots=True)
class NodeMcpApplications:
    managed: Starlette
    compatibility: Starlette


class _CompatibilityScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    dispatch_id: str = Field(min_length=1)


class _StreamableHttpRequestApp:
    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._session_manager.handle_request(scope, receive, send)


class _NodeMcpProjection:
    def __init__(
        self,
        *,
        kind: NodeMcpProjectionKind,
        operation_executor: NodeOperationExecutor,
        binding_registry: DispatchMcpBindingRegistry | None,
    ) -> None:
        self._kind = kind
        self._operation_executor = operation_executor
        self._binding_registry = binding_registry
        self._descriptors_by_name = {
            str(descriptor.name): descriptor for descriptor in NODE_OPERATION_CATALOG
        }
        server_name = (
            "autoclaw-node-managed" if kind is NodeMcpProjectionKind.MANAGED else "autoclaw-node"
        )
        self.server = Server(server_name, instructions=_server_instructions(kind))
        self.server.list_tools()(self.list_tools)
        self.server.call_tool(validate_input=False)(self.call_tool)

    async def list_tools(self) -> list[types.Tool]:
        descriptors = await self._listed_descriptors()
        return [self._tool_from_descriptor(descriptor) for descriptor in descriptors]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        descriptor = self._descriptors_by_name.get(name)
        if descriptor is None:
            return operation_failure_tool_result(
                operation_failure(
                    code=OperationFailureCode.INVALID_REQUEST_SHAPE,
                    summary=f"unknown Node operation '{name}'",
                    is_retryable=False,
                    field_path="name",
                    suggested_next_step="Reread the available Node tools before retrying.",
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
        if self._kind is NodeMcpProjectionKind.COMPATIBILITY:
            return NODE_OPERATION_CATALOG

        binding = current_managed_binding()
        if self._binding_registry is None or not self._binding_registry.is_active(binding):
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
        if self._kind is NodeMcpProjectionKind.COMPATIBILITY:
            return _extract_compatibility_scope(arguments)

        binding = current_managed_binding()
        if self._binding_registry is None or not self._binding_registry.is_active(binding):
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

    def _tool_from_descriptor(self, descriptor: NodeOperationDescriptor) -> types.Tool:
        is_read_only = descriptor.mutation_kind is NodeOperationMutationKind.READ
        input_schema = (
            managed_input_schema(descriptor)
            if self._kind is NodeMcpProjectionKind.MANAGED
            else compatibility_input_schema(descriptor)
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


def create_node_mcp_apps(
    *,
    binding_registry: DispatchMcpBindingRegistry,
    operation_executor: NodeOperationExecutor,
    transport_policy: NodeMcpTransportPolicy,
) -> NodeMcpApplications:
    return NodeMcpApplications(
        managed=create_managed_node_mcp_app(
            binding_registry=binding_registry,
            operation_executor=operation_executor,
            transport_policy=transport_policy,
        ),
        compatibility=create_compatibility_node_mcp_app(
            operation_executor=operation_executor,
            transport_policy=transport_policy,
        ),
    )


def create_managed_node_mcp_app(
    *,
    binding_registry: DispatchMcpBindingRegistry,
    operation_executor: NodeOperationExecutor,
    transport_policy: NodeMcpTransportPolicy,
) -> Starlette:
    projection = _NodeMcpProjection(
        kind=NodeMcpProjectionKind.MANAGED,
        operation_executor=operation_executor,
        binding_registry=binding_registry,
    )
    return _create_projection_app(
        projection=projection,
        transport_policy=transport_policy,
        binding_registry=binding_registry,
    )


def create_compatibility_node_mcp_app(
    *,
    operation_executor: NodeOperationExecutor,
    transport_policy: NodeMcpTransportPolicy,
) -> Starlette:
    projection = _NodeMcpProjection(
        kind=NodeMcpProjectionKind.COMPATIBILITY,
        operation_executor=operation_executor,
        binding_registry=None,
    )
    return _create_projection_app(
        projection=projection,
        transport_policy=transport_policy,
        binding_registry=None,
    )


def _create_projection_app(
    *,
    projection: _NodeMcpProjection,
    transport_policy: NodeMcpTransportPolicy,
    binding_registry: DispatchMcpBindingRegistry | None,
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
                if binding_registry is not None:
                    binding_registry.revoke_all()

    middleware = (
        [
            Middleware(
                ManagedNodeMcpHttpAdmission,
                binding_registry=binding_registry,
            )
        ]
        if binding_registry is not None
        else []
    )
    return Starlette(
        routes=[Route("/mcp", endpoint=_StreamableHttpRequestApp(session_manager))],
        middleware=middleware,
        lifespan=lifespan,
    )


def _extract_compatibility_scope(
    arguments: Mapping[str, object],
) -> tuple[NodeOperationScope, dict[str, object]]:
    semantic_arguments = dict(arguments)
    scope_request = _CompatibilityScopeRequest.model_validate(
        {
            "task_id": semantic_arguments.pop("task_id", None),
            "dispatch_id": semantic_arguments.pop("dispatch_id", None),
        }
    )
    return (
        NodeOperationScope(
            task_id=scope_request.task_id,
            dispatch_id=scope_request.dispatch_id,
        ),
        semantic_arguments,
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


def _server_instructions(kind: NodeMcpProjectionKind) -> str:
    if kind is NodeMcpProjectionKind.MANAGED:
        return (
            "Dispatch-scoped AutoClaw Node tools. Scope and exposure come from the private "
            "managed binding; tool arguments contain semantic fields only."
        )
    return (
        "Explicit-ID AutoClaw Node compatibility tools for user-configured OpenClaw. Every "
        "call requires the full current task_id and dispatch_id."
    )


__all__ = [
    "NODE_TOOL_NAMES",
    "NodeMcpApplications",
    "NodeMcpProjectionKind",
    "create_compatibility_node_mcp_app",
    "create_managed_node_mcp_app",
    "create_node_mcp_apps",
]
