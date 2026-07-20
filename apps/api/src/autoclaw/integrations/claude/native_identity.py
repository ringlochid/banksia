from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import claude_agent_sdk

from autoclaw.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    provider_subprocess_environment,
)
from autoclaw.runtime.providers import ProviderAuthenticationMethod

CLAUDE_AUTH_STATUS_TIMEOUT_SECONDS = 10.0
NativeCommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class ClaudeAuthenticationState:
    is_authenticated: bool
    method: ProviderAuthenticationMethod | None
    code: str


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


__all__ = [
    "CLAUDE_AUTH_STATUS_TIMEOUT_SECONDS",
    "ClaudeAuthenticationState",
    "bundled_claude_path",
    "read_claude_authentication",
]
