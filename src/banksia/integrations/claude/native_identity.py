from __future__ import annotations

import json
import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import Any

import claude_agent_sdk

from banksia.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    provider_subprocess_environment,
)
from banksia.runtime.providers import ProviderAuthenticationMethod

CLAUDE_AUTH_STATUS_TIMEOUT_SECONDS = 10.0
NativeCommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class ClaudeSubscriptionClass(StrEnum):
    """Policy-relevant subscription class without retained account details."""

    PERSONAL = "personal"
    MANAGED = "managed"
    UNKNOWN = "unknown"


class ClaudeIsolationMode(StrEnum):
    """Pinned Claude CLI isolation mode legal for one native identity."""

    BARE = "bare"
    SUBSCRIPTION = "subscription"


@dataclass(frozen=True, slots=True)
class ClaudeAuthenticationState:
    is_authenticated: bool
    method: ProviderAuthenticationMethod | None
    code: str
    subscription_class: ClaudeSubscriptionClass | None = None


@dataclass(frozen=True, slots=True)
class ClaudeEndpointPolicyState:
    is_installed: bool | None
    code: str


@dataclass(frozen=True, slots=True)
class ClaudeInvocationReadiness:
    method: ProviderAuthenticationMethod | None
    isolation_mode: ClaudeIsolationMode | None
    code: str

    @property
    def is_available(self) -> bool:
        return self.isolation_mode is not None


def read_claude_invocation_readiness(
    *,
    authentication_reader: Callable[[], ClaudeAuthenticationState] | None = None,
    endpoint_policy_reader: Callable[[], ClaudeEndpointPolicyState] | None = None,
) -> ClaudeInvocationReadiness:
    """Select a documented isolation mode or return one sanitized failure."""

    read_authentication = authentication_reader or read_claude_authentication
    read_endpoint_policy = endpoint_policy_reader or read_claude_endpoint_policy
    try:
        authentication = read_authentication()
    except Exception:
        return ClaudeInvocationReadiness(
            method=None,
            isolation_mode=None,
            code="claude_check_failed",
        )
    if not authentication.is_authenticated or authentication.method is None:
        return ClaudeInvocationReadiness(
            method=authentication.method,
            isolation_mode=None,
            code=authentication.code,
        )
    if authentication.method is ProviderAuthenticationMethod.API_KEY:
        return ClaudeInvocationReadiness(
            method=authentication.method,
            isolation_mode=ClaudeIsolationMode.BARE,
            code="claude_available",
        )
    if authentication.subscription_class is ClaudeSubscriptionClass.MANAGED:
        return ClaudeInvocationReadiness(
            method=authentication.method,
            isolation_mode=None,
            code="claude_managed_subscription_unsupported",
        )
    if authentication.subscription_class is not ClaudeSubscriptionClass.PERSONAL:
        return ClaudeInvocationReadiness(
            method=authentication.method,
            isolation_mode=None,
            code="claude_subscription_unverified",
        )

    try:
        endpoint_policy = read_endpoint_policy()
    except Exception:
        endpoint_policy = ClaudeEndpointPolicyState(
            is_installed=None,
            code="claude_endpoint_policy_check_failed",
        )
    if endpoint_policy.is_installed is not False:
        return ClaudeInvocationReadiness(
            method=authentication.method,
            isolation_mode=None,
            code=endpoint_policy.code,
        )
    return ClaudeInvocationReadiness(
        method=authentication.method,
        isolation_mode=ClaudeIsolationMode.SUBSCRIPTION,
        code="claude_available",
    )


def read_claude_authentication(
    *,
    command_runner: NativeCommandRunner = subprocess.run,
) -> ClaudeAuthenticationState:
    """Inspect native Claude identity without retaining account details."""

    try:
        completed = command_runner(
            [str(bundled_claude_path()), "auth", "status", "--json"],
            check=False,
            capture_output=True,
            env=provider_subprocess_environment(allowed_keys=frozenset({ANTHROPIC_API_KEY})),
            text=True,
            timeout=CLAUDE_AUTH_STATUS_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return ClaudeAuthenticationState(
            is_authenticated=False,
            method=None,
            code="claude_check_failed",
        )
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return ClaudeAuthenticationState(
            is_authenticated=False,
            method=None,
            code="claude_check_failed",
        )
    if not isinstance(payload, dict) or payload.get("loggedIn") is not True:
        return ClaudeAuthenticationState(
            is_authenticated=False,
            method=None,
            code="claude_authentication_required",
        )
    if completed.returncode != 0:
        return ClaudeAuthenticationState(
            is_authenticated=False,
            method=None,
            code="claude_check_failed",
        )

    method = _authentication_method(
        payload.get("authMethod"),
        api_key_source=payload.get("apiKeySource"),
    )
    if method is None:
        return ClaudeAuthenticationState(
            is_authenticated=False,
            method=None,
            code="claude_authentication_unsupported",
        )
    return ClaudeAuthenticationState(
        is_authenticated=True,
        method=method,
        code="claude_available",
        subscription_class=(
            _subscription_class(payload.get("subscriptionType"))
            if method is ProviderAuthenticationMethod.SUBSCRIPTION
            else None
        ),
    )


def read_claude_endpoint_policy(
    *,
    system_name: str | None = None,
    policy_directory: Path | None = None,
    command_runner: NativeCommandRunner = subprocess.run,
    windows_registry_reader: Callable[[], bool | None] | None = None,
) -> ClaudeEndpointPolicyState:
    """Detect supported endpoint-managed policy locations without reading policy bodies."""

    system = system_name or platform.system()
    directory = policy_directory or _managed_policy_directory(system)
    if directory is None:
        return ClaudeEndpointPolicyState(
            is_installed=None,
            code="claude_endpoint_policy_check_failed",
        )

    try:
        file_policy = _file_policy_present(directory)
    except OSError:
        return ClaudeEndpointPolicyState(
            is_installed=None,
            code="claude_endpoint_policy_check_failed",
        )
    if file_policy:
        return ClaudeEndpointPolicyState(
            is_installed=True,
            code="claude_endpoint_policy_unsupported",
        )

    native_policy: bool | None = False
    if system == "Darwin":
        native_policy = _macos_policy_present(command_runner)
    elif system == "Windows":
        native_policy = (windows_registry_reader or _windows_policy_present)()
    if native_policy is None:
        return ClaudeEndpointPolicyState(
            is_installed=None,
            code="claude_endpoint_policy_check_failed",
        )
    if native_policy:
        return ClaudeEndpointPolicyState(
            is_installed=True,
            code="claude_endpoint_policy_unsupported",
        )
    return ClaudeEndpointPolicyState(
        is_installed=False,
        code="claude_endpoint_policy_clear",
    )


def bundled_claude_path() -> Path:
    """Return the Claude Code binary shipped with the pinned Agent SDK."""

    package_file = getattr(claude_agent_sdk, "__file__", None)
    if package_file is None:
        raise FileNotFoundError("the Claude Agent SDK package path is unavailable")
    binary_name = "claude.exe" if os.name == "nt" else "claude"
    binary = Path(package_file).resolve().parent / "_bundled" / binary_name
    if not binary.is_file():
        raise FileNotFoundError("the SDK-bundled Claude Code CLI is unavailable")
    return binary


def _authentication_method(
    value: object,
    *,
    api_key_source: object = None,
) -> ProviderAuthenticationMethod | None:
    if api_key_source == ANTHROPIC_API_KEY:
        return ProviderAuthenticationMethod.API_KEY
    if value == "api_key":
        return ProviderAuthenticationMethod.API_KEY
    if value in {"claude.ai", "oauth", "oauth_token"}:
        return ProviderAuthenticationMethod.SUBSCRIPTION
    return None


def _subscription_class(value: object) -> ClaudeSubscriptionClass:
    if not isinstance(value, str):
        return ClaudeSubscriptionClass.UNKNOWN
    normalized = value.strip().casefold()
    if normalized in {"pro", "max"}:
        return ClaudeSubscriptionClass.PERSONAL
    if normalized in {"team", "enterprise"}:
        return ClaudeSubscriptionClass.MANAGED
    return ClaudeSubscriptionClass.UNKNOWN


def _managed_policy_directory(system_name: str) -> Path | None:
    if system_name == "Darwin":
        return Path("/Library/Application Support/ClaudeCode")
    if system_name == "Linux":
        return Path("/etc/claude-code")
    if system_name == "Windows":
        return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ClaudeCode"
    return None


def _file_policy_present(directory: Path) -> bool:
    if any((directory / name).exists() for name in ("managed-settings.json", "managed-mcp.json")):
        return True
    dropins = directory / "managed-settings.d"
    if not dropins.exists():
        return False
    if not dropins.is_dir():
        return True
    return any(
        entry.is_file() and not entry.name.startswith(".") and entry.suffix.casefold() == ".json"
        for entry in dropins.iterdir()
    )


def _macos_policy_present(command_runner: NativeCommandRunner) -> bool | None:
    try:
        completed = command_runner(
            ["defaults", "export", "com.anthropic.claudecode", "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=CLAUDE_AUTH_STATUS_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if completed.returncode == 0:
        return True
    error = completed.stderr.casefold()
    if "does not exist" in error or ("domain" in error and "not found" in error):
        return False
    return None


def _windows_policy_present() -> bool | None:
    try:
        winreg: Any = import_module("winreg")
    except ImportError:
        return None
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(root, r"SOFTWARE\Policies\ClaudeCode")
        except FileNotFoundError:
            continue
        except OSError:
            return None
        winreg.CloseKey(key)
        return True
    return False


__all__ = [
    "CLAUDE_AUTH_STATUS_TIMEOUT_SECONDS",
    "ClaudeAuthenticationState",
    "ClaudeEndpointPolicyState",
    "ClaudeInvocationReadiness",
    "ClaudeIsolationMode",
    "ClaudeSubscriptionClass",
    "bundled_claude_path",
    "read_claude_authentication",
    "read_claude_endpoint_policy",
    "read_claude_invocation_readiness",
]
