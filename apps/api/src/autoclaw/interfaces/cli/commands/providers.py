from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import click

from autoclaw.config import OpenClawGatewayAuthMode, Settings, load_settings
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.interfaces.cli.bootstrap.config import read_config_sections
from autoclaw.interfaces.cli.providers import (
    ProviderConfigurationRequest,
    authentication_method_choices,
    authentication_method_label,
    collect_provider_check,
    collect_provider_definitions,
    collect_provider_statuses,
    configure_provider,
    invoke_provider_identity_action,
    set_default_provider,
    set_openclaw_gateway_auth_mode,
)
from autoclaw.interfaces.cli.providers.contracts import (
    ProviderConfigurationSnapshot,
    ProviderIdentityOutcome,
)
from autoclaw.interfaces.cli.providers.inspection import providers_payload
from autoclaw.interfaces.cli.providers.presentation import (
    emit_provider_check,
    emit_provider_definitions,
    emit_provider_identity,
    emit_provider_status,
)
from autoclaw.interfaces.cli.providers.presentation import (
    emit_provider_configuration as emit_provider_configuration_view,
)
from autoclaw.interfaces.cli.support import (
    coerce_path,
    command_env,
    print_json,
    service_provider_check_env,
    service_provider_identity_env,
)
from autoclaw.runtime.providers import ProviderAuthenticationMethod


def cmd_providers_list(args: argparse.Namespace) -> int:
    definitions = collect_provider_definitions()
    payload = {"ok": True, "providers": providers_payload(definitions)}
    if args.json:
        print_json(payload)
    else:
        emit_provider_definitions(definitions)
    return 0


def cmd_providers_status(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path):
        settings = load_settings()
    provider = ProviderKind(args.provider) if args.provider is not None else None
    with service_provider_identity_env():
        statuses = collect_provider_statuses(settings, provider)
    payload = {
        "ok": True,
        "config_path": str(config_path),
        "providers": providers_payload(statuses),
    }
    if args.json:
        print_json(payload)
    else:
        emit_provider_status(statuses)
    return 0


def cmd_providers_check(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    provider = ProviderKind(args.provider)
    with service_provider_check_env(config_path=config_path):
        settings = load_settings()
        snapshot = collect_provider_check(settings, provider)
    payload = {"ok": snapshot.is_ready is True, **snapshot.model_dump(mode="json")}
    if args.json:
        print_json(payload)
    else:
        emit_provider_check(snapshot)
    return 0 if snapshot.is_ready is True else 1


def cmd_providers_configure(args: argparse.Namespace) -> int:
    request = provider_configuration_request_from_args(args)
    snapshot = configure_provider(coerce_path(args.config), request)
    emit_provider_configuration(snapshot, is_json_output=args.json)
    return 0


def cmd_providers_set_default(args: argparse.Namespace) -> int:
    snapshot = set_default_provider(
        coerce_path(args.config),
        ProviderKind(args.provider),
    )
    emit_provider_configuration(snapshot, is_json_output=args.json)
    return 0


def cmd_providers_identity(args: argparse.Namespace, action: str) -> int:
    provider = ProviderKind(args.provider)
    config_path = coerce_path(args.config)
    if action == "login" and provider is ProviderKind.OPENCLAW:
        _require_configured_openclaw_route(config_path)
    can_prompt = not args.json and sys.stdin.isatty() and sys.stdout.isatty()
    authentication_method = (
        _resolve_identity_method(
            provider,
            getattr(args, "method", None),
            can_prompt=can_prompt,
        )
        if action == "login"
        else None
    )
    secret = (
        _read_identity_secret(
            authentication_method,
            should_read_stdin=getattr(args, "secret_stdin", False),
            can_prompt=can_prompt,
        )
        if action == "login"
        else None
    )
    with service_provider_identity_env():
        snapshot = invoke_provider_identity_action(
            provider,
            action,
            is_json_output=args.json,
            config_path=config_path,
            authentication_method=authentication_method,
            secret=secret,
        )
    if (
        action == "login"
        and provider is ProviderKind.OPENCLAW
        and authentication_method is not None
        and snapshot.outcome == ProviderIdentityOutcome.SUCCEEDED
    ):
        set_openclaw_gateway_auth_mode(
            config_path,
            OpenClawGatewayAuthMode(authentication_method.value),
        )
    payload = {
        "ok": snapshot.outcome == ProviderIdentityOutcome.SUCCEEDED,
        **snapshot.model_dump(mode="json"),
    }
    if args.json:
        print_json(payload)
    else:
        emit_provider_identity(snapshot)
    return 0 if snapshot.outcome == ProviderIdentityOutcome.SUCCEEDED else 1


def cmd_setup(args: argparse.Namespace) -> int:
    if args.provider is None:
        config_path = coerce_path(args.config)
        with command_env(config_path=config_path):
            settings = load_settings()
        guide_payload = build_setup_guide(config_path, settings)
        if args.json:
            print_json(guide_payload)
        else:
            emit_setup_guide(guide_payload)
        return 0

    request = provider_configuration_request_from_args(args)
    config_path = coerce_path(args.config)
    snapshot = configure_provider(config_path, request)
    with service_provider_check_env(config_path=config_path):
        check = collect_provider_check(load_settings(), request.provider)
    setup_payload: dict[str, Any] = {
        "ok": check.is_ready is True,
        "configured_provider": snapshot.provider.value,
        "configuration": snapshot.model_dump(mode="json"),
        "check": check.model_dump(mode="json"),
        "next_actions": (
            ["autoclaw providers status", "autoclaw serve"]
            if check.is_ready is True
            else [
                f"autoclaw providers login {request.provider.value}",
                f"autoclaw providers check {request.provider.value}",
            ]
        ),
    }
    if args.json:
        print_json(setup_payload)
    else:
        print(f"Saved provider route: {snapshot.provider.value}")
        print(f"Default provider: {snapshot.default_provider.value}")
        emit_provider_check(check)
    return 0 if check.is_ready is True else 1


def build_setup_guide(config_path: Path, settings: Settings) -> dict[str, Any]:
    statuses = collect_provider_statuses(settings)
    configured = tuple(status.kind for status in statuses if status.is_configured)
    persisted_sections = read_config_sections(config_path)
    persisted = tuple(
        provider
        for provider in ProviderKind
        if persisted_sections.get(provider.value, {}).get("enabled") is True
    )
    default_provider = settings.runtime.default_provider
    is_default_configured = default_provider in configured

    if not configured:
        next_actions = []
        if not config_path.exists():
            next_actions.append("autoclaw init")
        next_actions.append("autoclaw providers configure <provider>")
    elif not is_default_configured:
        persisted_candidates = tuple(provider for provider in configured if provider in persisted)
        if persisted_candidates:
            provider = (
                persisted_candidates[0].value if len(persisted_candidates) == 1 else "<provider>"
            )
            next_actions = [f"autoclaw providers set-default {provider}"]
        else:
            provider = configured[0].value if len(configured) == 1 else "<provider>"
            next_actions = [f"autoclaw providers configure {provider}"]
    else:
        assert default_provider is not None
        next_actions = [
            f"autoclaw providers check {default_provider.value}",
            "autoclaw serve",
        ]

    return {
        "ok": True,
        "configured_provider": configured[0].value if len(configured) == 1 else None,
        "configured_providers": [provider.value for provider in configured],
        "default_provider": (default_provider.value if default_provider is not None else None),
        "default_provider_configured": is_default_configured,
        "next_actions": next_actions,
    }


def emit_setup_guide(payload: dict[str, Any]) -> None:
    configured = payload["configured_providers"]
    default_provider = payload["default_provider"]
    is_default_configured = payload["default_provider_configured"]

    print(
        f"Configured providers: {', '.join(configured)}"
        if configured
        else "Configured providers: none"
    )
    if default_provider is None:
        print("Default provider: not configured")
    elif is_default_configured:
        print(f"Default provider: {default_provider}")
    else:
        print(f"Default provider: {default_provider} (not enabled)")
    for action in payload["next_actions"]:
        print(f"Next: {action}")


def provider_configuration_request_from_args(
    args: argparse.Namespace,
) -> ProviderConfigurationRequest:
    return ProviderConfigurationRequest(
        provider=ProviderKind(args.provider),
        model=getattr(args, "model", None),
        effort=getattr(args, "effort", None),
        cli_path=getattr(args, "cli_path", None),
        gateway_url=getattr(args, "gateway_url", None),
        gateway_profile=getattr(args, "gateway_profile", None),
        gateway_auth_mode=getattr(args, "gateway_auth_mode", None),
    )


def emit_provider_configuration(
    snapshot: ProviderConfigurationSnapshot,
    *,
    is_json_output: bool,
) -> None:
    payload: dict[str, Any] = {"ok": True, **snapshot.model_dump(mode="json")}
    if is_json_output:
        print_json(payload)
        return
    emit_provider_configuration_view(snapshot)


def _resolve_identity_method(
    provider: ProviderKind,
    raw_method: str | None,
    *,
    can_prompt: bool,
) -> ProviderAuthenticationMethod:
    choices = tuple(
        method.value.replace("_", "-") for method in authentication_method_choices(provider)
    )
    selected = raw_method
    if selected is None and can_prompt:
        selected = click.prompt(
            "Authentication method",
            type=click.Choice(choices),
            default=choices[0],
        )
    if selected is None:
        raise click.UsageError(f"--method is required when {provider.value} login cannot prompt")
    method = ProviderAuthenticationMethod(selected.replace("-", "_"))
    if method not in authentication_method_choices(provider):
        supported = " or ".join(choices)
        raise click.ClickException(
            f"{provider.value.title()} authentication uses {supported}, not {selected}"
        )
    return method


def _read_identity_secret(
    method: ProviderAuthenticationMethod | None,
    *,
    should_read_stdin: bool,
    can_prompt: bool,
) -> str | None:
    if method is ProviderAuthenticationMethod.SUBSCRIPTION or method is None:
        if method is ProviderAuthenticationMethod.SUBSCRIPTION and not can_prompt:
            raise click.UsageError("subscription login requires an interactive terminal")
        return None
    if should_read_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    if can_prompt:
        return str(click.prompt(authentication_method_label(method), hide_input=True))
    raise click.UsageError("--secret-stdin is required when login cannot prompt for a secret")


def _require_configured_openclaw_route(config_path: Path) -> None:
    openclaw_section = read_config_sections(config_path).get(ProviderKind.OPENCLAW.value, {})
    if openclaw_section.get("enabled") is not True:
        raise click.ClickException(
            "Configure the OpenClaw Gateway route before saving its credential: "
            "autoclaw providers configure openclaw"
        )


__all__ = [
    "build_setup_guide",
    "cmd_providers_check",
    "cmd_providers_configure",
    "cmd_providers_identity",
    "cmd_providers_list",
    "cmd_providers_set_default",
    "cmd_providers_status",
    "cmd_setup",
    "emit_provider_configuration",
    "emit_setup_guide",
    "provider_configuration_request_from_args",
]
