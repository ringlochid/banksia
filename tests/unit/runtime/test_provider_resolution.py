from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from banksia.config import (
    CONFIG_ENV_VAR,
    ClaudeSettings,
    CodexSettings,
    OpenClawSettings,
    RuntimeSettings,
    Settings,
    load_settings,
)
from banksia.providers import (
    ManagedExtensionMode,
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
    ProviderNativeAccess,
)
from banksia.runtime.contracts import (
    CapabilitySource,
    EffectiveCapabilitySet,
    ExtensionModeResolutionSource,
    ProviderResolution,
    ProviderRoute,
    ProviderRouteValueSource,
    ProviderSelectionBasis,
)
from banksia.runtime.providers import (
    ProviderResolutionError,
    ProviderResolutionErrorCode,
    narrow_provider_capabilities,
    resolve_provider_route,
    validate_provider_execution_configuration,
)
from banksia.workflows.contracts import (
    ClaudeProviderSelection,
    CodexProviderSelection,
    OpenClawProviderSelection,
    ProviderSandbox,
)


def _settings(
    *,
    default_provider: ProviderKind | None = None,
    codex: CodexSettings | None = None,
    claude: ClaudeSettings | None = None,
    openclaw: OpenClawSettings | None = None,
) -> Settings:
    return Settings(
        runtime=RuntimeSettings(default_provider=default_provider),
        codex=codex or CodexSettings(),
        claude=claude or ClaudeSettings(),
        openclaw=openclaw or OpenClawSettings(),
    )


def test_sparse_settings_allow_zero_providers_and_no_default() -> None:
    settings = _settings()

    assert settings.runtime.default_provider is None
    assert not settings.codex.enabled
    assert not settings.claude.enabled
    assert not settings.openclaw.enabled


@pytest.mark.parametrize(
    "gateway_url",
    [
        "not-a-url",
        "  ",
        "http://127.0.0.1:18789",
        "ws://host name",
        "ws:///missing-host",
        "ws://[::1",
        "ws://user:secret@127.0.0.1:18789",
        "ws://127.0.0.1:18789/#fragment",
    ],
)
def test_openclaw_gateway_url_rejects_invalid_or_secret_bearing_values(
    gateway_url: str,
) -> None:
    settings = _settings(
        openclaw=OpenClawSettings(enabled=True, gateway_url=gateway_url),
    )

    with pytest.raises(ProviderResolutionError) as error:
        resolve_provider_route(
            provider=OpenClawProviderSelection(kind="openclaw"),
            settings=settings,
            available_adapter_kinds={ProviderKind.OPENCLAW},
        )

    assert error.value.code == ProviderResolutionErrorCode.INVALID_CONFIGURATION
    assert error.value.provider == ProviderKind.OPENCLAW


def test_invalid_unselected_openclaw_config_does_not_block_other_routes() -> None:
    settings = _settings(
        codex=CodexSettings(enabled=True),
        openclaw=OpenClawSettings(enabled=True, gateway_url="not-a-url"),
    )

    resolution = resolve_provider_route(
        provider=CodexProviderSelection(kind="codex"),
        settings=settings,
        available_adapter_kinds={ProviderKind.CODEX},
    )

    assert resolution.resolved_provider == ProviderKind.CODEX


def test_blank_unselected_provider_values_do_not_block_other_routes() -> None:
    settings = _settings(
        codex=CodexSettings(enabled=True),
        claude=ClaudeSettings(enabled=True, model="  "),
        openclaw=OpenClawSettings(enabled=True, gateway_url="  ", gateway_profile="  "),
    )

    resolution = resolve_provider_route(
        provider=CodexProviderSelection(kind="codex"),
        settings=settings,
        available_adapter_kinds={ProviderKind.CODEX},
    )

    assert resolution.resolved_provider == ProviderKind.CODEX


@pytest.mark.parametrize(
    ("selection", "settings"),
    [
        (
            CodexProviderSelection(kind="codex"),
            _settings(codex=CodexSettings(enabled=True, model="  ")),
        ),
        (
            ClaudeProviderSelection(kind="claude"),
            _settings(claude=ClaudeSettings(enabled=True, effort="")),
        ),
        (
            OpenClawProviderSelection(kind="openclaw"),
            _settings(
                openclaw=OpenClawSettings(
                    enabled=True,
                    gateway_url="ws://127.0.0.1:18789",
                    gateway_profile="  ",
                )
            ),
        ),
    ],
)
def test_selected_provider_rejects_explicit_blank_values(
    selection: CodexProviderSelection | ClaudeProviderSelection | OpenClawProviderSelection,
    settings: Settings,
) -> None:
    with pytest.raises(ProviderResolutionError) as error:
        resolve_provider_route(
            provider=selection,
            settings=settings,
            available_adapter_kinds=set(ProviderKind),
        )

    assert error.value.code == ProviderResolutionErrorCode.INVALID_CONFIGURATION
    assert error.value.provider == selection.kind


@pytest.mark.parametrize(
    ("selection", "settings"),
    [
        (
            CodexProviderSelection(kind="codex"),
            _settings(codex=CodexSettings(enabled=True, effort="impossible")),
        ),
        (
            ClaudeProviderSelection(kind="claude"),
            _settings(claude=ClaudeSettings(enabled=True, effort="minimal")),
        ),
    ],
)
def test_selected_provider_rejects_unsupported_effort_before_dispatch(
    selection: CodexProviderSelection | ClaudeProviderSelection,
    settings: Settings,
) -> None:
    with pytest.raises(ProviderResolutionError) as error:
        resolve_provider_route(
            provider=selection,
            settings=settings,
            available_adapter_kinds=set(ProviderKind),
        )

    assert error.value.code == ProviderResolutionErrorCode.INVALID_CONFIGURATION
    assert error.value.provider == selection.kind


@pytest.mark.parametrize(
    ("provider_native_access", "network_access", "sandbox_mode"),
    (
        (ProviderNativeAccess.DENIED, NetworkAccess.ALLOW, ManagedSandboxMode.READ_ONLY),
        (ProviderNativeAccess.FULL, NetworkAccess.DENY, ManagedSandboxMode.FULL_ACCESS),
    ),
)
def test_codex_inconsistent_sandbox_projections_are_rejected_before_dispatch(
    provider_native_access: ProviderNativeAccess,
    network_access: NetworkAccess,
    sandbox_mode: ManagedSandboxMode,
) -> None:
    resolution = resolve_provider_route(
        provider=CodexProviderSelection(kind="codex"),
        settings=_settings(codex=CodexSettings(enabled=True)),
        available_adapter_kinds={ProviderKind.CODEX},
    )

    with pytest.raises(ProviderResolutionError) as error:
        validate_provider_execution_configuration(
            route=resolution.route,
            provider_native_access=provider_native_access,
            network_access=network_access,
            sandbox_mode=sandbox_mode,
        )

    assert error.value.code == ProviderResolutionErrorCode.INVALID_CONFIGURATION
    assert error.value.provider == ProviderKind.CODEX


def test_codex_workspace_write_network_deny_projects_exact_adapter_access() -> None:
    resolution = resolve_provider_route(
        provider=CodexProviderSelection(
            kind="codex",
            sandbox=ProviderSandbox(mode="workspace_write", network="deny"),
        ),
        settings=_settings(codex=CodexSettings(enabled=True)),
        available_adapter_kinds={ProviderKind.CODEX},
    )
    capabilities = EffectiveCapabilitySet()

    effective = narrow_provider_capabilities(
        route=resolution.route,
        sandbox=resolution.sandbox,
        capabilities=capabilities,
    )

    assert effective.provider_native_access.effective is ProviderNativeAccess.RESTRICTED
    assert effective.provider_native_access.source is CapabilitySource.MEMBER_CONFIGURATION
    assert effective.network_access.effective is NetworkAccess.DENY
    assert effective.network_access.source is CapabilitySource.MEMBER_CONFIGURATION
    validate_provider_execution_configuration(
        route=resolution.route,
        provider_native_access=effective.provider_native_access.effective,
        network_access=effective.network_access.effective,
        sandbox_mode=ManagedSandboxMode.WORKSPACE_WRITE,
    )


def test_toml_source_loads_sparse_provider_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[runtime]
default_provider = "codex"

[codex]
enabled = true
model = "gpt-5"
effort = "high"

[claude]
enabled = false

[openclaw]
enabled = true
gateway_url = "ws://127.0.0.1:18789"
gateway_profile = "tested-local"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, str(config_path))

    settings = load_settings()

    assert settings.runtime.default_provider == ProviderKind.CODEX
    assert settings.codex.model_dump(mode="json") == {
        "enabled": True,
        "model": "gpt-5",
        "effort": "high",
        "extension_mode": "inherit",
    }
    assert settings.claude.model_dump(mode="json") == {
        "enabled": False,
        "model": None,
        "effort": None,
        "extension_mode": "inherit",
    }
    assert settings.openclaw.model_dump(mode="json") == {
        "enabled": True,
        "cli_path": "openclaw",
        "gateway_url": "ws://127.0.0.1:18789",
        "gateway_profile": "tested-local",
        "gateway_auth_mode": "token",
    }


@pytest.mark.parametrize(
    ("settings_type", "payload", "rejected_field"),
    [
        (CodexSettings, {"enabled": True, "api_key": "secret"}, "api_key"),
        (ClaudeSettings, {"enabled": True, "executable": "/bin/claude"}, "executable"),
        (
            OpenClawSettings,
            {"enabled": True, "gateway_token": "secret"},
            "gateway_token",
        ),
    ],
)
def test_provider_settings_reject_unknown_or_secret_fields(
    settings_type: type[CodexSettings] | type[ClaudeSettings] | type[OpenClawSettings],
    payload: dict[str, object],
    rejected_field: str,
) -> None:
    with pytest.raises(ValidationError, match=rejected_field):
        settings_type.model_validate(payload)


@pytest.mark.parametrize(
    ("selection", "settings", "expected_route"),
    [
        (
            CodexProviderSelection(kind="codex"),
            _settings(codex=CodexSettings(enabled=True, model="gpt-5", effort="high")),
            {
                "kind": "codex",
                "model_override": "gpt-5",
                "effort_override": "high",
            },
        ),
        (
            ClaudeProviderSelection(kind="claude"),
            _settings(claude=ClaudeSettings(enabled=True, model="opus", effort="high")),
            {
                "kind": "claude",
                "model_override": "opus",
                "effort_override": "high",
            },
        ),
        (
            OpenClawProviderSelection(kind="openclaw"),
            _settings(
                openclaw=OpenClawSettings(
                    enabled=True,
                    gateway_url="ws://127.0.0.1:18789",
                    gateway_profile="tested-local",
                )
            ),
            {"kind": "openclaw", "gateway_profile": "tested-local"},
        ),
    ],
)
def test_explicit_provider_resolution_constructs_exact_non_secret_route(
    selection: CodexProviderSelection | ClaudeProviderSelection | OpenClawProviderSelection,
    settings: Settings,
    expected_route: dict[str, object],
) -> None:
    resolution = resolve_provider_route(
        provider=selection,
        settings=settings,
        available_adapter_kinds=set(ProviderKind),
    )

    assert resolution.requested_provider == selection.kind
    assert resolution.resolved_provider == selection.kind
    assert resolution.selection_basis == ProviderSelectionBasis.EXPLICIT
    assert resolution.route.model_dump(mode="json") == expected_route
    if selection.kind in {ProviderKind.CODEX, ProviderKind.CLAUDE}:
        assert resolution.model_source is ProviderRouteValueSource.PROVIDER_CONFIGURATION
        assert resolution.effort_source is ProviderRouteValueSource.PROVIDER_CONFIGURATION
        assert resolution.gateway_profile_source is None
        assert resolution.extensions is not None
        assert resolution.extensions.requested_mode is ManagedExtensionMode.INHERIT
        assert resolution.extensions.effective_mode is ManagedExtensionMode.INHERIT
        assert (
            resolution.extensions.requested_source
            is ExtensionModeResolutionSource.PROVIDER_CONFIGURATION
        )
    else:
        assert resolution.model_source is None
        assert resolution.effort_source is None
        assert resolution.gateway_profile_source is ProviderRouteValueSource.PROVIDER_CONFIGURATION


def test_omitted_selection_resolves_only_the_configured_default() -> None:
    settings = _settings(
        default_provider=ProviderKind.CLAUDE,
        codex=CodexSettings(enabled=True),
        claude=ClaudeSettings(enabled=True, model="sonnet"),
    )

    resolution = resolve_provider_route(
        provider=None,
        settings=settings,
        available_adapter_kinds=set(ProviderKind),
    )

    assert resolution.requested_provider == ProviderKind.CLAUDE
    assert resolution.resolved_provider == ProviderKind.CLAUDE
    assert resolution.selection_basis == ProviderSelectionBasis.DEFAULT
    assert resolution.route.kind == ProviderKind.CLAUDE
    assert resolution.model_source is ProviderRouteValueSource.PROVIDER_CONFIGURATION


def test_member_extension_mode_is_exact_and_restricted_access_narrows_inherit() -> None:
    isolated = resolve_provider_route(
        provider=CodexProviderSelection(kind="codex", extension_mode="isolated"),
        settings=_settings(codex=CodexSettings(enabled=True)),
        available_adapter_kinds={ProviderKind.CODEX},
    )
    assert isolated.extensions is not None
    assert isolated.extensions.requested_mode is ManagedExtensionMode.ISOLATED
    assert isolated.extensions.effective_mode is ManagedExtensionMode.ISOLATED
    assert (
        isolated.extensions.requested_source is ExtensionModeResolutionSource.MEMBER_CONFIGURATION
    )

    narrowed = resolve_provider_route(
        provider=CodexProviderSelection(
            kind="codex",
            extension_mode="inherit",
            sandbox=ProviderSandbox(mode="workspace_write", network="deny"),
        ),
        settings=_settings(codex=CodexSettings(enabled=True)),
        available_adapter_kinds={ProviderKind.CODEX},
    )
    assert narrowed.extensions is not None
    assert narrowed.extensions.requested_mode is ManagedExtensionMode.INHERIT
    assert narrowed.extensions.effective_mode is ManagedExtensionMode.ISOLATED
    assert narrowed.extensions.effective_source is ExtensionModeResolutionSource.CONTROLLER


def test_experimental_openclaw_route_remains_default_eligible() -> None:
    settings = _settings(
        default_provider=ProviderKind.OPENCLAW,
        openclaw=OpenClawSettings(
            enabled=True,
            gateway_url="ws://127.0.0.1:18789",
            gateway_profile="experimental",
        ),
    )

    resolution = resolve_provider_route(
        provider=None,
        settings=settings,
        available_adapter_kinds={ProviderKind.OPENCLAW},
    )

    assert resolution.requested_provider == ProviderKind.OPENCLAW
    assert resolution.resolved_provider == ProviderKind.OPENCLAW
    assert resolution.selection_basis == ProviderSelectionBasis.DEFAULT
    assert resolution.route.model_dump(mode="json") == {
        "kind": "openclaw",
        "gateway_profile": "experimental",
    }


def test_missing_default_is_a_route_error() -> None:
    with pytest.raises(ProviderResolutionError) as error:
        resolve_provider_route(
            provider=None,
            settings=_settings(codex=CodexSettings(enabled=True)),
            available_adapter_kinds={ProviderKind.CODEX},
        )

    assert error.value.code == ProviderResolutionErrorCode.DEFAULT_NOT_CONFIGURED
    assert error.value.provider is None


def test_disabled_default_fails_without_scanning_for_fallback() -> None:
    settings = _settings(
        default_provider=ProviderKind.CODEX,
        codex=CodexSettings(enabled=False),
        claude=ClaudeSettings(enabled=True),
    )

    with pytest.raises(ProviderResolutionError) as error:
        resolve_provider_route(
            provider=None,
            settings=settings,
            available_adapter_kinds={ProviderKind.CODEX, ProviderKind.CLAUDE},
        )

    assert error.value.code == ProviderResolutionErrorCode.PROVIDER_DISABLED
    assert error.value.provider == ProviderKind.CODEX


def test_invalid_default_fails_without_scanning_for_fallback() -> None:
    settings = _settings(
        default_provider=ProviderKind.OPENCLAW,
        codex=CodexSettings(enabled=True),
        openclaw=OpenClawSettings(enabled=True, gateway_url="not-a-url"),
    )

    with pytest.raises(ProviderResolutionError) as error:
        resolve_provider_route(
            provider=None,
            settings=settings,
            available_adapter_kinds={ProviderKind.CODEX, ProviderKind.OPENCLAW},
        )

    assert error.value.code == ProviderResolutionErrorCode.INVALID_CONFIGURATION
    assert error.value.provider == ProviderKind.OPENCLAW


def test_explicit_selection_never_falls_back_to_an_enabled_default() -> None:
    settings = _settings(
        default_provider=ProviderKind.CLAUDE,
        codex=CodexSettings(enabled=False),
        claude=ClaudeSettings(enabled=True),
    )

    with pytest.raises(ProviderResolutionError) as error:
        resolve_provider_route(
            provider=CodexProviderSelection(kind="codex"),
            settings=settings,
            available_adapter_kinds={ProviderKind.CODEX, ProviderKind.CLAUDE},
        )

    assert error.value.code == ProviderResolutionErrorCode.PROVIDER_DISABLED
    assert error.value.provider == ProviderKind.CODEX


def test_selected_provider_requires_an_available_adapter() -> None:
    with pytest.raises(ProviderResolutionError) as error:
        resolve_provider_route(
            provider=CodexProviderSelection(kind="codex"),
            settings=_settings(codex=CodexSettings(enabled=True)),
            available_adapter_kinds={ProviderKind.CLAUDE},
        )

    assert error.value.code == ProviderResolutionErrorCode.ADAPTER_UNAVAILABLE
    assert error.value.provider == ProviderKind.CODEX


def test_provider_route_union_rejects_fields_from_another_variant() -> None:
    with pytest.raises(ValidationError, match="gateway_profile"):
        TypeAdapter(ProviderRoute).validate_python(
            {
                "kind": "codex",
                "model_override": None,
                "effort_override": None,
                "gateway_profile": "default",
            }
        )


def test_provider_resolution_rejects_non_exact_provenance() -> None:
    with pytest.raises(ValidationError, match="requested_provider"):
        ProviderResolution.model_validate(
            {
                "requested_provider": "codex",
                "resolved_provider": "claude",
                "selection_basis": "explicit",
                "route": {
                    "kind": "codex",
                    "model_override": None,
                    "effort_override": None,
                },
                "sandbox": {
                    "requested_mode": "full_access",
                    "requested_network": "allow",
                    "requested_source": "default",
                    "effective_mode": "full_access",
                    "effective_network": "allow",
                    "effective_mode_source": "default",
                    "effective_network_source": "default",
                },
                "extensions": {
                    "requested_mode": "inherit",
                    "requested_source": "provider_configuration",
                    "effective_mode": "inherit",
                    "effective_source": "provider_configuration",
                },
                "model_source": "provider_configuration",
                "effort_source": "provider_configuration",
                "gateway_profile_source": None,
            }
        )
