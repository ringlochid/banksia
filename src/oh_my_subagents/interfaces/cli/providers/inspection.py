from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from oh_my_subagents.config import Settings
from oh_my_subagents.integrations.claude.native_identity import bundled_claude_path
from oh_my_subagents.interfaces.cli.providers.configuration import product_status_for
from oh_my_subagents.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
    ProviderDefinitionSnapshot,
    ProviderStatusSnapshot,
)
from oh_my_subagents.interfaces.cli.providers.identity import (
    bundled_codex_path,
    provider_native_home,
    service_identity,
)
from oh_my_subagents.providers import ACTIVE_PROVIDER_KINDS, ProviderKind
from oh_my_subagents.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderResolutionError,
    provider_selection_from_kind,
    resolve_provider_route,
)

PROVIDER_ORDER = ACTIVE_PROVIDER_KINDS
PROVIDER_CHECK_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class _ProviderCheckBasis:
    kind: ProviderKind
    service_identity: str
    native_home: str
    limitations: tuple[str, ...]

    def snapshot(
        self,
        *,
        outcome: ProviderCheckOutcome,
        is_ready: bool | None,
        detail: str,
        authentication: ProviderCheckAxisStatus = ProviderCheckAxisStatus.NOT_CHECKED,
        authentication_method: ProviderAuthenticationMethod | None = None,
        reachability: ProviderCheckAxisStatus = ProviderCheckAxisStatus.NOT_CHECKED,
    ) -> ProviderCheckSnapshot:
        return ProviderCheckSnapshot(
            kind=self.kind,
            outcome=outcome,
            is_ready=is_ready,
            service_identity=self.service_identity,
            native_home=self.native_home,
            authentication=authentication,
            authentication_method=authentication_method,
            reachability=reachability,
            detail=detail,
            limitations=self.limitations,
        )


def collect_provider_check(
    settings: Settings,
    provider: ProviderKind,
) -> ProviderCheckSnapshot:
    status = collect_provider_status(settings, provider)
    basis = _ProviderCheckBasis(
        kind=provider,
        service_identity=status.service_identity,
        native_home=status.native_home,
        limitations=status.limitations,
    )
    if not status.is_configured:
        return basis.snapshot(
            outcome=ProviderCheckOutcome.NOT_CONFIGURED,
            is_ready=False,
            detail=f"provider '{provider.value}' is not enabled in Oh My Subagents config",
        )
    if not status.is_integration_available:
        return basis.snapshot(
            outcome=ProviderCheckOutcome.NOT_INSTALLED,
            is_ready=False,
            detail=f"provider integration '{provider.value}' is not locally available",
        )
    try:
        resolve_provider_route(
            provider=provider_selection_from_kind(provider),
            settings=settings,
            available_adapter_kinds=ACTIVE_PROVIDER_KINDS,
        )
    except ProviderResolutionError as exc:
        return basis.snapshot(
            outcome=ProviderCheckOutcome.INCOMPATIBLE,
            is_ready=False,
            detail=str(exc),
        )
    try:
        result = execute_provider_diagnostic(settings, provider)
    except TimeoutError:
        return basis.snapshot(
            outcome=ProviderCheckOutcome.UNREACHABLE,
            is_ready=False,
            detail="the bounded provider diagnostic timed out",
        )
    except Exception:
        return basis.snapshot(
            outcome=ProviderCheckOutcome.CHECK_FAILED,
            is_ready=False,
            detail="the bounded provider diagnostic failed",
        )
    return provider_check_snapshot(basis=basis, result=result)


def collect_provider_definitions() -> tuple[ProviderDefinitionSnapshot, ...]:
    return tuple(
        ProviderDefinitionSnapshot.model_validate(
            {
                "kind": provider,
                "integration": integration_name(provider),
                "product_status": product_status_for(provider),
                "integration_available": is_provider_integration_available(provider),
                "setup_owner": "banksia",
            }
        )
        for provider in PROVIDER_ORDER
    )


def collect_provider_statuses(
    settings: Settings,
    provider: ProviderKind | None = None,
) -> tuple[ProviderStatusSnapshot, ...]:
    selected = (provider,) if provider is not None else PROVIDER_ORDER
    return tuple(collect_provider_status(settings, item) for item in selected)


def collect_provider_status(
    settings: Settings,
    provider: ProviderKind,
) -> ProviderStatusSnapshot:
    configured = provider_is_enabled(settings, provider)
    return ProviderStatusSnapshot.model_validate(
        {
            "kind": provider,
            "product_status": product_status_for(provider),
            "integration_available": is_provider_integration_available(provider, settings),
            "configured": configured,
            "is_default": settings.runtime.default_provider == provider,
            "configuration_fields_present": provider_fields_are_present(settings, provider),
            "service_identity": service_identity(),
            "native_home": str(provider_native_home(provider)),
            "route": provider_route_readback(settings, provider),
            "limitations": provider_limitations(provider),
        }
    )


def execute_provider_diagnostic(
    settings: Settings,
    provider: ProviderKind,
) -> ProviderCheckResult:
    """Run one explicit bounded non-agent adapter diagnostic."""

    from oh_my_subagents.integrations.provider_registry import build_provider_adapter

    async def run() -> ProviderCheckResult:
        adapter = build_provider_adapter(provider, settings)
        async with asyncio.timeout(PROVIDER_CHECK_TIMEOUT_SECONDS):
            async with adapter.lifespan():
                return await adapter.read_availability()

    return asyncio.run(run())


def provider_check_snapshot(
    *,
    basis: _ProviderCheckBasis,
    result: ProviderCheckResult,
) -> ProviderCheckSnapshot:
    if result.authentication is ProviderCheckAxisStatus.FAILED:
        return basis.snapshot(
            outcome=ProviderCheckOutcome.AUTHENTICATION_FAILED,
            is_ready=False,
            detail=result.code,
            authentication=result.authentication,
            authentication_method=result.authentication_method,
            reachability=result.reachability,
        )
    if (
        result.status in {ProviderCheckStatus.AVAILABLE, ProviderCheckStatus.LIMITED}
        and result.authentication is ProviderCheckAxisStatus.PASSED
    ):
        return basis.snapshot(
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail=result.code,
            authentication=result.authentication,
            authentication_method=result.authentication_method,
            reachability=result.reachability,
        )

    if result.status in {ProviderCheckStatus.AVAILABLE, ProviderCheckStatus.LIMITED}:
        return basis.snapshot(
            outcome=ProviderCheckOutcome.LOCAL_PREREQUISITES_READY,
            is_ready=None,
            detail=result.code,
            authentication=result.authentication,
            authentication_method=result.authentication_method,
            reachability=result.reachability,
        )

    code = result.code
    if "auth" in code:
        outcome = ProviderCheckOutcome.AUTHENTICATION_FAILED
    elif any(marker in code for marker in ("connection", "timeout", "unreachable")):
        outcome = ProviderCheckOutcome.UNREACHABLE
    elif any(marker in code for marker in ("incompatible", "rejected", "unsupported")):
        outcome = ProviderCheckOutcome.INCOMPATIBLE
    else:
        outcome = ProviderCheckOutcome.CHECK_FAILED
    return basis.snapshot(
        outcome=outcome,
        is_ready=False,
        detail=code,
        authentication=result.authentication,
        authentication_method=result.authentication_method,
        reachability=result.reachability,
    )


def integration_name(provider: ProviderKind) -> str:
    match provider:
        case ProviderKind.CODEX:
            return "Codex managed SDK/app-server"
        case ProviderKind.CLAUDE:
            return "Claude managed Agent SDK"
        case ProviderKind.OPENCLAW:
            raise ValueError("OpenClaw is retired")


def is_provider_integration_available(
    provider: ProviderKind,
    settings: Settings | None = None,
) -> bool:
    del settings
    match provider:
        case ProviderKind.CODEX:
            return module_is_available("openai_codex") and _bundled_cli_is_available(
                bundled_codex_path
            )
        case ProviderKind.CLAUDE:
            return module_is_available("claude_agent_sdk") and _bundled_cli_is_available(
                bundled_claude_path
            )
        case ProviderKind.OPENCLAW:
            return False


def module_is_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def provider_fields_are_present(settings: Settings, provider: ProviderKind) -> bool:
    match provider:
        case ProviderKind.CODEX | ProviderKind.CLAUDE:
            return provider_is_enabled(settings, provider)
        case ProviderKind.OPENCLAW:
            return False


def provider_is_enabled(settings: Settings, provider: ProviderKind) -> bool:
    match provider:
        case ProviderKind.CODEX:
            return settings.codex.enabled
        case ProviderKind.CLAUDE:
            return settings.claude.enabled
        case ProviderKind.OPENCLAW:
            return False


def provider_route_readback(
    settings: Settings,
    provider: ProviderKind,
) -> dict[str, str | bool | None]:
    match provider:
        case ProviderKind.CODEX:
            return {
                "enabled": settings.codex.enabled,
                "model": settings.codex.model,
                "effort": settings.codex.effort,
                "extension_mode": settings.codex.extension_mode.value,
            }
        case ProviderKind.CLAUDE:
            return {
                "enabled": settings.claude.enabled,
                "model": settings.claude.model,
                "effort": settings.claude.effort,
                "extension_mode": settings.claude.extension_mode.value,
            }
        case ProviderKind.OPENCLAW:
            raise ValueError("OpenClaw is retired")


def provider_limitations(provider: ProviderKind) -> tuple[str, ...]:
    if provider == ProviderKind.CODEX:
        return (
            "the pinned Codex app-server cannot enforce MCP-only provider-native "
            "access denied; that route is rejected before dispatch creation",
            "when network access is denied, the pinned Codex sandbox narrows full "
            "provider-native access to restricted with controller provenance",
        )
    return ()


def providers_payload(
    snapshots: Sequence[
        ProviderDefinitionSnapshot | ProviderStatusSnapshot | ProviderCheckSnapshot
    ],
) -> list[dict[str, object]]:
    return [snapshot.model_dump(mode="json") for snapshot in snapshots]


def _bundled_cli_is_available(resolver: Callable[[], Path]) -> bool:
    try:
        path = resolver()
    except (FileNotFoundError, ImportError, OSError):
        return False
    return path.is_file()


__all__ = [
    "PROVIDER_ORDER",
    "collect_provider_check",
    "collect_provider_definitions",
    "collect_provider_status",
    "collect_provider_statuses",
    "execute_provider_diagnostic",
    "integration_name",
    "is_provider_integration_available",
    "module_is_available",
    "provider_native_home",
    "providers_payload",
    "service_identity",
]
