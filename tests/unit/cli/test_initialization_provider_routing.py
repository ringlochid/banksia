from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from oh_my_subagents.interfaces.cli import root as cli_root
from oh_my_subagents.interfaces.cli.commands import provider_setup as guided_provider_setup
from oh_my_subagents.interfaces.cli.main import build_parser
from oh_my_subagents.interfaces.cli.providers import inspection as provider_inspection
from oh_my_subagents.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
)
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckResult,
    ProviderCheckStatus,
)
from tests.unit.cli.cli_test_support import build_provider_check_snapshot


def test_guided_init_reuses_provider_diagnostic_outside_database_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        provider_inspection,
        "is_provider_integration_available",
        lambda *_args: True,
    )
    diagnostic_calls: list[ProviderKind] = []

    def run_diagnostic(
        _settings: object,
        provider: ProviderKind,
    ) -> ProviderCheckResult:
        diagnostic_calls.append(provider)

        async def read_result() -> ProviderCheckResult:
            return ProviderCheckResult(
                kind=provider,
                status=ProviderCheckStatus.AVAILABLE,
                code="codex_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
            )

        return asyncio.run(read_result())

    monkeypatch.setattr(
        provider_inspection,
        "execute_provider_diagnostic",
        run_diagnostic,
    )

    result = CliRunner().invoke(
        build_parser(),
        [
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
        ],
        input="\ny\ncodex\ny\nn\ncodex\nn\n",
    )

    assert result.exit_code == 0, result.output
    output = result.output.casefold()
    assert "credential" in output
    assert "found" in output
    assert "codex" in output
    assert "ready" in output
    assert "check_failed" not in output
    assert diagnostic_calls == [ProviderKind.CODEX]
    assert "Runtime identity" not in result.output
    assert "Native home" not in result.output
    assert tomllib.loads(config_path.read_text(encoding="utf-8"))["operator"] == {
        "provider": "codex"
    }
    assert result.output.count("Initialization complete") == 1
    assert "Local initialization complete" not in result.output
    assert "Provider setup summary" not in result.output
    assert "Operator setup complete" not in result.output
    assert result.output.count("Next: oms serve") == 1


def test_guided_init_configures_distinct_operator_provider_without_changing_task_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    checked_providers: list[ProviderKind] = []
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    def ready_check(_settings: object, provider: ProviderKind) -> ProviderCheckSnapshot:
        checked_providers.append(provider)
        return build_provider_check_snapshot(
            provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail=f"{provider.value}_available",
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
        )

    monkeypatch.setattr(
        guided_provider_setup,
        "collect_provider_check",
        ready_check,
    )

    result = CliRunner().invoke(
        build_parser(),
        [
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
        ],
        input="\ny\ncodex\ny\nn\nClaude\ny\ny\nn\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["codex"]["enabled"] is True
    assert payload["claude"]["enabled"] is True
    assert payload["runtime"]["default_provider"] == "codex"
    assert payload["operator"] == {"provider": "claude"}
    assert checked_providers == [ProviderKind.CODEX, ProviderKind.CLAUDE]
    assert "Claude is not configured. Configure it now?" in result.output
    assert "Runtime identity" not in result.output
    assert "Initialization complete" in result.output
