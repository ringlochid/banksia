from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.providers import (
    ManagedExtensionMode,
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
    ProviderNativeAccess,
)
from oh_my_subagents.runtime.contracts.provider_resolution import (
    ClaudeProviderRoute,
    CodexProviderRoute,
    ProviderRoute,
)
from oh_my_subagents.runtime.dispatch.provider_start import ProviderStartCandidate
from oh_my_subagents.runtime.node_mcp import DispatchMcpBinding, DispatchMcpBindingRegistry
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from oh_my_subagents.runtime.post_commit import DispatchStartDue
from oh_my_subagents.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
)
from oh_my_subagents.runtime.providers.resolution import validate_provider_execution_configuration
from oh_my_subagents.runtime.task_root import read_task_root_paths


@dataclass(frozen=True, slots=True)
class PreparedProviderStart:
    request: DispatchStartRequest
    binding: DispatchMcpBinding


class ProviderStartRequestBuilder:
    """Build one exact provider request from committed text and capabilities."""

    def __init__(
        self,
        *,
        binding_registry: DispatchMcpBindingRegistry,
        operation_executor: NodeOperationExecutor,
        managed_node_mcp_url: str,
    ) -> None:
        self._binding_registry = binding_registry
        self._operation_executor = operation_executor
        self._managed_node_mcp_url = managed_node_mcp_url

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
            extension_mode,
            instructions,
            input_text,
        ) = _validate_candidate(candidate)
        paths = await read_task_root_paths(session, candidate.task_id)
        await session.rollback()

        binding: DispatchMcpBinding | None = None
        try:
            binding, managed_connection = await self._prepare_node_connection(signal, candidate)
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
                extension_mode=extension_mode,
                managed_node_mcp=managed_connection,
            )
        except Exception:
            if binding is not None:
                self._binding_registry.revoke_binding(binding)
            raise
        assert binding is not None
        return PreparedProviderStart(request=request, binding=binding)

    async def _prepare_node_connection(
        self,
        signal: DispatchStartDue,
        candidate: ProviderStartCandidate,
    ) -> tuple[DispatchMcpBinding, ManagedNodeMcpConnection]:
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
        return issued.binding, ManagedNodeMcpConnection(
            url=self._managed_node_mcp_url,
            bearer_token=SecretStr(issued.credential),
            enabled_tools=operation_names,
        )


def _validate_candidate(
    candidate: ProviderStartCandidate,
) -> tuple[
    ProviderRoute,
    ProviderNativeAccess,
    NetworkAccess,
    ManagedSandboxMode,
    ManagedExtensionMode,
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
    if candidate.sandbox_mode is None or candidate.effective_extension_mode is None:
        raise ValueError("current starting dispatch is missing managed provider records")
    sandbox_mode = ManagedSandboxMode(candidate.sandbox_mode)
    extension_mode = ManagedExtensionMode(candidate.effective_extension_mode)
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
        extension_mode,
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
        case _:
            raise ValueError("current starting dispatch selects a retired provider")


__all__ = ["PreparedProviderStart", "ProviderStartRequestBuilder"]
