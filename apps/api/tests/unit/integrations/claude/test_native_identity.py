from __future__ import annotations

import json
import subprocess

import pytest
from autoclaw.integrations.claude.native_identity import read_claude_authentication
from autoclaw.runtime.providers import ProviderAuthenticationMethod


@pytest.mark.parametrize(
    ("auth_method", "api_key_source", "expected"),
    (
        ("claude.ai", None, ProviderAuthenticationMethod.SUBSCRIPTION),
        ("api_key", None, ProviderAuthenticationMethod.API_KEY),
        ("claude.ai", "ANTHROPIC_API_KEY", ProviderAuthenticationMethod.API_KEY),
    ),
)
def test_claude_auth_status_accepts_subscription_and_api_key_without_account_readback(
    monkeypatch: pytest.MonkeyPatch,
    auth_method: str,
    api_key_source: str | None,
    expected: ProviderAuthenticationMethod,
) -> None:
    monkeypatch.setattr(
        "autoclaw.integrations.claude.native_identity.bundled_claude_path",
        lambda: "/sdk/claude",
    )
    command_calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command_calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": auth_method,
                    "apiKeySource": api_key_source,
                    "email": "must-not-be-retained@example.com",
                }
            ),
        )

    state = read_claude_authentication(command_runner=run)

    assert state.is_authenticated is True
    assert state.method is expected
    assert state.code == "claude_available"
    assert command_calls == [["/sdk/claude", "auth", "status", "--json"]]
    assert not hasattr(state, "email")


def test_claude_auth_status_reports_missing_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "autoclaw.integrations.claude.native_identity.bundled_claude_path",
        lambda: "/sdk/claude",
    )

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout='{"loggedIn":false,"authMethod":"none"}',
        )

    state = read_claude_authentication(command_runner=run)

    assert state.is_authenticated is False
    assert state.method is None
    assert state.code == "claude_authentication_required"


def test_claude_auth_status_keeps_unstructured_native_failure_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "autoclaw.integrations.claude.native_identity.bundled_claude_path",
        lambda: "/sdk/claude",
    )

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="native failure")

    state = read_claude_authentication(command_runner=run)

    assert state.is_authenticated is False
    assert state.method is None
    assert state.code == "claude_check_failed"
