from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import click

from banksia.config import (
    OpenClawGatewayAuthMode,
    Settings,
    load_settings,
)
from banksia.interfaces.cli.bootstrap.config import read_config_sections
from banksia.interfaces.cli.commands.presentation import (
    emit_completion,
    emit_key_value_panel,
    emit_provider_choices,
    emit_step,
    emit_success,
    emit_warning,
    emit_wizard_header,
)
from banksia.interfaces.cli.commands.provider_authentication import (
    existing_credential_prompt,
    prompt_authentication_method,
    prompt_provider_secret,
    prompt_shell_secret_import,
    provider_display_name,
    read_shell_authentication_method,
)
from banksia.interfaces.cli.commands.providers import (
    provider_configuration_request_from_args,
)
from banksia.interfaces.cli.providers import (
    ProviderConfigurationRequest,
    authentication_method_label,
    collect_provider_check,
    collect_provider_statuses,
    configure_provider,
    invoke_provider_identity_action,
    set_openclaw_gateway_auth_mode,
)
from banksia.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
    ProviderIdentityOutcome,
)
from banksia.interfaces.cli.providers.inspection import PROVIDER_ORDER
from banksia.interfaces.cli.providers.presentation import emit_provider_check
from banksia.interfaces.cli.support import (
    coerce_path,
    command_env,
    service_provider_check_env,
    service_provider_identity_env,
)
from banksia.providers import ProviderKind
from banksia.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
)

_PROVIDER_CHOICES = click.Choice(
    tuple(provider.value for provider in PROVIDER_ORDER),
    case_sensitive=False,
)


@dataclass(frozen=True, slots=True)
class GuidedProviderSetupResult:
    """Transient results from one guided provider-setup journey."""

    exit_code: int
    checks: Mapping[ProviderKind, ProviderCheckSnapshot]


def guide_provider_setup(
    args: argparse.Namespace,
    *,
    should_emit_summary: bool = True,
) -> int:
    """Guide Task-provider selection through the atomic provider operations."""

    return guide_provider_setup_with_result(
        args,
        should_emit_summary=should_emit_summary,
    ).exit_code


def guide_provider_setup_with_result(
    args: argparse.Namespace,
    *,
    should_emit_summary: bool = True,
) -> GuidedProviderSetupResult:
    """Run provider setup and return checks for this guided call only."""

    config_path = coerce_path(args.config)
    _require_initialized_config(config_path)
    settings = load_config_settings(config_path)
    emit_wizard_header(
        "Task provider setup",
        "Choose a route, verify it, and optionally add more providers.",
    )
    _emit_provider_state(config_path, settings)
    primary = _select_primary_provider(args, config_path, settings)
    if primary is None:
        emit_warning("Provider setup cancelled. No provider changes were made.")
        return GuidedProviderSetupResult(exit_code=0, checks={})

    check_results = {
        primary: guide_specific_provider(
            args,
            config_path=config_path,
            provider=primary,
        )
    }
    configured = persisted_provider_kinds(config_path)
    remaining = [provider for provider in PROVIDER_ORDER if provider not in configured]
    while remaining and click.confirm("Configure another provider?", default=False):
        extra = ProviderKind(
            click.prompt(
                "Additional provider",
                type=click.Choice(tuple(provider.value for provider in remaining)),
            )
        )
        extra_args = clone_namespace(
            args,
            provider=extra.value,
            model=None,
            effort=None,
            cli_path=None,
            gateway_url=None,
            gateway_profile=None,
            gateway_auth_mode=None,
        )
        check_results[extra] = guide_specific_provider(
            extra_args,
            config_path=config_path,
            provider=extra,
        )
        remaining.remove(extra)

    if should_emit_summary:
        _emit_setup_summary(config_path, check_results)
    exit_code = 0 if all(check.is_ready is True for check in check_results.values()) else 1
    return GuidedProviderSetupResult(
        exit_code=exit_code,
        checks=dict(check_results),
    )


def guide_specific_provider(
    args: argparse.Namespace,
    *,
    config_path: Path,
    provider: ProviderKind,
) -> ProviderCheckSnapshot:
    """Configure and diagnose one exact provider without opening another chooser."""

    settings = load_config_settings(config_path)
    request = _provider_request_for_selection(args, provider, settings)
    return _configure_and_check_provider(config_path, request)


def persisted_provider_kinds(config_path: Path) -> set[ProviderKind]:
    sections = read_config_sections(config_path)
    return {
        provider
        for provider in ProviderKind
        if sections.get(provider.value, {}).get("enabled") is True
    }


def persisted_default_provider(config_path: Path) -> ProviderKind | None:
    raw_default = read_config_sections(config_path).get("runtime", {}).get("default_provider")
    return ProviderKind(raw_default) if raw_default else None


def load_config_settings(config_path: Path) -> Settings:
    with command_env(config_path=config_path):
        return load_settings()


def clone_namespace(
    args: argparse.Namespace,
    **updates: object,
) -> argparse.Namespace:
    payload = vars(args).copy()
    payload.update(updates)
    return argparse.Namespace(**payload)


def collect_configured_provider_check(
    config_path: Path,
    provider: ProviderKind,
) -> ProviderCheckSnapshot:
    """Run the shared bounded diagnostic for one configured provider route."""

    with service_provider_check_env(config_path=config_path):
        return collect_provider_check(load_settings(), provider)


def provider_list_text(providers: set[ProviderKind]) -> str:
    """Render configured providers in the shared product order."""

    ordered = [provider.value for provider in PROVIDER_ORDER if provider in providers]
    return ", ".join(ordered) if ordered else "none"


def _require_initialized_config(config_path: Path) -> None:
    if not config_path.is_file():
        raise click.UsageError(
            f"Banksia is not initialized at {config_path}. Run 'banksia init' first."
        )


def _select_primary_provider(
    args: argparse.Namespace,
    config_path: Path,
    settings: Settings,
) -> ProviderKind | None:
    emit_provider_choices()
    if args.provider is not None:
        selected = ProviderKind(args.provider)
        click.echo(f"Provider to configure: {selected.value} (from --provider)")
        return selected

    configured = tuple(
        status.kind for status in collect_provider_statuses(settings) if status.is_configured
    )
    default_provider = (
        persisted_default_provider(config_path)
        or settings.runtime.default_provider
        or (configured[0] if configured else ProviderKind.CODEX)
    )
    selected = click.prompt(
        "Provider to configure",
        type=click.Choice((*_PROVIDER_CHOICES.choices, "cancel")),
        default=default_provider.value,
    )
    return None if selected == "cancel" else ProviderKind(selected)


def _configure_and_check_provider(
    config_path: Path,
    request: ProviderConfigurationRequest,
) -> ProviderCheckSnapshot:
    configure_provider(config_path, request)
    emit_success(f"Saved provider route: {request.provider.value}")
    if request.provider == ProviderKind.OPENCLAW:
        emit_warning(
            "OpenClaw is experimental; the Gateway process and compatibility MCP "
            "configuration remain user-managed."
        )
    preferred_method = None
    if request.gateway_auth_mode is not None:
        preferred_method = ProviderAuthenticationMethod(request.gateway_auth_mode.value)
    return _check_provider_with_identity(
        config_path,
        request.provider,
        preferred_method=preferred_method,
    )


def _check_provider_with_identity(
    config_path: Path,
    provider: ProviderKind,
    *,
    preferred_method: ProviderAuthenticationMethod | None,
) -> ProviderCheckSnapshot:
    emit_step(f"Checking {provider.value}")
    provider_check = collect_configured_provider_check(config_path, provider)
    emit_provider_check(provider_check, is_compact=True)
    can_configure_identity = provider_check.is_ready is True or (
        provider_check.outcome
        in {
            ProviderCheckOutcome.AUTHENTICATION_FAILED,
            ProviderCheckOutcome.LOCAL_PREREQUISITES_READY,
        }
    )
    if not can_configure_identity:
        return provider_check

    if _should_reuse_ready_credential(
        provider,
        provider_check,
        preferred_method=preferred_method,
    ):
        method = provider_check.authentication_method
        assert method is not None
        emit_success(f"Using existing {provider.value} {authentication_method_label(method)}")
        return provider_check

    method = preferred_method or prompt_authentication_method(
        provider,
        default_method=(
            provider_check.authentication_method or read_shell_authentication_method(provider)
        ),
    )
    secret = prompt_shell_secret_import(config_path, provider, method)
    if secret is None:
        secret = prompt_provider_secret(provider, method)
    with service_provider_identity_env():
        identity = invoke_provider_identity_action(
            provider,
            "login",
            is_json_output=False,
            config_path=config_path,
            authentication_method=method,
            secret=secret,
        )
    if identity.outcome != ProviderIdentityOutcome.SUCCEEDED:
        emit_warning(f"{provider_display_name(provider)} authentication: {identity.detail}")
        return provider_check.model_copy(
            update={
                "outcome": ProviderCheckOutcome.AUTHENTICATION_FAILED,
                "is_ready": False,
                "authentication": ProviderCheckAxisStatus.FAILED,
                "authentication_method": method,
                "detail": "selected_provider_authentication_failed",
            }
        )
    if provider is ProviderKind.OPENCLAW:
        set_openclaw_gateway_auth_mode(
            config_path,
            OpenClawGatewayAuthMode(method.value),
        )
    return _recheck_effective_authentication(config_path, provider, method)


def _should_reuse_ready_credential(
    provider: ProviderKind,
    provider_check: ProviderCheckSnapshot,
    *,
    preferred_method: ProviderAuthenticationMethod | None,
) -> bool:
    current_method = provider_check.authentication_method
    if (
        provider_check.is_ready is not True
        or current_method is None
        or (preferred_method is not None and preferred_method is not current_method)
    ):
        return False
    return click.confirm(
        existing_credential_prompt(provider, current_method),
        default=True,
    )


def _recheck_effective_authentication(
    config_path: Path,
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
) -> ProviderCheckSnapshot:
    label = authentication_method_label(method)
    emit_success(f"{provider_display_name(provider)} {label} completed")
    emit_step(f"Checking effective {provider.value} credential")
    provider_check = collect_configured_provider_check(config_path, provider)
    emit_provider_check(provider_check, is_compact=True)
    if provider_check.is_ready is True and provider_check.authentication_method is not method:
        effective_method = (
            authentication_method_label(provider_check.authentication_method)
            if provider_check.authentication_method is not None
            else "another credential"
        )
        emit_warning(
            f"{provider_display_name(provider)} {effective_method} remains effective; "
            f"the selected {label} did not take effect. An environment variable or "
            "native credential store may take precedence."
        )
        return provider_check.model_copy(
            update={
                "outcome": ProviderCheckOutcome.CHECK_FAILED,
                "is_ready": False,
                "detail": "selected_authentication_method_not_effective",
            }
        )
    if provider_check.is_ready is True:
        emit_success(f"{provider_display_name(provider)} {label} is ready")
    return provider_check


def _emit_provider_state(config_path: Path, settings: Settings) -> None:
    with service_provider_identity_env():
        statuses = collect_provider_statuses(settings)
    effective_providers = {status.kind for status in statuses if status.is_configured}
    persisted_providers = persisted_provider_kinds(config_path)
    rows = [
        ("Config", str(config_path)),
        ("Configured providers", provider_list_text(persisted_providers)),
    ]
    if effective_providers != persisted_providers:
        rows.append(
            (
                "Effective providers",
                f"{provider_list_text(effective_providers)} (environment overrides apply)",
            )
        )
    persisted_default = persisted_default_provider(config_path)
    effective_default = settings.runtime.default_provider
    rows.append(("Current default", _provider_text(persisted_default)))
    if effective_default != persisted_default:
        rows.append(
            (
                "Effective default",
                f"{_provider_text(effective_default)} (environment override)",
            )
        )
    emit_key_value_panel("Current configuration", rows)


def _emit_setup_summary(
    config_path: Path,
    checks: dict[ProviderKind, ProviderCheckSnapshot],
) -> None:
    settings = load_config_settings(config_path)
    with service_provider_identity_env():
        statuses = collect_provider_statuses(settings)
    effective_providers = {status.kind for status in statuses if status.is_configured}
    configured = persisted_provider_kinds(config_path)
    default = persisted_default_provider(config_path)
    effective_default = settings.runtime.default_provider
    rows = [
        ("Default provider", _provider_text(default)),
        ("Configured providers", provider_list_text(configured)),
    ]
    if effective_providers != configured:
        rows.append(("Effective providers", provider_list_text(effective_providers)))
    if effective_default != default:
        rows.append(
            (
                "Effective environment-overridden default",
                _provider_text(effective_default),
            )
        )
    for provider, provider_check in checks.items():
        state = "ready" if provider_check.is_ready is True else provider_check.outcome.value
        rows.append((provider.value, state))
    first_nonready = next(
        (
            provider
            for provider, provider_check in checks.items()
            if provider_check.is_ready is not True
        ),
        None,
    )
    next_action = (
        f"banksia providers check {first_nonready.value}"
        if first_nonready is not None
        else "banksia serve"
    )
    if first_nonready is not None:
        emit_warning("Provider setup is saved, but at least one selected route needs attention.")
    emit_completion("Provider setup summary", rows, next_action=next_action)


def _provider_request_for_selection(
    args: argparse.Namespace,
    provider: ProviderKind,
    settings: Settings,
) -> ProviderConfigurationRequest:
    selected_args = clone_namespace(args, provider=provider.value)
    if provider is ProviderKind.OPENCLAW:
        selected_args.gateway_url = click.prompt(
            "Gateway URL",
            default=(getattr(args, "gateway_url", None) or settings.openclaw.gateway_url),
        )
        selected_args.gateway_profile = click.prompt(
            "Gateway profile",
            default=(getattr(args, "gateway_profile", None) or settings.openclaw.gateway_profile),
        )
        selected_args.gateway_auth_mode = click.prompt(
            "Gateway authentication",
            type=click.Choice(("token", "password")),
            default=(
                getattr(args, "gateway_auth_mode", None)
                or settings.openclaw.gateway_auth_mode.value
            ),
        )
    return provider_configuration_request_from_args(selected_args)


def _provider_text(provider: ProviderKind | None) -> str:
    return provider.value if provider is not None else "none"


__all__ = [
    "GuidedProviderSetupResult",
    "clone_namespace",
    "collect_configured_provider_check",
    "guide_provider_setup",
    "guide_provider_setup_with_result",
    "guide_specific_provider",
    "load_config_settings",
    "persisted_default_provider",
    "persisted_provider_kinds",
    "provider_list_text",
]
