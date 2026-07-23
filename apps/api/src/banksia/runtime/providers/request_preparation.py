from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.providers import (
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
    ProviderNativeAccess,
)
from banksia.runtime.contracts.provider_resolution import (
    ClaudeProviderRoute,
    CodexProviderRoute,
    OpenClawProviderRoute,
    ProviderRoute,
)
from banksia.runtime.dispatch.provider_start import ProviderStartCandidate
from banksia.runtime.node_mcp import DispatchMcpBinding, DispatchMcpBindingRegistry
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import DispatchStartDue
from banksia.runtime.providers.contracts import (
    CompatibilityNodeMcpConnection,
    DispatchStartRequest,
    ManagedNodeMcpConnection,
)
from banksia.runtime.providers.resolution import validate_provider_execution_configuration
from banksia.runtime.task_root import read_task_root_paths


@dataclass(frozen=True, slots=True)
class PreparedProviderStart:
    request: DispatchStartRequest
    binding: DispatchMcpBinding | None


class ProviderStartRequestBuilder:
    """Build one exact provider request from committed text and capabilities."""

    def __init__(
        self,
        *,
        binding_registry: DispatchMcpBindingRegistry,
        operation_executor: NodeOperationExecutor,
        managed_node_mcp_url: str,
        compatibility_node_mcp_url: str,
    ) -> None:
        self._binding_registry = binding_registry
        self._operation_executor = operation_executor
        self._managed_node_mcp_url = managed_node_mcp_url
        self._compatibility_node_mcp_url = compatibility_node_mcp_url

    async def prepare_provider_start(
        self,
        session: AsyncSession,
        signal: DispatchStartDue,
        candidate: ProviderStartCandidate,
    ) -> PreparedProviderStart:
        (
            route,
            native_access,
            network_access,
            sandbox_mode,
            instructions,
            input_text,
        ) = _validate_candidate(candidate)
        paths = await read_task_root_paths(session, candidate.task_id)
        await session.rollback()

        binding: DispatchMcpBinding | None = None
        try:
            (
                binding,
                managed_connection,
                compatibility_connection,
            ) = await self._prepare_node_connections(signal, candidate)
            request = DispatchStartRequest(
                task_id=candidate.task_id,
                dispatch_id=signal.dispatch_id,
                provider_start_revision=signal.provider_start_revision,
                working_directory=paths.workspace_path,
                instructions=instructions,
                input=input_text,
                provider_route=route,
                provider_native_access=native_access,
                network_access=network_access,
                sandbox_mode=sandbox_mode,
                managed_node_mcp=managed_connection,
                compatibility_node_mcp=compatibility_connection,
            )
        except Exception:
            if binding is not None:
                self._binding_registry.revoke_binding(binding)
            raise
        return PreparedProviderStart(request=request, binding=binding)

    async def _prepare_node_connections(
        self,
        signal: DispatchStartDue,
        candidate: ProviderStartCandidate,
    ) -> tuple[
        DispatchMcpBinding | None,
        ManagedNodeMcpConnection | None,
        CompatibilityNodeMcpConnection | None,
    ]:
        if candidate.provider_kind in {ProviderKind.CODEX, ProviderKind.CLAUDE}:
            descriptors = await self._operation_executor.list_operations(
                NodeOperationScope(
                    task_id=candidate.task_id,
                    dispatch_id=signal.dispatch_id,
                    provider_start_revision=signal.provider_start_revision,
                )
            )
            operation_names = tuple(str(descriptor.name) for descriptor in descriptors)
            issued = self._binding_registry.issue_binding(
                task_id=candidate.task_id,
                dispatch_id=signal.dispatch_id,
                provider_start_revision=signal.provider_start_revision,
                exposure_ceiling=operation_names,
            )
            managed_connection = ManagedNodeMcpConnection(
                url=self._managed_node_mcp_url,
                bearer_token=SecretStr(issued.credential),
                enabled_tools=operation_names,
            )
            return issued.binding, managed_connection, None

        compatibility_connection = CompatibilityNodeMcpConnection(
            url=self._compatibility_node_mcp_url
        )
        return None, None, compatibility_connection


def _validate_candidate(
    candidate: ProviderStartCandidate,
) -> tuple[
    ProviderRoute,
    ProviderNativeAccess,
    NetworkAccess,
    ManagedSandboxMode | None,
    str,
    str,
]:
    if (
        candidate.instructions is None
        or candidate.input is None
        or candidate.provider_native_access is None
        or candidate.network_access is None
    ):
        raise ValueError("current starting dispatch is missing request records")
    route = _provider_route(candidate)
    native_access = ProviderNativeAccess(candidate.provider_native_access)
    network_access = NetworkAccess(candidate.network_access)
    sandbox_mode = (
        ManagedSandboxMode(candidate.sandbox_mode) if candidate.sandbox_mode is not None else None
    )
    validate_provider_execution_configuration(
        route=route,
        provider_native_access=native_access,
        network_access=network_access,
        sandbox_mode=sandbox_mode,
    )
    return (
        route,
        native_access,
        network_access,
        sandbox_mode,
        candidate.instructions,
        candidate.input,
    )


def _provider_route(candidate: ProviderStartCandidate) -> ProviderRoute:
    if candidate.provider_kind is None:
        raise ValueError("current starting dispatch has an invalid provider route")
    match candidate.provider_kind:
        case ProviderKind.CODEX:
            return CodexProviderRoute(
                kind=ProviderKind.CODEX,
                model_override=candidate.model_override,
                effort_override=candidate.effort_override,
            )
        case ProviderKind.CLAUDE:
            return ClaudeProviderRoute(
                kind=ProviderKind.CLAUDE,
                model_override=candidate.model_override,
                effort_override=candidate.effort_override,
            )
        case ProviderKind.OPENCLAW:
            return OpenClawProviderRoute(
                kind=ProviderKind.OPENCLAW,
                gateway_profile=candidate.gateway_profile or "",
            )


__all__ = ["PreparedProviderStart", "ProviderStartRequestBuilder"]
