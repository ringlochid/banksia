from __future__ import annotations

import json
from collections.abc import Sequence
from typing import NoReturn

import autoclaw.interfaces.cli as cli
import click
import pytest
from autoclaw.config import Settings
from pydantic import ValidationError


def test_main_renders_friendly_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main(["definitely-not-a-command"])

    output = capsys.readouterr().out
    assert result == 2
    assert 'AutoClaw does not know the command "definitely-not-a-command".' in output
    assert "Try: autoclaw --help" in output
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

    monkeypatch.setattr("autoclaw.interfaces.cli.root.cmd_init", _boom)
    result = cli.main(["init", "--force"])

    output = capsys.readouterr().out
    assert result == 1
    assert "AutoClaw command failed" in output
    assert "Reason: boom" in output
    assert "Traceback" not in output


def test_main_shows_traceback_with_debug(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(_args: Sequence[str]) -> NoReturn:
        raise RuntimeError("boom")

    monkeypatch.setattr("autoclaw.interfaces.cli.root.cmd_init", _boom)
    result = cli.main(["--debug", "init", "--force"])

    output = capsys.readouterr().out
    assert result == 1
    assert "AutoClaw command failed" in output
    assert "Traceback" in output


def test_main_accepts_debug_after_a_leaf_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(_args: Sequence[str]) -> NoReturn:
        raise RuntimeError("service boom")

    monkeypatch.setattr("autoclaw.interfaces.cli.root.cmd_service_start", _boom)

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
    assert 'AutoClaw does not recognize option "--not-an-option".' in output
    assert "Traceback" not in output


def test_main_explains_that_cancelled_setup_keeps_completed_steps(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def abort(_args: Sequence[str]) -> NoReturn:
        raise click.Abort()

    monkeypatch.setattr("autoclaw.interfaces.cli.root.cmd_setup", abort)

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
            {"openclaw": {"gateway_token": "must-not-appear"}},
        )

    def _boom(_args: Sequence[str]) -> NoReturn:
        raise captured.value

    monkeypatch.setattr("autoclaw.interfaces.cli.root.cmd_init", _boom)

    result = cli.main(["init", "--force", "--debug"])

    output = capsys.readouterr().out
    assert result == 1
    assert "Configuration invalid" in output
    assert "openclaw.gateway_token" in output
    assert "Extra inputs are not permitted" in output
    assert "must-not-appear" not in output
    assert "input_value" not in output
    assert "Traceback" not in output
