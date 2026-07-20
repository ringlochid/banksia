from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from autoclaw.config import OpenClawGatewayAuthMode
from autoclaw.platform.provider_environment import (
    OPENCLAW_GATEWAY_PASSWORD,
    OPENCLAW_GATEWAY_TOKEN,
    PROVIDER_SECRET_ENVIRONMENT_KEYS,
)

DEFAULT_GATEWAY_CALL_TIMEOUT_MS = 10_000
GATEWAY_PROCESS_EXIT_GRACE_SECONDS = 2.0
MAX_GATEWAY_RESPONSE_BYTES = 1_048_576


class OpenClawGatewayFailureCode(StrEnum):
    NOT_INSTALLED = "openclaw_not_installed"
    PROCESS_LAUNCH_FAILED = "openclaw_process_launch_failed"
    AUTHENTICATION_FAILED = "openclaw_authentication_failed"
    UNREACHABLE = "openclaw_gateway_unreachable"
    REJECTED = "openclaw_gateway_rejected"
    TIMEOUT = "openclaw_gateway_timeout"
    INVALID_RESPONSE = "openclaw_gateway_invalid_response"
    CALL_FAILED = "openclaw_gateway_call_failed"


class OpenClawGatewayCliError(RuntimeError):
    """Expose only a stable code and acceptance certainty for one CLI call."""

    def __init__(
        self,
        *,
        code: OpenClawGatewayFailureCode,
        is_acceptance_uncertain: bool,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.is_acceptance_uncertain = is_acceptance_uncertain


async def call_openclaw_gateway(
    *,
    executable: str = "openclaw",
    profile: str,
    gateway_url: str,
    gateway_auth_mode: OpenClawGatewayAuthMode,
    method: str,
    params: Mapping[str, object],
    working_directory: Path | None = None,
    timeout_ms: int = DEFAULT_GATEWAY_CALL_TIMEOUT_MS,
) -> dict[str, object]:
    """Call one Gateway method through the user-installed OpenClaw CLI."""

    command = build_openclaw_gateway_command(
        executable=executable,
        profile=profile,
        method=method,
        params=params,
        timeout_ms=timeout_ms,
    )
    process_environment = build_openclaw_gateway_environment(
        gateway_url=gateway_url,
        gateway_auth_mode=gateway_auth_mode,
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=None if working_directory is None else str(working_directory),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_environment,
        )
    except FileNotFoundError:
        raise OpenClawGatewayCliError(
            code=OpenClawGatewayFailureCode.NOT_INSTALLED,
            is_acceptance_uncertain=False,
        ) from None
    except OSError:
        raise OpenClawGatewayCliError(
            code=OpenClawGatewayFailureCode.PROCESS_LAUNCH_FAILED,
            is_acceptance_uncertain=False,
        ) from None

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=(timeout_ms / 1000) + GATEWAY_PROCESS_EXIT_GRACE_SECONDS,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise OpenClawGatewayCliError(
            code=OpenClawGatewayFailureCode.TIMEOUT,
            is_acceptance_uncertain=method in {"agent", "sessions.abort"},
        ) from None

    if process.returncode != 0:
        code, is_definite = classify_gateway_cli_failure(stderr)
        raise OpenClawGatewayCliError(
            code=code,
            is_acceptance_uncertain=method == "agent" and not is_definite,
        )
    return parse_gateway_response(stdout, can_accept_work=method == "agent")


def build_openclaw_gateway_command(
    *,
    executable: str = "openclaw",
    profile: str,
    method: str,
    params: Mapping[str, object],
    timeout_ms: int,
) -> tuple[str, ...]:
    """Build the non-final-waiting Gateway CLI request."""

    serialized_params = json.dumps(
        params,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        executable,
        "--profile",
        profile,
        "gateway",
        "call",
        method,
        "--params",
        serialized_params,
        "--json",
        "--timeout",
        str(timeout_ms),
    )


def build_openclaw_gateway_environment(
    *,
    gateway_url: str,
    gateway_auth_mode: OpenClawGatewayAuthMode,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment without placing Gateway secrets on argv."""

    source = os.environ if environment is None else environment
    credential_key = {
        OpenClawGatewayAuthMode.TOKEN: OPENCLAW_GATEWAY_TOKEN,
        OpenClawGatewayAuthMode.PASSWORD: OPENCLAW_GATEWAY_PASSWORD,
    }[gateway_auth_mode]
    secret = source.get(credential_key)
    if not secret:
        raise OpenClawGatewayCliError(
            code=OpenClawGatewayFailureCode.AUTHENTICATION_FAILED,
            is_acceptance_uncertain=False,
        )

    child_environment = dict(source)
    child_environment["OPENCLAW_GATEWAY_URL"] = gateway_url
    for key in PROVIDER_SECRET_ENVIRONMENT_KEYS:
        child_environment.pop(key, None)
    child_environment[credential_key] = secret
    return child_environment


def classify_gateway_cli_failure(
    stderr: bytes,
) -> tuple[OpenClawGatewayFailureCode, bool]:
    """Classify a bounded diagnostic without returning provider text."""

    diagnostic = stderr[:16_384].decode("utf-8", errors="replace").casefold()
    if any(
        marker in diagnostic
        for marker in (
            "explicit credentials",
            "authentication",
            "not authenticated",
            "unauthorized",
            "forbidden",
        )
    ):
        return OpenClawGatewayFailureCode.AUTHENTICATION_FAILED, True
    if any(
        marker in diagnostic
        for marker in (
            "econnrefused",
            "connection refused",
            "enotfound",
            "could not connect",
            "failed to connect",
        )
    ):
        return OpenClawGatewayFailureCode.UNREACHABLE, True
    if any(
        marker in diagnostic
        for marker in (
            "invalid agent params",
            "invalid request",
            "not supported",
            "unsupported",
            "rejected",
        )
    ):
        return OpenClawGatewayFailureCode.REJECTED, True
    if "timeout" in diagnostic or "timed out" in diagnostic:
        return OpenClawGatewayFailureCode.TIMEOUT, False
    return OpenClawGatewayFailureCode.CALL_FAILED, False


def parse_gateway_response(
    stdout: bytes,
    *,
    can_accept_work: bool,
) -> dict[str, object]:
    """Parse one bounded JSON object without retaining raw CLI output."""

    if len(stdout) > MAX_GATEWAY_RESPONSE_BYTES:
        raise OpenClawGatewayCliError(
            code=OpenClawGatewayFailureCode.INVALID_RESPONSE,
            is_acceptance_uncertain=can_accept_work,
        )
    try:
        payload = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OpenClawGatewayCliError(
            code=OpenClawGatewayFailureCode.INVALID_RESPONSE,
            is_acceptance_uncertain=can_accept_work,
        ) from None
    if not isinstance(payload, dict):
        raise OpenClawGatewayCliError(
            code=OpenClawGatewayFailureCode.INVALID_RESPONSE,
            is_acceptance_uncertain=can_accept_work,
        )
    return payload


__all__ = [
    "DEFAULT_GATEWAY_CALL_TIMEOUT_MS",
    "OpenClawGatewayCliError",
    "OpenClawGatewayFailureCode",
    "build_openclaw_gateway_command",
    "build_openclaw_gateway_environment",
    "call_openclaw_gateway",
    "classify_gateway_cli_failure",
    "parse_gateway_response",
]
