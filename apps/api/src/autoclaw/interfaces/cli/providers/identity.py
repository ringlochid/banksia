from __future__ import annotations

import getpass
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.integrations.claude.native_identity import bundled_claude_path
from autoclaw.interfaces.cli.providers.contracts import (
    ProviderIdentityOutcome,
    ProviderIdentitySnapshot,
)
from autoclaw.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    OPENCLAW_GATEWAY_PASSWORD,
    OPENCLAW_GATEWAY_TOKEN,
    persist_provider_secret,
    provider_environment_file_path,
    provider_subprocess_environment,
    read_provider_secret_environment,
    remove_provider_secrets,
)
from autoclaw.runtime.providers import ProviderAuthenticationMethod

NativeCommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def invoke_provider_identity_action(
    provider: ProviderKind,
    action: str,
    *,
    is_json_output: bool,
    config_path: Path | None = None,
    authentication_method: ProviderAuthenticationMethod | None = None,
    secret: str | None = None,
    command_runner: NativeCommandRunner | None = None,
) -> ProviderIdentitySnapshot:
    normalized_action = _identity_action(action)
    identity = service_identity()
    native_home = str(provider_native_home(provider))
    method = authentication_method or _default_authentication_method(provider)
    if normalized_action == "logout":
        return _logout_provider_identity(
            provider=provider,
            identity=identity,
            native_home=native_home,
            config_path=config_path,
            is_json_output=is_json_output,
            command_runner=command_runner,
        )
    if not _provider_supports_authentication_method(provider, method):
        return ProviderIdentitySnapshot(
            provider=provider,
            action=normalized_action,
            outcome=ProviderIdentityOutcome.FAILED,
            service_identity=identity,
            native_home=native_home,
            authentication_method=method,
            detail=f"{provider.value} does not support {authentication_method_label(method)}",
        )
    if method is not ProviderAuthenticationMethod.SUBSCRIPTION and not secret:
        return ProviderIdentitySnapshot(
            provider=provider,
            action=normalized_action,
            outcome=ProviderIdentityOutcome.FAILED,
            service_identity=identity,
            native_home=native_home,
            authentication_method=method,
            detail=f"{authentication_method_label(method)} is required",
        )

    if provider is ProviderKind.CLAUDE and method is ProviderAuthenticationMethod.API_KEY:
        return _save_claude_api_key(
            config_path=config_path,
            secret=secret,
            identity=identity,
            native_home=native_home,
        )
    if provider is ProviderKind.OPENCLAW:
        return _save_openclaw_credential(
            config_path=config_path,
            method=method,
            secret=secret,
            identity=identity,
            native_home=native_home,
        )
    return _run_native_login(
        provider=provider,
        method=method,
        identity=identity,
        native_home=native_home,
        config_path=config_path,
        secret=secret,
        is_json_output=is_json_output,
        command_runner=command_runner,
    )


def authentication_method_choices(
    provider: ProviderKind,
) -> tuple[ProviderAuthenticationMethod, ...]:
    if provider in {ProviderKind.CODEX, ProviderKind.CLAUDE}:
        return (
            ProviderAuthenticationMethod.SUBSCRIPTION,
            ProviderAuthenticationMethod.API_KEY,
        )
    return (
        ProviderAuthenticationMethod.TOKEN,
        ProviderAuthenticationMethod.PASSWORD,
    )


def authentication_method_label(method: ProviderAuthenticationMethod) -> str:
    return {
        ProviderAuthenticationMethod.SUBSCRIPTION: "subscription login",
        ProviderAuthenticationMethod.API_KEY: "API key",
        ProviderAuthenticationMethod.TOKEN: "Gateway token",
        ProviderAuthenticationMethod.PASSWORD: "Gateway password",
    }[method]


def provider_secret_environment_key(
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
) -> str | None:
    """Return the private service variable used by one managed secret method."""

    if provider is ProviderKind.CLAUDE and method is ProviderAuthenticationMethod.API_KEY:
        return ANTHROPIC_API_KEY
    if provider is ProviderKind.OPENCLAW:
        if method is ProviderAuthenticationMethod.TOKEN:
            return OPENCLAW_GATEWAY_TOKEN
        if method is ProviderAuthenticationMethod.PASSWORD:
            return OPENCLAW_GATEWAY_PASSWORD
    return None


def service_identity() -> str:
    try:
        import pwd

        return pwd.getpwuid(os.geteuid()).pw_name
    except (AttributeError, ImportError, KeyError):
        return getpass.getuser()


def provider_native_home(provider: ProviderKind) -> Path:
    user_home = Path.home()
    match provider:
        case ProviderKind.CODEX:
            return Path(os.environ.get("CODEX_HOME", user_home / ".codex")).expanduser()
        case ProviderKind.CLAUDE:
            return Path(os.environ.get("CLAUDE_CONFIG_DIR", user_home / ".claude")).expanduser()
        case ProviderKind.OPENCLAW:
            return Path(os.environ.get("OPENCLAW_STATE_DIR", user_home / ".openclaw")).expanduser()


def _default_authentication_method(provider: ProviderKind) -> ProviderAuthenticationMethod:
    return authentication_method_choices(provider)[0]


def _provider_supports_authentication_method(
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
) -> bool:
    return method in authentication_method_choices(provider)


def _save_claude_api_key(
    *,
    config_path: Path | None,
    secret: str | None,
    identity: str,
    native_home: str,
) -> ProviderIdentitySnapshot:
    method = ProviderAuthenticationMethod.API_KEY
    if config_path is None:
        return _missing_private_environment_snapshot(
            ProviderKind.CLAUDE, method, identity, native_home
        )
    assert secret is not None
    persist_provider_secret(
        provider_environment_file_path(config_path),
        key=ANTHROPIC_API_KEY,
        value=secret,
    )
    return _successful_identity_snapshot(ProviderKind.CLAUDE, method, identity, native_home)


def _save_openclaw_credential(
    *,
    config_path: Path | None,
    method: ProviderAuthenticationMethod,
    secret: str | None,
    identity: str,
    native_home: str,
) -> ProviderIdentitySnapshot:
    if config_path is None:
        return _missing_private_environment_snapshot(
            ProviderKind.OPENCLAW,
            method,
            identity,
            native_home,
        )
    assert secret is not None
    key = (
        OPENCLAW_GATEWAY_TOKEN
        if method is ProviderAuthenticationMethod.TOKEN
        else OPENCLAW_GATEWAY_PASSWORD
    )
    opposite = (
        OPENCLAW_GATEWAY_PASSWORD if key == OPENCLAW_GATEWAY_TOKEN else OPENCLAW_GATEWAY_TOKEN
    )
    persist_provider_secret(
        provider_environment_file_path(config_path),
        key=key,
        value=secret,
        remove=frozenset({opposite}),
    )
    return _successful_identity_snapshot(ProviderKind.OPENCLAW, method, identity, native_home)


def _run_native_login(
    *,
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
    identity: str,
    native_home: str,
    config_path: Path | None,
    secret: str | None,
    is_json_output: bool,
    command_runner: NativeCommandRunner | None,
) -> ProviderIdentitySnapshot:
    try:
        command, input_text = _native_login_command(provider, method, secret)
    except FileNotFoundError:
        return ProviderIdentitySnapshot(
            provider=provider,
            action="login",
            outcome=ProviderIdentityOutcome.NOT_INSTALLED,
            service_identity=identity,
            native_home=native_home,
            authentication_method=method,
            detail=f"the SDK-bundled {provider.value.title()} CLI is not available",
        )
    completed = _invoke_native_identity_command(
        command,
        is_json_output=is_json_output,
        input_text=input_text,
        environment=provider_subprocess_environment(),
        command_runner=command_runner,
    )
    if completed.returncode == 0:
        if provider is ProviderKind.CLAUDE and config_path is not None:
            remove_provider_secrets(
                provider_environment_file_path(config_path),
                keys=frozenset({ANTHROPIC_API_KEY}),
            )
        outcome = ProviderIdentityOutcome.SUCCEEDED
        detail = f"native {provider.value.title()} login completed"
    else:
        outcome = ProviderIdentityOutcome.FAILED
        detail = f"native {provider.value.title()} login failed"
    return ProviderIdentitySnapshot(
        provider=provider,
        action="login",
        outcome=outcome,
        service_identity=identity,
        native_home=native_home,
        authentication_method=method,
        detail=detail,
    )


def _native_login_command(
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
    secret: str | None,
) -> tuple[list[str], str | None]:
    if provider is ProviderKind.CODEX:
        command = [str(bundled_codex_path()), "login"]
        if method is ProviderAuthenticationMethod.API_KEY:
            assert secret is not None
            return [*command, "--with-api-key"], f"{secret}\n"
        return command, None
    return [str(bundled_claude_path()), "auth", "login", "--claudeai"], None


def _logout_provider_identity(
    *,
    provider: ProviderKind,
    identity: str,
    native_home: str,
    config_path: Path | None,
    is_json_output: bool,
    command_runner: NativeCommandRunner | None,
) -> ProviderIdentitySnapshot:
    removed_claude_api_key = False
    if config_path is not None:
        environment_path = provider_environment_file_path(config_path)
        if provider is ProviderKind.CLAUDE:
            removed_claude_api_key = ANTHROPIC_API_KEY in read_provider_secret_environment(
                environment_path
            )
            remove_provider_secrets(environment_path, keys=frozenset({ANTHROPIC_API_KEY}))
        elif provider is ProviderKind.OPENCLAW:
            remove_provider_secrets(
                environment_path,
                keys=frozenset({OPENCLAW_GATEWAY_TOKEN, OPENCLAW_GATEWAY_PASSWORD}),
            )
            return ProviderIdentitySnapshot(
                provider=provider,
                action="logout",
                outcome=ProviderIdentityOutcome.SUCCEEDED,
                service_identity=identity,
                native_home=native_home,
                detail="stored OpenClaw Gateway credential removed",
            )

    try:
        command = (
            [str(bundled_codex_path()), "logout"]
            if provider is ProviderKind.CODEX
            else [str(bundled_claude_path()), "auth", "logout"]
        )
    except FileNotFoundError:
        if removed_claude_api_key:
            return ProviderIdentitySnapshot(
                provider=provider,
                action="logout",
                outcome=ProviderIdentityOutcome.PARTIAL,
                service_identity=identity,
                native_home=native_home,
                detail="stored Claude API key removed; native subscription logout was unavailable",
            )
        return ProviderIdentitySnapshot(
            provider=provider,
            action="logout",
            outcome=ProviderIdentityOutcome.NOT_INSTALLED,
            service_identity=identity,
            native_home=native_home,
            detail=f"the SDK-bundled {provider.value.title()} CLI is not available",
        )
    completed = _invoke_native_identity_command(
        command,
        is_json_output=is_json_output,
        environment=provider_subprocess_environment(),
        command_runner=command_runner,
    )
    succeeded = completed.returncode == 0
    outcome = ProviderIdentityOutcome.SUCCEEDED if succeeded else ProviderIdentityOutcome.FAILED
    detail = (
        f"native {provider.value.title()} logout completed"
        if succeeded
        else f"native {provider.value.title()} logout failed"
    )
    if not succeeded and removed_claude_api_key:
        outcome = ProviderIdentityOutcome.PARTIAL
        detail = "stored Claude API key removed; native subscription logout failed"
    return ProviderIdentitySnapshot(
        provider=provider,
        action="logout",
        outcome=outcome,
        service_identity=identity,
        native_home=native_home,
        detail=detail,
    )


def _missing_private_environment_snapshot(
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
    identity: str,
    native_home: str,
) -> ProviderIdentitySnapshot:
    return ProviderIdentitySnapshot(
        provider=provider,
        action="login",
        outcome=ProviderIdentityOutcome.FAILED,
        service_identity=identity,
        native_home=native_home,
        authentication_method=method,
        detail="the AutoClaw config path is required to store this credential",
    )


def _successful_identity_snapshot(
    provider: ProviderKind,
    method: ProviderAuthenticationMethod,
    identity: str,
    native_home: str,
) -> ProviderIdentitySnapshot:
    return ProviderIdentitySnapshot(
        provider=provider,
        action="login",
        outcome=ProviderIdentityOutcome.SUCCEEDED,
        service_identity=identity,
        native_home=native_home,
        authentication_method=method,
        detail=f"{authentication_method_label(method)} saved for {provider.value}",
    )


def _identity_action(action: str) -> Literal["login", "logout"]:
    if action == "login":
        return "login"
    if action == "logout":
        return "logout"
    raise ValueError(f"unsupported provider identity action: {action}")


def _invoke_native_identity_command(
    command: list[str],
    *,
    is_json_output: bool,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
    command_runner: NativeCommandRunner | None,
) -> subprocess.CompletedProcess[str]:
    if command_runner is not None:
        options: dict[str, object] = {"check": False, "text": True}
        if input_text is not None:
            options["input"] = input_text
        if environment is not None:
            options["env"] = environment
        if is_json_output:
            options.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return command_runner(command, **options)
    return subprocess.run(
        command,
        check=False,
        text=True,
        input=input_text,
        env=environment,
        stdout=subprocess.DEVNULL if is_json_output else None,
        stderr=subprocess.DEVNULL if is_json_output else None,
    )


def bundled_codex_path() -> Path:
    """Resolve the SDK-bundled CLI without loading it for passive commands."""

    from codex_cli_bin import bundled_codex_path as resolve_path  # type: ignore[import-untyped]

    return Path(resolve_path())


__all__ = [
    "authentication_method_choices",
    "authentication_method_label",
    "bundled_codex_path",
    "invoke_provider_identity_action",
    "provider_native_home",
    "provider_secret_environment_key",
    "service_identity",
]
