from __future__ import annotations

from oh_my_subagents.config import ClaudeSettings, CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.providers import ManagedSandboxMode, NetworkAccess, ProviderKind
from oh_my_subagents.runtime.contracts import (
    CodexProviderRoute,
    ProviderRouteValueSource,
    SandboxResolutionSource,
)
from oh_my_subagents.runtime.providers import resolve_provider_route
from oh_my_subagents.workflows.contracts import (
    ClaudeProviderSelection,
    CodexProviderSelection,
    ProviderSandbox,
)


def test_exact_authored_model_effort_and_sandbox_override_controller_defaults() -> None:
    settings = Settings(
        runtime=RuntimeSettings(default_provider=ProviderKind.CLAUDE),
        codex=CodexSettings(enabled=True, model="controller-model", effort="low"),
        claude=ClaudeSettings(enabled=True),
    )

    resolution = resolve_provider_route(
        provider=CodexProviderSelection(
            kind="codex",
            model="authored-model",
            effort="high",
            sandbox=ProviderSandbox(mode="workspace_write", network="deny"),
        ),
        settings=settings,
        available_adapter_kinds={ProviderKind.CODEX, ProviderKind.CLAUDE},
    )

    assert resolution.requested_provider is ProviderKind.CODEX
    assert resolution.resolved_provider is ProviderKind.CODEX
    assert isinstance(resolution.route, CodexProviderRoute)
    assert resolution.route.model_override == "authored-model"
    assert resolution.route.effort_override == "high"
    assert resolution.model_source is ProviderRouteValueSource.MEMBER_CONFIGURATION
    assert resolution.effort_source is ProviderRouteValueSource.MEMBER_CONFIGURATION
    assert resolution.sandbox is not None
    assert resolution.sandbox.requested_mode is ManagedSandboxMode.WORKSPACE_WRITE
    assert resolution.sandbox.requested_network is NetworkAccess.DENY
    assert resolution.sandbox.requested_source is SandboxResolutionSource.MEMBER_CONFIGURATION
    assert resolution.sandbox.effective_mode is ManagedSandboxMode.WORKSPACE_WRITE
    assert resolution.sandbox.effective_network is NetworkAccess.DENY


def test_omitted_managed_sandbox_defaults_full_access_and_network_allow() -> None:
    settings = Settings(codex=CodexSettings(enabled=True))

    resolution = resolve_provider_route(
        provider=CodexProviderSelection(kind="codex"),
        settings=settings,
        available_adapter_kinds={ProviderKind.CODEX},
    )

    assert resolution.sandbox is not None
    assert resolution.sandbox.requested_mode is ManagedSandboxMode.FULL_ACCESS
    assert resolution.sandbox.requested_network is NetworkAccess.ALLOW
    assert resolution.sandbox.requested_source is SandboxResolutionSource.DEFAULT
    assert resolution.sandbox.effective_mode is ManagedSandboxMode.FULL_ACCESS
    assert resolution.sandbox.effective_network is NetworkAccess.ALLOW


def test_controller_can_only_narrow_managed_sandbox_request() -> None:
    settings = Settings(
        runtime=RuntimeSettings(
            managed_provider_sandbox_mode=ManagedSandboxMode.READ_ONLY,
            managed_provider_network_access=NetworkAccess.DENY,
        ),
        claude=ClaudeSettings(enabled=True),
    )

    resolution = resolve_provider_route(
        provider=ClaudeProviderSelection(
            kind="claude",
            sandbox=ProviderSandbox(mode="full_access", network="allow"),
        ),
        settings=settings,
        available_adapter_kinds={ProviderKind.CLAUDE},
    )

    assert resolution.sandbox is not None
    assert resolution.sandbox.requested_mode is ManagedSandboxMode.FULL_ACCESS
    assert resolution.sandbox.effective_mode is ManagedSandboxMode.READ_ONLY
    assert resolution.sandbox.effective_network is NetworkAccess.DENY
    assert resolution.sandbox.effective_mode_source is SandboxResolutionSource.CONTROLLER
    assert resolution.sandbox.effective_network_source is SandboxResolutionSource.CONTROLLER
