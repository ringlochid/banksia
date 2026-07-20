from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from autoclaw.config import (
    DEFAULT_LOG_LEVEL,
    OpenClawGatewayAuthMode,
    Settings,
    format_loopback_authority,
    load_settings,
)
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.interfaces.cli.bootstrap.config import read_config_sections
from autoclaw.interfaces.cli.commands.bootstrap import cmd_init, ensure_database_ready
from autoclaw.interfaces.cli.commands.config_view import redact_database_url
from autoclaw.interfaces.cli.commands.guided_presentation import (
    emit_completion,
    emit_key_value_panel,
    emit_provider_choices,
    emit_step,
    emit_success,
    emit_warning,
    emit_wizard_header,
)
from autoclaw.interfaces.cli.commands.provider_authentication import (
    existing_credential_prompt,
    prompt_authentication_method,
    prompt_provider_secret,
    prompt_shell_secret_import,
    provider_display_name,
    read_shell_authentication_method,
)
from autoclaw.interfaces.cli.commands.providers import (
    provider_configuration_request_from_args,
)
from autoclaw.interfaces.cli.progress import CliProgress
from autoclaw.interfaces.cli.providers import (
    ProviderConfigurationRequest,
    authentication_method_label,
    collect_provider_check,
    collect_provider_statuses,
    configure_provider,
    invoke_provider_identity_action,
    set_default_provider,
    set_openclaw_gateway_auth_mode,
)
from autoclaw.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
    ProviderIdentityOutcome,
)
from autoclaw.interfaces.cli.providers.inspection import PROVIDER_ORDER
from autoclaw.interfaces.cli.providers.presentation import emit_provider_check
from autoclaw.interfaces.cli.support import (
    coerce_path,
    command_env,
    service_provider_check_env,
    service_provider_identity_env,
)
from autoclaw.paths import default_data_dir, default_database_url
from autoclaw.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
)

_INIT_ACTIONS = click.Choice(("keep", "replace", "cancel"), case_sensitive=False)
_PROVIDER_CHOICES = click.Choice(
    tuple(provider.value for provider in PROVIDER_ORDER),
    case_sensitive=False,
)
_LOG_LEVELS = click.Choice(
    ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    case_sensitive=False,
)
_LOOPBACK_HOSTS = click.Choice(("127.0.0.1", "localhost", "::1"), case_sensitive=False)


@dataclass(frozen=True, slots=True)
class _LocalInitSelection:
    args: argparse.Namespace
    is_recommended_accepted: bool


def should_run_guided_flow(*, is_non_interactive: bool, is_json_output: bool) -> bool:
    """Return whether this invocation can safely prompt a human."""

    if is_non_interactive or is_json_output:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


async def guide_local_initialization(args: argparse.Namespace) -> int:
    """Guide local initialization while keeping database reset explicit."""

    config_path = coerce_path(args.config)
    should_confirm_replacement = False
    emit_wizard_header(
        "initialization",
        "Create or verify the local controller configuration and database.",
    )

    if config_path.is_file() and not args.force:
        action = _prompt_existing_init_action(config_path)
        if action == "cancel":
            return _emit_cancelled()
        if action == "keep":
            await _verify_existing_local_state(args, config_path)
            emit_completion(
                "Initialization complete",
                (("Config", str(config_path)), ("Database", "verified")),
                next_action="autoclaw setup",
            )
            return 0
        args = _clone_namespace(args, force=True)
        should_confirm_replacement = True
    elif config_path.is_file():
        emit_warning(f"Existing config will be replaced: {config_path}")

    selection = _prompt_local_init_settings(args)
    if should_confirm_replacement or not selection.is_recommended_accepted:
        prompt = (
            "Replace the existing local config with these settings?"
            if should_confirm_replacement
            else "Initialize AutoClaw with these custom settings?"
        )
        if not click.confirm(prompt, default=not should_confirm_replacement):
            return _emit_cancelled()

    result = await cmd_init(selection.args)
    if result == 0:
        emit_completion(
            "Initialization complete",
            (("Config", str(config_path)), ("Database", "ready")),
            next_action="autoclaw setup",
        )
    return result


def guide_provider_setup(args: argparse.Namespace) -> int:
    """Guide provider selection through the existing atomic CLI operations."""

    config_path = coerce_path(args.config)
    if not config_path.is_file():
        raise click.UsageError(
            f"AutoClaw is not initialized at {config_path}. Run 'autoclaw init' first."
        )

    settings = _load_config_settings(config_path)
    emit_wizard_header(
        "provider setup",
        "Choose a primary route, verify it, and optionally add more providers.",
    )
    _emit_provider_state(config_path, settings)
    primary = _select_primary_provider(args, config_path, settings)
    if primary is None:
        return _emit_cancelled()

    check_results: dict[ProviderKind, ProviderCheckSnapshot] = {}
    primary_request = _provider_request_for_selection(args, primary, settings)
    check_results[primary] = _configure_and_check_provider(
        config_path,
        primary_request,
        make_default=True,
    )

    configured = _persisted_provider_kinds(config_path)
    remaining = [provider for provider in PROVIDER_ORDER if provider not in configured]
    while remaining and click.confirm("Configure another provider?", default=False):
        extra = ProviderKind(
            click.prompt(
                "Additional provider",
                type=click.Choice(tuple(provider.value for provider in remaining)),
            )
        )
        settings = _load_config_settings(config_path)
        check_results[extra] = _configure_and_check_provider(
            config_path,
            _provider_request_for_selection(
                _clone_namespace(
                    args,
                    provider=extra.value,
                    model=None,
                    effort=None,
                    cli_path=None,
                    gateway_url=None,
                    gateway_profile=None,
                    gateway_auth_mode=None,
                ),
                extra,
                settings,
            ),
            make_default=False,
        )
        remaining.remove(extra)

    _emit_setup_summary(config_path, check_results)
    return 0 if all(check.is_ready is True for check in check_results.values()) else 1


def _prompt_existing_init_action(config_path: Path) -> str:
    click.echo(f"Existing config found: {config_path}")
    click.echo("  keep    Keep and verify current config (recommended)")
    click.echo("  replace Replace local config after confirmation")
    click.echo("  cancel  Leave everything unchanged")
    return str(click.prompt("Action", type=_INIT_ACTIONS, default="keep")).casefold()


def _prompt_local_init_settings(args: argparse.Namespace) -> _LocalInitSelection:
    prepared = _clone_namespace(args)
    data_dir = coerce_path(prepared.data_dir or default_data_dir())
    database_url = prepared.database_url or default_database_url(data_dir)
    prepared.data_dir = str(data_dir)
    prepared.database_url = database_url
    _emit_local_init_summary(prepared)
    if click.confirm("Use these recommended local settings?", default=True):
        return _LocalInitSelection(args=prepared, is_recommended_accepted=True)

    data_dir = click.prompt(
        "Data directory",
        default=str(data_dir),
        type=click.Path(path_type=Path, file_okay=False, resolve_path=True),
    )
    prepared.data_dir = str(data_dir)
    if args.database_url is None:
        prepared.database_url = click.prompt(
            "Database URL",
            default=default_database_url(data_dir),
        )
    prepared.host = click.prompt(
        "Loopback API host",
        default=prepared.host,
        type=_LOOPBACK_HOSTS,
    )
    prepared.port = click.prompt(
        "API port",
        default=prepared.port,
        type=click.IntRange(1, 65535),
    )
    prepared.log_level = click.prompt(
        "Log level",
        default=prepared.log_level or DEFAULT_LOG_LEVEL,
        type=_LOG_LEVELS,
    )
    _emit_local_init_summary(prepared)
    return _LocalInitSelection(args=prepared, is_recommended_accepted=False)


def _emit_local_init_summary(args: argparse.Namespace) -> None:
    database_url = args.database_url or default_database_url(
        coerce_path(args.data_dir or default_data_dir())
    )
    emit_key_value_panel(
        "Local settings",
        (
            ("Config", str(coerce_path(args.config))),
            ("Data", str(coerce_path(args.data_dir or default_data_dir()))),
            ("Database", redact_database_url(database_url)),
            ("API", f"http://{format_loopback_authority(args.host, args.port)}"),
        ),
    )


async def _verify_existing_local_state(args: argparse.Namespace, config_path: Path) -> None:
    progress = CliProgress.from_args(args)
    with command_env(config_path=config_path):
        settings = load_settings()
        if not args.skip_db_upgrade:
            await ensure_database_ready(progress=progress)
    emit_success(f"Verified config at {config_path}")
    emit_success(f"Data directory ready at {settings.data_dir}")


def _select_primary_provider(
    args: argparse.Namespace,
    config_path: Path,
    settings: Settings,
) -> ProviderKind | None:
    emit_provider_choices()
    if args.provider is not None:
        selected = ProviderKind(args.provider)
        click.echo(f"Primary/default provider: {selected.value} (from --provider)")
        return selected

    configured = tuple(
        status.kind for status in collect_provider_statuses(settings) if status.is_configured
    )
    default_provider = (
        _persisted_default_provider(config_path)
        or settings.runtime.default_provider
        or (configured[0] if configured else ProviderKind.CODEX)
    )
    selected = click.prompt(
        "Primary/default provider",
        type=click.Choice((*_PROVIDER_CHOICES.choices, "cancel")),
        default=default_provider.value,
    )
    return None if selected == "cancel" else ProviderKind(selected)


def _configure_and_check_provider(
    config_path: Path,
    request: ProviderConfigurationRequest,
    *,
    make_default: bool,
) -> ProviderCheckSnapshot:
    snapshot = configure_provider(config_path, request)
    if make_default and snapshot.default_provider != request.provider:
        set_default_provider(config_path, request.provider)
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
    check = _collect_provider_check(config_path, provider)
    emit_provider_check(check, is_compact=True)
    can_configure_identity = check.is_ready is True or check.outcome in {
        ProviderCheckOutcome.AUTHENTICATION_FAILED,
        ProviderCheckOutcome.LOCAL_PREREQUISITES_READY,
    }
    if not can_configure_identity:
        return check

    method = preferred_method or prompt_authentication_method(
        provider,
        default_method=(check.authentication_method or read_shell_authentication_method(provider)),
    )
    if check.is_ready is True and check.authentication_method is method:
        should_reuse = click.confirm(
            existing_credential_prompt(provider, method),
            default=True,
        )
        if should_reuse:
            emit_success(f"Using existing {provider.value} {authentication_method_label(method)}")
            return check

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
        return check.model_copy(
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


def _recheck_effective_authentication(
    config_path: Path,
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
) -> ProviderCheckSnapshot:
    label = authentication_method_label(method)
    emit_success(f"{provider_display_name(provider)} {label} completed")
    emit_step(f"Checking effective {provider.value} credential")
    check = _collect_provider_check(config_path, provider)
    emit_provider_check(check, is_compact=True)
    if check.is_ready is True and check.authentication_method is not method:
        effective_method = (
            authentication_method_label(check.authentication_method)
            if check.authentication_method is not None
            else "another credential"
        )
        emit_warning(
            f"{provider_display_name(provider)} {effective_method} remains effective; "
            "the selected "
            f"{label} did not take effect. An environment variable or native credential "
            "store may take precedence."
        )
        return check.model_copy(
            update={
                "outcome": ProviderCheckOutcome.CHECK_FAILED,
                "is_ready": False,
                "detail": "selected_authentication_method_not_effective",
            }
        )
    if check.is_ready is True:
        emit_success(f"{provider_display_name(provider)} {label} is ready")
    return check


def _emit_provider_state(config_path: Path, settings: Settings) -> None:
    with service_provider_identity_env():
        statuses = collect_provider_statuses(settings)
    effective_providers = {status.kind for status in statuses if status.is_configured}
    persisted_providers = _persisted_provider_kinds(config_path)
    rows = [
        ("Config", str(config_path)),
        ("Configured providers", _provider_list_text(persisted_providers)),
    ]
    if effective_providers != persisted_providers:
        rows.append(
            (
                "Effective providers",
                f"{_provider_list_text(effective_providers)} (environment overrides apply)",
            )
        )
    persisted_default = _persisted_default_provider(config_path)
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
    settings = _load_config_settings(config_path)
    with service_provider_identity_env():
        statuses = collect_provider_statuses(settings)
    effective_providers = {status.kind for status in statuses if status.is_configured}
    configured = _persisted_provider_kinds(config_path)
    default = _persisted_default_provider(config_path)
    effective_default = settings.runtime.default_provider
    rows = [
        ("Default provider", _provider_text(default)),
        ("Configured providers", _provider_list_text(configured)),
    ]
    if effective_providers != configured:
        rows.append(("Effective providers", _provider_list_text(effective_providers)))
    if effective_default != default:
        rows.append(
            (
                "Effective environment-overridden default",
                _provider_text(effective_default),
            )
        )
    for provider, check in checks.items():
        state = "ready" if check.is_ready is True else check.outcome.value
        rows.append((provider.value, state))
    first_nonready = next(
        (provider for provider, check in checks.items() if check.is_ready is not True),
        None,
    )
    next_action = (
        f"autoclaw providers check {first_nonready.value}"
        if first_nonready is not None
        else "autoclaw serve"
    )
    if first_nonready is not None:
        emit_warning("Provider setup is saved, but at least one selected route is not ready.")
    emit_completion("Provider setup summary", rows, next_action=next_action)


def _provider_request_for_selection(
    args: argparse.Namespace,
    provider: ProviderKind,
    settings: Settings,
) -> ProviderConfigurationRequest:
    selected_args = _clone_namespace(args, provider=provider.value)
    if provider is ProviderKind.OPENCLAW:
        selected_args.gateway_url = click.prompt(
            "Gateway URL",
            default=getattr(args, "gateway_url", None) or settings.openclaw.gateway_url,
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


def _collect_provider_check(
    config_path: Path,
    provider: ProviderKind,
) -> ProviderCheckSnapshot:
    with service_provider_check_env(config_path=config_path):
        return collect_provider_check(load_settings(), provider)


def _persisted_provider_kinds(config_path: Path) -> set[ProviderKind]:
    sections = read_config_sections(config_path)
    return {
        provider
        for provider in ProviderKind
        if sections.get(provider.value, {}).get("enabled") is True
    }


def _persisted_default_provider(config_path: Path) -> ProviderKind | None:
    raw_default = read_config_sections(config_path).get("runtime", {}).get("default_provider")
    return ProviderKind(raw_default) if raw_default else None


def _provider_list_text(providers: set[ProviderKind]) -> str:
    ordered = [provider.value for provider in PROVIDER_ORDER if provider in providers]
    return ", ".join(ordered) if ordered else "none"


def _provider_text(provider: ProviderKind | None) -> str:
    return provider.value if provider is not None else "none"


def _load_config_settings(config_path: Path) -> Settings:
    with command_env(config_path=config_path):
        return load_settings()


def _clone_namespace(args: argparse.Namespace, **updates: object) -> argparse.Namespace:
    payload = vars(args).copy()
    payload.update(updates)
    return argparse.Namespace(**payload)


def _emit_cancelled() -> int:
    emit_warning("Cancelled. No further changes were made.")
    return 0


__all__ = [
    "guide_local_initialization",
    "guide_provider_setup",
    "should_run_guided_flow",
]
