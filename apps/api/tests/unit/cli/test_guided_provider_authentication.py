from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.interfaces.cli import root as cli_root
from autoclaw.interfaces.cli.commands import guided_setup
from autoclaw.interfaces.cli.main import build_parser
from autoclaw.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
    ProviderIdentityOutcome,
    ProviderIdentitySnapshot,
)
from autoclaw.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    read_provider_secret_environment,
)
from autoclaw.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
)
from click.testing import CliRunner

from tests.unit.cli.cli_test_support import (
    build_provider_check_snapshot,
    write_local_cli_config,
)


def test_guided_setup_selects_default_and_offers_codex_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checks = iter(
        (
            build_provider_check_snapshot(
                ProviderKind.CODEX,
                outcome=ProviderCheckOutcome.AUTHENTICATION_FAILED,
                is_ready=False,
                detail="codex_authentication_required",
                authentication=ProviderCheckAxisStatus.FAILED,
            ),
            build_provider_check_snapshot(
                ProviderKind.CODEX,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="codex_available",
            ),
        )
    )
    identity_calls: list[ProviderKind] = []
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(guided_setup, "collect_provider_check", lambda *_args: next(checks))

    def login(
        provider: ProviderKind, *_args: object, **_kwargs: object
    ) -> ProviderIdentitySnapshot:
        identity_calls.append(provider)
        return ProviderIdentitySnapshot(
            provider=provider,
            action="login",
            outcome=ProviderIdentityOutcome.SUCCEEDED,
            service_identity="tester",
            native_home="/tmp/codex-home",
            detail="native Codex login completed",
        )

    monkeypatch.setattr(guided_setup, "invoke_provider_identity_action", login)

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path)],
        input="\n\n\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["codex"]["enabled"] is True
    assert payload["runtime"]["default_provider"] == "codex"
    assert identity_calls == [ProviderKind.CODEX]
    assert "Codex authentication" in result.output
    assert "Codex subscription login is ready" in result.output
    assert "codex: ready" in result.output


def test_guided_setup_accepts_claude_api_key_and_verifies_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checks = iter(
        (
            build_provider_check_snapshot(
                ProviderKind.CLAUDE,
                outcome=ProviderCheckOutcome.AUTHENTICATION_FAILED,
                is_ready=False,
                detail="claude_authentication_required",
                authentication=ProviderCheckAxisStatus.FAILED,
            ),
            build_provider_check_snapshot(
                ProviderKind.CLAUDE,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="claude_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.API_KEY,
            ),
        )
    )
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(guided_setup, "collect_provider_check", lambda *_args: next(checks))

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "claude"],
        input="api-key\nanthropic-secret\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert read_provider_secret_environment(config_path.parent / "autoclaw.env") == {
        ANTHROPIC_API_KEY: "anthropic-secret"
    }
    assert "anthropic-secret" not in result.output
    assert "Anthropic API key" in result.output
    assert "Claude API key is ready" in result.output


def test_guided_setup_can_replace_existing_codex_subscription_with_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checks = iter(
        (
            build_provider_check_snapshot(
                ProviderKind.CODEX,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="codex_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
            ),
            build_provider_check_snapshot(
                ProviderKind.CODEX,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="codex_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.API_KEY,
            ),
        )
    )
    identity_calls: list[tuple[ProviderAuthenticationMethod | None, str | None]] = []
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(guided_setup, "collect_provider_check", lambda *_args: next(checks))

    def login(
        provider: ProviderKind,
        *_args: object,
        authentication_method: ProviderAuthenticationMethod | None = None,
        secret: str | None = None,
        **_kwargs: object,
    ) -> ProviderIdentitySnapshot:
        identity_calls.append((authentication_method, secret))
        return ProviderIdentitySnapshot(
            provider=provider,
            action="login",
            outcome=ProviderIdentityOutcome.SUCCEEDED,
            service_identity="tester",
            native_home="/tmp/codex-home",
            authentication_method=authentication_method,
            detail="native Codex login completed",
        )

    monkeypatch.setattr(guided_setup, "invoke_provider_identity_action", login)

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "codex"],
        input="api-key\ncodex-api-secret\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert "Codex authentication" in result.output
    assert "OpenAI API key" in result.output
    assert identity_calls == [(ProviderAuthenticationMethod.API_KEY, "codex-api-secret")]
    assert "codex-api-secret" not in result.output
    assert "Codex API key is ready" in result.output


@pytest.mark.parametrize("provider", (ProviderKind.CODEX, ProviderKind.CLAUDE))
def test_guided_setup_confirms_reusing_detected_subscription_login(
    provider: ProviderKind,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    check_calls: list[ProviderKind] = []
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    def ready_check(_settings: object, checked_provider: ProviderKind) -> ProviderCheckSnapshot:
        check_calls.append(checked_provider)
        return build_provider_check_snapshot(
            checked_provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail=f"{checked_provider.value}_available",
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
        )

    monkeypatch.setattr(guided_setup, "collect_provider_check", ready_check)
    monkeypatch.setattr(
        guided_setup,
        "invoke_provider_identity_action",
        lambda *_args, **_kwargs: pytest.fail("reusing auth started a new login"),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", provider.value],
        input="\n\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert (
        f"Existing {provider.value.title()} subscription login found. Use it? [Y/n]"
        in result.output
    )
    assert f"Using existing {provider.value} subscription login" in result.output
    assert check_calls == [provider]


@pytest.mark.parametrize("provider", (ProviderKind.CODEX, ProviderKind.CLAUDE))
def test_guided_setup_can_replace_detected_subscription_login(
    provider: ProviderKind,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checks = iter(
        (
            build_provider_check_snapshot(
                provider,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail=f"{provider.value}_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
            ),
            build_provider_check_snapshot(
                provider,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail=f"{provider.value}_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
            ),
        )
    )
    identity_calls: list[ProviderAuthenticationMethod | None] = []
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(guided_setup, "collect_provider_check", lambda *_args: next(checks))

    def login(
        checked_provider: ProviderKind,
        *_args: object,
        authentication_method: ProviderAuthenticationMethod | None = None,
        **_kwargs: object,
    ) -> ProviderIdentitySnapshot:
        identity_calls.append(authentication_method)
        return ProviderIdentitySnapshot(
            provider=checked_provider,
            action="login",
            outcome=ProviderIdentityOutcome.SUCCEEDED,
            service_identity="tester",
            native_home=f"/tmp/{checked_provider.value}-home",
            authentication_method=authentication_method,
            detail=f"native {checked_provider.value} login completed",
        )

    monkeypatch.setattr(guided_setup, "invoke_provider_identity_action", login)

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", provider.value],
        input="\nn\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert (
        f"Existing {provider.value.title()} subscription login found. Use it? [Y/n]"
        in result.output
    )
    assert "browser or device sign-in" in result.output
    assert identity_calls == [ProviderAuthenticationMethod.SUBSCRIPTION]
    assert f"{provider.value.title()} subscription login is ready" in result.output


def test_guided_setup_can_replace_detected_claude_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checks = iter(
        (
            build_provider_check_snapshot(
                ProviderKind.CLAUDE,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="claude_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.API_KEY,
            ),
            build_provider_check_snapshot(
                ProviderKind.CLAUDE,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="claude_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.API_KEY,
            ),
        )
    )
    identity_calls: list[tuple[ProviderAuthenticationMethod | None, str | None]] = []
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(guided_setup, "collect_provider_check", lambda *_args: next(checks))

    def login(
        provider: ProviderKind,
        *_args: object,
        authentication_method: ProviderAuthenticationMethod | None = None,
        secret: str | None = None,
        **_kwargs: object,
    ) -> ProviderIdentitySnapshot:
        identity_calls.append((authentication_method, secret))
        return ProviderIdentitySnapshot(
            provider=provider,
            action="login",
            outcome=ProviderIdentityOutcome.SUCCEEDED,
            service_identity="tester",
            native_home="/tmp/claude-home",
            authentication_method=authentication_method,
            detail="Claude API key saved",
        )

    monkeypatch.setattr(guided_setup, "invoke_provider_identity_action", login)

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "claude"],
        input="\nn\nreplacement-secret\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert "Existing Claude API key stored for the AutoClaw service. Use it? [Y/n]" in result.output
    assert "Anthropic API key" in result.output
    assert identity_calls == [(ProviderAuthenticationMethod.API_KEY, "replacement-secret")]
    assert "replacement-secret" not in result.output


def test_guided_setup_rejects_when_selected_authentication_is_not_effective(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checks = iter(
        (
            build_provider_check_snapshot(
                ProviderKind.CLAUDE,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="claude_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
            ),
            build_provider_check_snapshot(
                ProviderKind.CLAUDE,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="claude_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.API_KEY,
            ),
        )
    )
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(guided_setup, "collect_provider_check", lambda *_args: next(checks))
    monkeypatch.setattr(
        guided_setup,
        "invoke_provider_identity_action",
        lambda provider, *_args, authentication_method=None, **_kwargs: ProviderIdentitySnapshot(
            provider=provider,
            action="login",
            outcome=ProviderIdentityOutcome.SUCCEEDED,
            service_identity="tester",
            native_home="/tmp/claude-home",
            authentication_method=authentication_method,
            detail="native Claude login completed",
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "claude"],
        input="\nn\nn\n",
    )

    assert result.exit_code == 1, result.output
    assert "Existing Claude subscription login found. Use it? [Y/n]" in result.output
    assert "API key remains effective" in result.output
    assert "environment variable or native credential store may take precedence" in result.output
    assert "claude: check_failed" in result.output


def test_guided_setup_does_not_fall_back_after_selected_authentication_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        guided_setup,
        "collect_provider_check",
        lambda *_args: build_provider_check_snapshot(
            ProviderKind.CODEX,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail="codex_available",
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
        ),
    )
    monkeypatch.setattr(
        guided_setup,
        "invoke_provider_identity_action",
        lambda provider, *_args, authentication_method=None, **_kwargs: ProviderIdentitySnapshot(
            provider=provider,
            action="login",
            outcome=ProviderIdentityOutcome.FAILED,
            service_identity="tester",
            native_home="/tmp/codex-home",
            authentication_method=authentication_method,
            detail="native Codex login failed",
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "codex"],
        input="api-key\ncodex-api-secret\nn\n",
    )

    assert result.exit_code == 1, result.output
    assert "Codex authentication: native Codex login failed" in result.output
    assert "codex: authentication_failed" in result.output
    assert "codex-api-secret" not in result.output
