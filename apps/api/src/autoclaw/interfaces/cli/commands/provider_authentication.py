from __future__ import annotations

import os
from pathlib import Path

import click

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.interfaces.cli.commands.guided_presentation import emit_step
from autoclaw.interfaces.cli.providers import (
    authentication_method_choices,
    authentication_method_label,
    provider_secret_environment_key,
)
from autoclaw.platform.provider_environment import (
    provider_environment_file_path,
    read_provider_secret_environment,
)
from autoclaw.runtime.providers import ProviderAuthenticationMethod


def prompt_authentication_method(
    provider: ProviderKind,
    *,
    default_method: ProviderAuthenticationMethod | None,
) -> ProviderAuthenticationMethod:
    """Ask for one supported provider authentication method."""

    supported_methods = authentication_method_choices(provider)
    choices = tuple(method.value.replace("_", "-") for method in supported_methods)
    default = choices[0]
    if default_method is not None and default_method in supported_methods:
        default = default_method.value.replace("_", "-")
    selected = click.prompt(
        f"{provider_display_name(provider)} authentication",
        type=click.Choice(choices),
        default=default,
    )
    return ProviderAuthenticationMethod(selected.replace("-", "_"))


def prompt_provider_secret(
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
) -> str | None:
    """Collect one hidden secret or prepare a provider-native subscription login."""

    if method is ProviderAuthenticationMethod.SUBSCRIPTION:
        emit_step("A browser or device sign-in may open in the provider's native CLI")
        return None
    if method is ProviderAuthenticationMethod.API_KEY:
        label = "OpenAI API key" if provider is ProviderKind.CODEX else "Anthropic API key"
    else:
        label = authentication_method_label(method)
    return str(click.prompt(label, hide_input=True))


def prompt_shell_secret_import(
    config_path: Path,
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
) -> str | None:
    """Offer to copy a shell-only secret into the managed service environment."""

    key = provider_secret_environment_key(provider, method)
    if key is None:
        return None
    shell_secret = os.environ.get(key)
    if not shell_secret:
        return None
    stored_secret = read_provider_secret_environment(
        provider_environment_file_path(config_path)
    ).get(key)
    if stored_secret == shell_secret:
        return None
    if click.confirm(
        f"Existing {provider_display_name(provider)} {authentication_method_label(method)} "
        "found in this shell. Store it for the AutoClaw service?",
        default=True,
    ):
        return shell_secret
    return None


def existing_credential_prompt(
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
) -> str:
    """Describe reuse without implying that a shell-only secret is service-ready."""

    label = authentication_method_label(method)
    if provider_secret_environment_key(provider, method) is not None:
        return (
            f"Existing {provider_display_name(provider)} {label} stored for the AutoClaw "
            "service. Use it?"
        )
    return f"Existing {provider_display_name(provider)} {label} found. Use it?"


def read_shell_authentication_method(
    provider: ProviderKind,
) -> ProviderAuthenticationMethod | None:
    """Return the first supported managed-secret method exported by this shell."""

    for method in authentication_method_choices(provider):
        key = provider_secret_environment_key(provider, method)
        if key is not None and os.environ.get(key):
            return method
    return None


def provider_display_name(provider: ProviderKind) -> str:
    """Return the stable human product spelling for a provider."""

    return "OpenClaw" if provider is ProviderKind.OPENCLAW else provider.value.title()


__all__ = [
    "existing_credential_prompt",
    "prompt_authentication_method",
    "prompt_provider_secret",
    "prompt_shell_secret_import",
    "provider_display_name",
    "read_shell_authentication_method",
]
