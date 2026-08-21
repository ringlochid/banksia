from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import click
import pytest
from pydantic import ValidationError

import oh_my_subagents.interfaces.cli as cli
from oh_my_subagents.config import Settings
from oh_my_subagents.persistence.schema_contract import DatabaseSchemaMismatchError


def test_main_renders_friendly_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main(["definitely-not-a-command"])

    output = capsys.readouterr().out
    assert result == 2
    assert 'Oh My Subagents does not know the command "definitely-not-a-command".' in output
    assert "Try: oms --help" in output
    assert "Traceback" not in output


def test_main_renders_json_parse_errors(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main(["init", "--json", "--definitely-not-an-option"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "unknown_option"
    assert "--definitely-not-an-option" in payload["error"]["message"]


def test_main_hides_traceback_without_debug(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(_args: Sequence[str]) -> NoReturn:
        raise RuntimeError("boom")

    monkeypatch.setattr("oh_my_subagents.interfaces.cli.root.cmd_init", _boom)
    result = cli.main(["init", "--force"])

    output = capsys.readouterr().out
    assert result == 1
    assert "Oh My Subagents command failed" in output
    assert "Reason: boom" in output
    assert "Traceback" not in output


def test_main_directs_schema_mismatch_to_data_preserving_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia.toml"

    def _mismatch(_args: Sequence[str]) -> NoReturn:
        raise DatabaseSchemaMismatchError("attempts missing watchdog replacement state")

    monkeypatch.setattr("oh_my_subagents.interfaces.cli.root.cmd_init", _mismatch)
    result = cli.main(["init", "--force", "--config", str(config_path)])

    output = capsys.readouterr().out
    assert result == 1
    assert "Database upgrade required" in output
    assert shlex.join(("oms", "db", "upgrade", "--config", str(config_path))) in output
    assert "db reset` only if you accept deletion" in output


def test_service_install_directs_schema_mismatch_to_selected_config_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "service-config.toml"

    def mismatch(_args: Sequence[str]) -> NoReturn:
        raise DatabaseSchemaMismatchError("attempts missing watchdog replacement state")

    monkeypatch.setattr(
        "oh_my_subagents.interfaces.cli.service_commands.cmd_service_install",
        mismatch,
    )
    result = cli.main(["service", "install", "--no-start", "--config", str(config_path)])

    output = capsys.readouterr().out
    assert result == 1
    upgrade_command = shlex.join(("oms", "db", "upgrade", "--config", str(config_path)))
    assert upgrade_command in output
    assert output.index(upgrade_command) < output.index("oms db reset")


def test_main_shows_traceback_with_debug(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(_args: Sequence[str]) -> NoReturn:
        raise RuntimeError("boom")

    monkeypatch.setattr("oh_my_subagents.interfaces.cli.root.cmd_init", _boom)
    result = cli.main(["--debug", "init", "--force"])

    output = capsys.readouterr().out
    assert result == 1
    assert "Oh My Subagents command failed" in output
    assert "Traceback" in output


def test_main_accepts_debug_after_a_leaf_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(_args: Sequence[str]) -> NoReturn:
        raise RuntimeError("service boom")

    monkeypatch.setattr("oh_my_subagents.interfaces.cli.service_commands.cmd_service_start", _boom)

    result = cli.main(["service", "start", "--debug"])

    output = capsys.readouterr().out
    assert result == 1
    assert "service boom" in output
    assert "Traceback" in output


def test_main_never_traces_expected_parse_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["service", "start", "--not-an-option", "--debug"])

    output = capsys.readouterr().out
    assert result == 2
    assert 'Oh My Subagents does not recognize option "--not-an-option".' in output
    assert "Traceback" not in output


def test_main_explains_that_cancelled_setup_keeps_completed_steps(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def abort(_args: Sequence[str]) -> NoReturn:
        raise click.Abort()

    monkeypatch.setattr("oh_my_subagents.interfaces.cli.root.cmd_setup", abort)

    result = cli.main(["setup"])

    output = capsys.readouterr()
    assert result == 2
    assert "Setup cancelled. Completed setup steps were kept." in output.err


def test_main_redacts_invalid_configuration_inputs_even_with_debug(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(ValidationError) as captured:
        Settings.model_validate(
            {"claude": {"api_key": "must-not-appear"}},
        )

    def _boom(_args: Sequence[str]) -> NoReturn:
        raise captured.value

    monkeypatch.setattr("oh_my_subagents.interfaces.cli.root.cmd_init", _boom)

    result = cli.main(["init", "--force", "--debug"])

    output = capsys.readouterr().out
    assert result == 1
    assert "Configuration invalid" in output
    assert "claude.api_key" in output
    assert "Extra inputs are not permitted" in output
    assert "must-not-appear" not in output
    assert "input_value" not in output
    assert "Traceback" not in output
