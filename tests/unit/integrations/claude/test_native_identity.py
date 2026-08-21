from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from oh_my_subagents.integrations.claude.native_identity import (
    ClaudeAuthenticationState,
    ClaudeEndpointPolicyState,
    ClaudeIsolationMode,
    ClaudeSubscriptionClass,
    read_claude_authentication,
    read_claude_endpoint_policy,
    read_claude_invocation_readiness,
)
from oh_my_subagents.runtime.providers import ProviderAuthenticationMethod


@pytest.mark.parametrize(
    ("auth_method", "api_key_source", "subscription_type", "expected", "subscription_class"),
    (
        (
            "claude.ai",
            None,
            "pro",
            ProviderAuthenticationMethod.SUBSCRIPTION,
            ClaudeSubscriptionClass.PERSONAL,
        ),
        (
            "claude.ai",
            None,
            "enterprise",
            ProviderAuthenticationMethod.SUBSCRIPTION,
            ClaudeSubscriptionClass.MANAGED,
        ),
        ("api_key", None, None, ProviderAuthenticationMethod.API_KEY, None),
        (
            "claude.ai",
            "ANTHROPIC_API_KEY",
            "pro",
            ProviderAuthenticationMethod.API_KEY,
            None,
        ),
    ),
)
def test_claude_auth_status_accepts_subscription_and_api_key_without_account_readback(
    monkeypatch: pytest.MonkeyPatch,
    auth_method: str,
    api_key_source: str | None,
    subscription_type: str | None,
    expected: ProviderAuthenticationMethod,
    subscription_class: ClaudeSubscriptionClass | None,
) -> None:
    monkeypatch.setattr(
        "oh_my_subagents.integrations.claude.native_identity.bundled_claude_path",
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
                    "subscriptionType": subscription_type,
                    "email": "must-not-be-retained@example.com",
                    "orgId": "must-not-be-retained",
                }
            ),
        )

    state = read_claude_authentication(command_runner=run)

    assert state.is_authenticated is True
    assert state.method is expected
    assert state.code == "claude_available"
    assert state.subscription_class is subscription_class
    assert command_calls == [["/sdk/claude", "auth", "status", "--json"]]
    assert not hasattr(state, "email")
    assert not hasattr(state, "org_id")


def test_claude_auth_status_reports_missing_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "oh_my_subagents.integrations.claude.native_identity.bundled_claude_path",
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
        "oh_my_subagents.integrations.claude.native_identity.bundled_claude_path",
        lambda: "/sdk/claude",
    )

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="native failure")

    state = read_claude_authentication(command_runner=run)

    assert state.is_authenticated is False
    assert state.method is None
    assert state.code == "claude_check_failed"


@pytest.mark.parametrize("filename", ("managed-settings.json", "managed-mcp.json"))
def test_claude_endpoint_policy_detects_supported_file_locations(
    tmp_path: Path,
    filename: str,
) -> None:
    (tmp_path / filename).write_text("{}", encoding="utf-8")

    state = read_claude_endpoint_policy(
        system_name="Linux",
        policy_directory=tmp_path,
    )

    assert state.is_installed is True
    assert state.code == "claude_endpoint_policy_unsupported"


def test_claude_endpoint_policy_detects_macos_and_windows_native_policy(
    tmp_path: Path,
) -> None:
    def defaults(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="<plist/>", stderr="")

    macos = read_claude_endpoint_policy(
        system_name="Darwin",
        policy_directory=tmp_path,
        command_runner=defaults,
    )
    windows = read_claude_endpoint_policy(
        system_name="Windows",
        policy_directory=tmp_path,
        windows_registry_reader=lambda: True,
    )

    assert macos.is_installed is True
    assert windows.is_installed is True


@pytest.mark.parametrize(
    ("authentication", "policy", "expected_mode", "expected_code"),
    (
        (
            ClaudeAuthenticationState(
                is_authenticated=True,
                method=ProviderAuthenticationMethod.API_KEY,
                code="claude_available",
            ),
            ClaudeEndpointPolicyState(
                is_installed=True,
                code="claude_endpoint_policy_unsupported",
            ),
            ClaudeIsolationMode.BARE,
            "claude_available",
        ),
        (
            ClaudeAuthenticationState(
                is_authenticated=True,
                method=ProviderAuthenticationMethod.SUBSCRIPTION,
                code="claude_available",
                subscription_class=ClaudeSubscriptionClass.PERSONAL,
            ),
            ClaudeEndpointPolicyState(
                is_installed=False,
                code="claude_endpoint_policy_clear",
            ),
            ClaudeIsolationMode.STANDARD,
            "claude_available",
        ),
        (
            ClaudeAuthenticationState(
                is_authenticated=True,
                method=ProviderAuthenticationMethod.SUBSCRIPTION,
                code="claude_available",
                subscription_class=ClaudeSubscriptionClass.MANAGED,
            ),
            ClaudeEndpointPolicyState(
                is_installed=False,
                code="claude_endpoint_policy_clear",
            ),
            None,
            "claude_managed_subscription_unsupported",
        ),
        (
            ClaudeAuthenticationState(
                is_authenticated=True,
                method=ProviderAuthenticationMethod.SUBSCRIPTION,
                code="claude_available",
                subscription_class=ClaudeSubscriptionClass.PERSONAL,
            ),
            ClaudeEndpointPolicyState(
                is_installed=True,
                code="claude_endpoint_policy_unsupported",
            ),
            None,
            "claude_endpoint_policy_unsupported",
        ),
    ),
)
def test_claude_invocation_mode_fails_closed_for_managed_subscription_boundaries(
    authentication: ClaudeAuthenticationState,
    policy: ClaudeEndpointPolicyState,
    expected_mode: ClaudeIsolationMode | None,
    expected_code: str,
) -> None:
    readiness = read_claude_invocation_readiness(
        authentication_reader=lambda: authentication,
        endpoint_policy_reader=lambda: policy,
    )

    assert readiness.isolation_mode is expected_mode
    assert readiness.code == expected_code


def test_claude_standard_mode_requires_clear_policy_for_api_key_tasks() -> None:
    authentication = ClaudeAuthenticationState(
        is_authenticated=True,
        method=ProviderAuthenticationMethod.API_KEY,
        code="claude_available",
    )

    ready = read_claude_invocation_readiness(
        authentication_reader=lambda: authentication,
        endpoint_policy_reader=lambda: ClaudeEndpointPolicyState(
            is_installed=False,
            code="claude_endpoint_policy_clear",
        ),
        should_use_standard_mode=True,
    )
    blocked = read_claude_invocation_readiness(
        authentication_reader=lambda: authentication,
        endpoint_policy_reader=lambda: ClaudeEndpointPolicyState(
            is_installed=True,
            code="claude_endpoint_policy_unsupported",
        ),
        should_use_standard_mode=True,
    )

    assert ready.isolation_mode is ClaudeIsolationMode.STANDARD
    assert blocked.isolation_mode is None
    assert blocked.code == "claude_endpoint_policy_unsupported"
