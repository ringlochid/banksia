from __future__ import annotations

from collections.abc import Collection, Mapping
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError, WebsocketUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import Settings
from banksia.persistence.models import MemberConfigurationModel
from banksia.providers import (
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
    ProviderNativeAccess,
)
from banksia.runtime.contracts.capabilities import (
    CapabilitySource,
    EffectiveCapabilitySet,
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
)
from banksia.runtime.contracts.provider_resolution import (
    ClaudeProviderRoute,
    CodexProviderRoute,
    ManagedSandboxResolution,
    OpenClawProviderRoute,
    ProviderResolution,
    ProviderRoute,
    ProviderRouteValueSource,
    ProviderSelectionBasis,
    SandboxResolutionSource,
)
from banksia.workflows.contracts import (
    ClaudeProviderSelection,
    CodexProviderSelection,
    OpenClawProviderSelection,
    ProviderSelection,
)

_WEBSOCKET_URL_ADAPTER = TypeAdapter(WebsocketUrl)
_PROVIDER_SELECTION_ADAPTER: TypeAdapter[ProviderSelection] = TypeAdapter(ProviderSelection)
_CODEX_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})
_CLAUDE_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


class ProviderResolutionErrorCode(StrEnum):
    DEFAULT_NOT_CONFIGURED = "provider_default_not_configured"
    PROVIDER_DISABLED = "provider_disabled"
    INVALID_CONFIGURATION = "provider_invalid_configuration"
    ADAPTER_UNAVAILABLE = "provider_adapter_unavailable"


class ProviderResolutionError(ValueError):
    def __init__(
        self,
        *,
        code: ProviderResolutionErrorCode,
        provider: ProviderKind | None,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider


async def resolve_member_provider_route(
    session: AsyncSession,
    *,
    task_id: str,
    member_configuration_id: str,
    settings: Settings,
    available_adapter_kinds: Collection[ProviderKind],
) -> ProviderResolution:
    """Resolve the authored provider route pinned by one MemberConfiguration."""

    return resolve_provider_route(
        provider=await read_member_provider_selection(
            session,
            task_id=task_id,
            member_configuration_id=member_configuration_id,
        ),
        settings=settings,
        available_adapter_kinds=available_adapter_kinds,
    )


def resolve_provider_route(
    *,
    provider: ProviderSelection | None,
    settings: Settings,
    available_adapter_kinds: Collection[ProviderKind],
) -> ProviderResolution:
    selected_provider, selection_basis = _select_provider(provider, settings=settings)
    if not _provider_is_enabled(selected_provider, settings=settings):
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.PROVIDER_DISABLED,
            provider=selected_provider,
            message=f"provider '{selected_provider.value}' is disabled",
        )
    route, model_source, effort_source, gateway_profile_source = _build_provider_route(
        provider,
        selected_provider,
        settings=settings,
    )
    if selected_provider not in available_adapter_kinds:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.ADAPTER_UNAVAILABLE,
            provider=selected_provider,
            message=f"provider adapter '{selected_provider.value}' is unavailable",
        )

    return ProviderResolution(
        requested_provider=selected_provider,
        resolved_provider=selected_provider,
        selection_basis=selection_basis,
        route=route,
        sandbox=_resolve_managed_sandbox(provider, selected_provider, settings=settings),
        model_source=model_source,
        effort_source=effort_source,
        gateway_profile_source=gateway_profile_source,
    )


def provider_selection_from_kind(
    provider_kind: ProviderKind | str | None,
) -> ProviderSelection | None:
    """Rebuild the strict authored selection carried by a persisted node."""

    if provider_kind is None:
        return None
    match ProviderKind(provider_kind):
        case ProviderKind.CODEX:
            return CodexProviderSelection(kind="codex")
        case ProviderKind.CLAUDE:
            return ClaudeProviderSelection(kind="claude")
        case ProviderKind.OPENCLAW:
            return OpenClawProviderSelection(kind="openclaw")


def provider_selection_from_mapping(
    provider: Mapping[str, object] | None,
) -> ProviderSelection | None:
    """Validate one persisted or candidate authored provider selection."""

    if provider is None:
        return None
    return _PROVIDER_SELECTION_ADAPTER.validate_python(provider)


async def read_member_provider_selection(
    session: AsyncSession,
    *,
    task_id: str,
    member_configuration_id: str,
) -> ProviderSelection | None:
    """Read authored provider intent from one exact immutable MemberConfiguration."""

    requested = await session.scalar(
        select(MemberConfigurationModel.requested_provider_json).where(
            MemberConfigurationModel.task_id == task_id,
            MemberConfigurationModel.member_configuration_id == member_configuration_id,
        )
    )
    return provider_selection_from_mapping(requested)


def validate_provider_execution_configuration(
    *,
    route: ProviderRoute,
    provider_native_access: ProviderNativeAccess,
    network_access: NetworkAccess,
    sandbox_mode: ManagedSandboxMode | None = None,
) -> None:
    """Reject deterministic adapter-configuration gaps before creating a Dispatch."""

    if route.kind is ProviderKind.OPENCLAW:
        if sandbox_mode is not None:
            raise ProviderResolutionError(
                code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
                provider=route.kind,
                message="OpenClaw dispatches do not carry a controller-managed sandbox",
            )
        return
    if sandbox_mode is None:
        return
    expected_native = _native_access_for_sandbox(sandbox_mode)
    if provider_native_access is not expected_native:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=route.kind,
            message="managed sandbox mode and provider-native projection disagree",
        )
    legal_network = (
        NetworkAccess.DENY
        if sandbox_mode is ManagedSandboxMode.READ_ONLY
        else NetworkAccess.ALLOW
        if sandbox_mode is ManagedSandboxMode.FULL_ACCESS
        else network_access
    )
    if network_access is not legal_network:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=route.kind,
            message="managed sandbox mode and network projection form an illegal pair",
        )


def narrow_provider_capabilities(
    *,
    route: ProviderRoute,
    capabilities: EffectiveCapabilitySet,
    sandbox: ManagedSandboxResolution | None = None,
) -> EffectiveCapabilitySet:
    """Narrow effective capabilities to one provider-local hard ceiling."""

    if route.kind is ProviderKind.OPENCLAW or sandbox is None:
        return capabilities
    return capabilities.model_copy(
        update={
            "provider_native_access": EffectiveProviderNativeAccess(
                effective=_native_access_for_sandbox(sandbox.effective_mode),
                source=CapabilitySource(sandbox.effective_mode_source.value),
            ),
            "network_access": EffectiveNetworkAccess(
                effective=sandbox.effective_network,
                source=CapabilitySource(sandbox.effective_network_source.value),
            ),
        }
    )


def _native_access_for_sandbox(mode: ManagedSandboxMode) -> ProviderNativeAccess:
    match mode:
        case ManagedSandboxMode.READ_ONLY:
            return ProviderNativeAccess.DENIED
        case ManagedSandboxMode.WORKSPACE_WRITE:
            return ProviderNativeAccess.RESTRICTED
        case ManagedSandboxMode.FULL_ACCESS:
            return ProviderNativeAccess.FULL


def _select_provider(
    provider: ProviderSelection | None,
    *,
    settings: Settings,
) -> tuple[ProviderKind, ProviderSelectionBasis]:
    if provider is not None:
        return ProviderKind(provider.kind), ProviderSelectionBasis.EXPLICIT
    if settings.runtime.default_provider is None:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.DEFAULT_NOT_CONFIGURED,
            provider=None,
            message="runtime.default_provider is not configured",
        )
    return settings.runtime.default_provider, ProviderSelectionBasis.DEFAULT


def _provider_is_enabled(provider: ProviderKind, *, settings: Settings) -> bool:
    match provider:
        case ProviderKind.CODEX:
            return settings.codex.enabled
        case ProviderKind.CLAUDE:
            return settings.claude.enabled
        case ProviderKind.OPENCLAW:
            return settings.openclaw.enabled


def _resolve_managed_sandbox(
    selection: ProviderSelection | None,
    provider: ProviderKind,
    *,
    settings: Settings,
) -> ManagedSandboxResolution | None:
    if provider is ProviderKind.OPENCLAW:
        return None

    authored_sandbox = (
        selection.sandbox
        if isinstance(selection, CodexProviderSelection | ClaudeProviderSelection)
        else None
    )
    if authored_sandbox is None:
        requested_mode = ManagedSandboxMode.FULL_ACCESS
        requested_network = NetworkAccess.ALLOW
        requested_source = SandboxResolutionSource.DEFAULT
    else:
        requested_mode = ManagedSandboxMode(authored_sandbox.mode)
        requested_network = NetworkAccess(authored_sandbox.network)
        requested_source = SandboxResolutionSource.MEMBER_CONFIGURATION

    controller_mode = settings.runtime.managed_provider_sandbox_mode
    controller_network = settings.runtime.managed_provider_network_access
    mode_order = {
        ManagedSandboxMode.READ_ONLY: 0,
        ManagedSandboxMode.WORKSPACE_WRITE: 1,
        ManagedSandboxMode.FULL_ACCESS: 2,
    }
    if mode_order[controller_mode] < mode_order[requested_mode]:
        effective_mode = controller_mode
        effective_mode_source = SandboxResolutionSource.CONTROLLER
    else:
        effective_mode = requested_mode
        effective_mode_source = requested_source

    if requested_network is NetworkAccess.DENY:
        effective_network = NetworkAccess.DENY
        effective_network_source = requested_source
    elif controller_network is NetworkAccess.DENY:
        effective_network = NetworkAccess.DENY
        effective_network_source = SandboxResolutionSource.CONTROLLER
    else:
        effective_network = NetworkAccess.ALLOW
        effective_network_source = requested_source

    if effective_mode is ManagedSandboxMode.FULL_ACCESS and effective_network is NetworkAccess.DENY:
        effective_mode = ManagedSandboxMode.WORKSPACE_WRITE
        effective_mode_source = SandboxResolutionSource.CONTROLLER
    if effective_mode is ManagedSandboxMode.READ_ONLY:
        effective_network = NetworkAccess.DENY
        if requested_network is not NetworkAccess.DENY:
            effective_network_source = SandboxResolutionSource.CONTROLLER

    return ManagedSandboxResolution(
        requested_mode=requested_mode,
        requested_network=requested_network,
        requested_source=requested_source,
        effective_mode=effective_mode,
        effective_network=effective_network,
        effective_mode_source=effective_mode_source,
        effective_network_source=effective_network_source,
    )


def _build_provider_route(
    selection: ProviderSelection | None,
    provider: ProviderKind,
    *,
    settings: Settings,
) -> tuple[
    CodexProviderRoute | ClaudeProviderRoute | OpenClawProviderRoute,
    ProviderRouteValueSource | None,
    ProviderRouteValueSource | None,
    ProviderRouteValueSource | None,
]:
    match provider:
        case ProviderKind.CODEX:
            codex_selection = selection if isinstance(selection, CodexProviderSelection) else None
            codex_authored_model = codex_selection.model if codex_selection is not None else None
            codex_authored_effort = codex_selection.effort if codex_selection is not None else None
            model_is_authored = codex_authored_model is not None
            effort_is_authored = codex_authored_effort is not None
            return (
                CodexProviderRoute(
                    kind=ProviderKind.CODEX,
                    model_override=_validate_optional_override(
                        codex_authored_model if model_is_authored else settings.codex.model,
                        provider=ProviderKind.CODEX,
                        field_name="provider.model" if model_is_authored else "codex.model",
                    ),
                    effort_override=_validate_optional_effort(
                        codex_authored_effort if effort_is_authored else settings.codex.effort,
                        provider=ProviderKind.CODEX,
                        field_name="provider.effort" if effort_is_authored else "codex.effort",
                        supported=_CODEX_EFFORTS,
                    ),
                ),
                _route_value_source(model_is_authored),
                _route_value_source(effort_is_authored),
                None,
            )
        case ProviderKind.CLAUDE:
            claude_selection = selection if isinstance(selection, ClaudeProviderSelection) else None
            claude_authored_model = claude_selection.model if claude_selection is not None else None
            claude_authored_effort = (
                claude_selection.effort if claude_selection is not None else None
            )
            model_is_authored = claude_authored_model is not None
            effort_is_authored = claude_authored_effort is not None
            return (
                ClaudeProviderRoute(
                    kind=ProviderKind.CLAUDE,
                    model_override=_validate_optional_override(
                        claude_authored_model if model_is_authored else settings.claude.model,
                        provider=ProviderKind.CLAUDE,
                        field_name="provider.model" if model_is_authored else "claude.model",
                    ),
                    effort_override=_validate_optional_effort(
                        claude_authored_effort if effort_is_authored else settings.claude.effort,
                        provider=ProviderKind.CLAUDE,
                        field_name="provider.effort" if effort_is_authored else "claude.effort",
                        supported=_CLAUDE_EFFORTS,
                    ),
                ),
                _route_value_source(model_is_authored),
                _route_value_source(effort_is_authored),
                None,
            )
        case ProviderKind.OPENCLAW:
            _validate_openclaw_gateway_url(settings.openclaw.gateway_url)
            return (
                OpenClawProviderRoute(
                    kind=ProviderKind.OPENCLAW,
                    gateway_profile=_validate_required_value(
                        settings.openclaw.gateway_profile,
                        provider=ProviderKind.OPENCLAW,
                        field_name="openclaw.gateway_profile",
                    ),
                ),
                None,
                None,
                ProviderRouteValueSource.PROVIDER_CONFIGURATION,
            )


def _route_value_source(is_authored: bool) -> ProviderRouteValueSource:
    if is_authored:
        return ProviderRouteValueSource.MEMBER_CONFIGURATION
    return ProviderRouteValueSource.PROVIDER_CONFIGURATION


def _validate_optional_override(
    value: str | None,
    *,
    provider: ProviderKind,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _validate_required_value(value, provider=provider, field_name=field_name)


def _validate_optional_effort(
    value: str | None,
    *,
    provider: ProviderKind,
    field_name: str,
    supported: frozenset[str],
) -> str | None:
    normalized = _validate_optional_override(
        value,
        provider=provider,
        field_name=field_name,
    )
    if normalized is None:
        return None
    if normalized not in supported:
        choices = ", ".join(sorted(supported))
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=provider,
            message=f"{field_name} must be one of: {choices}",
        )
    return normalized


def _validate_required_value(
    value: str,
    *,
    provider: ProviderKind,
    field_name: str,
) -> str:
    if not value:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=provider,
            message=f"{field_name} must not be blank when configured",
        )
    return value


def _validate_openclaw_gateway_url(value: str) -> None:
    try:
        raw_url = urlsplit(value)
    except ValueError as exc:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=ProviderKind.OPENCLAW,
            message="openclaw.gateway_url must be a valid ws or wss URL",
        ) from exc
    if raw_url.scheme not in {"ws", "wss"} or not raw_url.netloc:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=ProviderKind.OPENCLAW,
            message="openclaw.gateway_url must be an absolute ws or wss URL with a host",
        )
    try:
        parsed = _WEBSOCKET_URL_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=ProviderKind.OPENCLAW,
            message="openclaw.gateway_url must be a valid ws or wss URL",
        ) from exc
    if parsed.username is not None or parsed.password is not None:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=ProviderKind.OPENCLAW,
            message="openclaw.gateway_url must not contain credentials",
        )
    if parsed.fragment:
        raise ProviderResolutionError(
            code=ProviderResolutionErrorCode.INVALID_CONFIGURATION,
            provider=ProviderKind.OPENCLAW,
            message="openclaw.gateway_url must not contain a fragment",
        )


__all__ = [
    "ProviderResolutionError",
    "ProviderResolutionErrorCode",
    "narrow_provider_capabilities",
    "provider_selection_from_kind",
    "provider_selection_from_mapping",
    "read_member_provider_selection",
    "resolve_member_provider_route",
    "resolve_provider_route",
    "validate_provider_execution_configuration",
]
