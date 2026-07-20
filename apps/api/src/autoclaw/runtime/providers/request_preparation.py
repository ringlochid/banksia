from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.contracts.registry import NetworkAccess, ProviderNativeAccess
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.runtime.contracts.provider_resolution import (
    ClaudeProviderRoute,
    CodexProviderRoute,
    OpenClawProviderRoute,
    ProviderRoute,
)
from autoclaw.runtime.dispatch.provider_start import ProviderStartCandidate
from autoclaw.runtime.node_mcp import DispatchMcpBinding, DispatchMcpBindingRegistry
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import DispatchStartDue
from autoclaw.runtime.providers.contracts import (
    CompatibilityNodeMcpConnection,
    DispatchStartRequest,
    ManagedNodeMcpConnection,
)
from autoclaw.runtime.providers.resolution import validate_provider_execution_policy
from autoclaw.runtime.task_root import (
    read_logical_regular_file_bytes,
    read_task_root_paths,
)


@dataclass(frozen=True, slots=True)
class PreparedProviderStart:
    request: DispatchStartRequest
    binding: DispatchMcpBinding | None


class ProviderStartRequestBuilder:
    """Build one exact provider request from committed refs and capabilities."""

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
        route, native_access, network_access = _validate_candidate(candidate)
        paths = await read_task_root_paths(session, candidate.task_id)
        await session.rollback()
        instructions, input_bytes = _read_request_pair(
            paths,
            dispatch_id=signal.dispatch_id,
            instructions_logical_path=candidate.instructions_logical_path,
            input_logical_path=candidate.input_logical_path,
        )

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
                input=input_bytes,
                provider_route=route,
                provider_native_access=native_access,
                network_access=network_access,
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
) -> tuple[ProviderRoute, ProviderNativeAccess, NetworkAccess]:
    if (
        candidate.instructions_logical_path is None
        or candidate.input_logical_path is None
        or candidate.provider_native_access is None
        or candidate.network_access is None
    ):
        raise ValueError("current starting dispatch is missing request records")
    route = _provider_route(candidate)
    native_access = ProviderNativeAccess(candidate.provider_native_access)
    network_access = NetworkAccess(candidate.network_access)
    validate_provider_execution_policy(
        route=route,
        provider_native_access=native_access,
        network_access=network_access,
    )
    return route, native_access, network_access


def _read_request_pair(
    paths: object,
    *,
    dispatch_id: str,
    instructions_logical_path: str | None,
    input_logical_path: str | None,
) -> tuple[bytes, bytes]:
    if instructions_logical_path is None or input_logical_path is None:
        raise ValueError("current starting dispatch is missing request refs")
    _require_exact_request_refs(
        dispatch_id,
        instructions_logical_path=instructions_logical_path,
        input_logical_path=input_logical_path,
    )
    instructions = read_logical_regular_file_bytes(paths, instructions_logical_path)
    input_bytes = read_logical_regular_file_bytes(paths, input_logical_path)
    instructions.decode("utf-8")
    input_bytes.decode("utf-8")
    return instructions, input_bytes


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


def _require_exact_request_refs(
    dispatch_id: str,
    *,
    instructions_logical_path: str,
    input_logical_path: str,
) -> None:
    expected_root = PurePosixPath("_runtime", "dispatch", dispatch_id)
    if (
        PurePosixPath(instructions_logical_path) != expected_root / "instructions.md"
        or PurePosixPath(input_logical_path) != expected_root / "input.md"
    ):
        raise ValueError("dispatch request refs do not identify the exact dispatch pair")


__all__ = ["PreparedProviderStart", "ProviderStartRequestBuilder"]
