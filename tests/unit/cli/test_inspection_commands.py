from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from click.testing import CliRunner

from banksia.config import Settings
from banksia.interfaces.cli.commands import providers as provider_commands
from banksia.interfaces.cli.main import build_parser
from banksia.interfaces.cli.providers import inspection as provider_inspection
from banksia.interfaces.cli.providers.configuration import (
    ProviderConfigurationRequest,
    configure_provider,
)
from banksia.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
)
from banksia.platform.provider_environment import ANTHROPIC_API_KEY, persist_provider_secret
from banksia.providers import ProviderKind
from banksia.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckResult,
    ProviderCheckStatus,
)


def test_bare_and_status_are_passive_with_zero_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    (tmp_path / "banksia.env").write_text(
        'ANTHROPIC_API_KEY="invalid-unclosed-value\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BANKSIA_CONFIG", str(config_path))
    monkeypatch.setattr(
        "banksia.interfaces.cli.providers.identity.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("passive status invoked a provider command"),
    )
    runner = CliRunner()
    parser = build_parser()

    bare = runner.invoke(parser, [])
    status = runner.invoke(parser, ["status", "--config", str(config_path), "--json"])

    assert bare.exit_code == 0
    assert status.exit_code == 0
    assert "Default provider: Not configured" in bare.output
    assert "authentication not_checked" not in bare.output
    assert "Local configuration only" in bare.output
    payload = json.loads(status.output)
    assert payload["default_provider"] is None
    assert all(not provider["configured"] for provider in payload["providers"])
    assert payload["database"]["schema"] == "not_checked"
    assert payload["service"]["status"] == "not_checked"
    assert not config_path.exists()


def test_status_redacts_database_password(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[database]\nurl = "postgresql+asyncpg://operator:secret@localhost/banksia"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        build_parser(),
        ["status", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 0
    assert "secret" not in result.output
    assert json.loads(result.output)["database"]["configured_url"] == (
        "postgresql+asyncpg://operator:***@localhost/banksia"
    )


def test_bare_status_reports_the_managed_service_native_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    expected_home = str(Path.home() / ".codex")
    monkeypatch.setenv("CODEX_HOME", "/tmp/shell-only-codex-home")

    result = CliRunner().invoke(
        build_parser(),
        ["status", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    codex = next(provider for provider in payload["providers"] if provider["kind"] == "codex")
    assert codex["native_home"] == expected_home


def test_provider_list_and_status_are_passive_and_mark_openclaw_experimental(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[openclaw]
enabled = true
gateway_url = "ws://user:secret@127.0.0.1:18789"
gateway_profile = "external"

[runtime]
default_provider = "openclaw"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    previous_bytes = config_path.read_bytes()
    runner = CliRunner()
    parser = build_parser()

    listed = runner.invoke(parser, ["providers", "list", "--json"])
    status = runner.invoke(
        parser,
        ["providers", "status", "openclaw", "--config", str(config_path), "--json"],
    )

    assert listed.exit_code == 0
    assert status.exit_code == 0
    list_payload = json.loads(listed.output)
    status_payload = json.loads(status.output)
    openclaw_definition = next(
        provider for provider in list_payload["providers"] if provider["kind"] == "openclaw"
    )
    assert openclaw_definition["product_status"] == "experimental"
    assert openclaw_definition["setup_owner"] == "shared"
    assert status_payload["providers"][0]["authentication"] == "not_checked"
    assert status_payload["providers"][0]["reachability"] == "not_checked"
    assert "user:secret" not in status.output
    assert config_path.read_bytes() == previous_bytes


def test_managed_integration_availability_requires_the_bundled_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_inspection, "module_is_available", lambda _module: True)

    def missing_cli() -> Path:
        raise FileNotFoundError

    monkeypatch.setattr(provider_inspection, "bundled_codex_path", missing_cli)

    assert provider_inspection.is_provider_integration_available(ProviderKind.CODEX) is False


def test_provider_check_runs_bounded_diagnostic_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    previous_bytes = config_path.read_bytes()
    monkeypatch.setattr(
        "banksia.interfaces.cli.providers.inspection.module_is_available",
        lambda _module: True,
    )
    monkeypatch.setattr(
        "banksia.interfaces.cli.providers.inspection.execute_provider_diagnostic",
        lambda _settings, provider: ProviderCheckResult(
            kind=provider,
            status=ProviderCheckStatus.AVAILABLE,
            code="codex_available",
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["providers", "check", "codex", "--config", str(config_path), "--json"],
    )
    human_result = CliRunner().invoke(
        build_parser(),
        ["providers", "check", "codex", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert human_result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["outcome"] == "ready"
    assert payload["is_ready"] is True
    assert payload["authentication"] == "passed"
    assert payload["authentication_method"] == "subscription"
    assert payload["reachability"] == "not_checked"
    assert "Credential: found" in human_result.output
    assert "Method: Subscription login" in human_result.output
    assert "Reachability: not tested" in human_result.output
    assert "not_checked" not in human_result.output
    assert config_path.read_bytes() == previous_bytes


def test_provider_check_uses_the_managed_service_secret_instead_of_the_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CLAUDE),
    )
    persist_provider_secret(
        tmp_path / "banksia.env",
        key=ANTHROPIC_API_KEY,
        value="stored-api-key",
    )
    monkeypatch.setenv(ANTHROPIC_API_KEY, "shell-api-key")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/shell-only-claude-home")
    observed_keys: list[str | None] = []
    observed_homes: list[str | None] = []

    def inspect_service_environment(
        _settings: Settings,
        provider: ProviderKind,
    ) -> ProviderCheckSnapshot:
        observed_keys.append(os.environ.get(ANTHROPIC_API_KEY))
        observed_homes.append(os.environ.get("CLAUDE_CONFIG_DIR"))
        return ProviderCheckSnapshot(
            kind=provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            service_identity="tester",
            native_home="/tmp/claude",
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=ProviderAuthenticationMethod.API_KEY,
            detail="claude_available",
        )

    monkeypatch.setattr(provider_commands, "collect_provider_check", inspect_service_environment)

    result = CliRunner().invoke(
        build_parser(),
        ["providers", "check", "claude", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 0, result.output
    assert observed_keys == ["stored-api-key"]
    assert observed_homes == [None]
    assert os.environ[ANTHROPIC_API_KEY] == "shell-api-key"
    assert os.environ["CLAUDE_CONFIG_DIR"] == "/tmp/shell-only-claude-home"


def test_provider_check_does_not_call_unverified_authentication_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    monkeypatch.setattr(
        "banksia.interfaces.cli.providers.inspection.module_is_available",
        lambda _module: True,
    )
    monkeypatch.setattr(
        "banksia.interfaces.cli.providers.inspection.execute_provider_diagnostic",
        lambda _settings, provider: ProviderCheckResult(
            kind=provider,
            status=ProviderCheckStatus.AVAILABLE,
            code="codex_available",
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["providers", "check", "codex", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["outcome"] == "local_prerequisites_ready"
    assert payload["is_ready"] is None


def test_provider_status_keeps_passive_diagnostics_out_of_human_output(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["providers", "status", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert "Provider status" in result.output
    assert "Codex" in result.output
    assert "Local configuration only" in result.output
    assert "banksia providers check codex" in result.output
    assert "not_checked" not in result.output


def test_provider_status_reports_the_managed_service_native_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    expected_home = str(Path.home() / ".codex")
    monkeypatch.setenv("CODEX_HOME", "/tmp/shell-only-codex-home")

    result = CliRunner().invoke(
        build_parser(),
        ["providers", "status", "codex", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["providers"][0]["native_home"] == expected_home


def test_provider_check_maps_authentication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    monkeypatch.setattr(
        "banksia.interfaces.cli.providers.inspection.module_is_available",
        lambda _module: True,
    )
    monkeypatch.setattr(
        "banksia.interfaces.cli.providers.inspection.execute_provider_diagnostic",
        lambda _settings, provider: ProviderCheckResult(
            kind=provider,
            status=ProviderCheckStatus.UNAVAILABLE,
            code="codex_authentication_required",
            authentication=ProviderCheckAxisStatus.FAILED,
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["providers", "check", "codex", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["outcome"] == "authentication_failed"
    assert payload["authentication"] == "failed"
    assert payload["reachability"] == "not_checked"


def test_provider_diagnostic_timeout_includes_adapter_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowCleanupAdapter:
        @asynccontextmanager
        async def lifespan(self) -> AsyncIterator[None]:
            try:
                yield
            finally:
                await asyncio.Event().wait()

        async def read_availability(self) -> ProviderCheckResult:
            return ProviderCheckResult(
                kind=ProviderKind.CODEX,
                status=ProviderCheckStatus.AVAILABLE,
                code="codex_available",
            )

    monkeypatch.setattr(
        "banksia.integrations.provider_registry.build_provider_adapter",
        lambda _provider, _settings: SlowCleanupAdapter(),
    )
    monkeypatch.setattr(provider_inspection, "PROVIDER_CHECK_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(TimeoutError):
        provider_inspection.execute_provider_diagnostic(
            Settings(),
            ProviderKind.CODEX,
        )
