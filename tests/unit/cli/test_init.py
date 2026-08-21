from __future__ import annotations

import json
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest
from click.testing import CliRunner

import oh_my_subagents.interfaces.cli as cli
from oh_my_subagents.config import CONTROLLER_WORKSPACE_ENV_VAR, DEFAULT_LOG_LEVEL
from oh_my_subagents.interfaces.cli.main import build_parser
from oh_my_subagents.persistence.session import dispose_db_engine
from oh_my_subagents.workflows.bootstrap import STARTER_WORKFLOW_FILENAMES

from .cli_test_support import assert_seeded_registry_is_bootstrapped, build_cli_init_args


@pytest.mark.asyncio
async def test_init_writes_canonical_config_and_db_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"

    try:
        result = await cli.cmd_init(build_cli_init_args(config_path, data_dir))
    finally:
        await dispose_db_engine()

    assert result == 0
    assert config_path.exists()
    assert data_dir.joinpath("oms.persistence").exists()

    config_text = config_path.read_text(encoding="utf-8")
    config_payload = tomllib.loads(config_text)
    assert f'level = "{DEFAULT_LOG_LEVEL}"' in config_text
    assert "security" not in config_payload
    assert "definitions_root" not in config_text
    assert "[app]" not in config_text
    assert "workspace" not in config_payload["paths"]
    assert config_payload["database"]["echo"] is False
    assert "codex" not in config_payload
    assert "claude" not in config_payload
    assert "openclaw" not in config_payload
    assert "runtime" not in config_payload
    assert_seeded_registry_is_bootstrapped(data_dir / "oms.persistence")
    assert '"ok": true' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_init_keeps_sql_echo_quiet_when_legacy_debug_env_is_set(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    monkeypatch.setenv("OMS_DEBUG", "true")

    try:
        result = await cli.cmd_init(build_cli_init_args(config_path, data_dir))
    finally:
        await dispose_db_engine()

    assert result == 0
    assert "sqlalchemy.engine.Engine" not in capsys.readouterr().out


def test_noninteractive_init_records_and_reads_effective_default_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    configured_workspace = tmp_path / "configured-workspace"
    environment_workspace = tmp_path / "environment-workspace"
    configured_workspace.mkdir()
    environment_workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    parser = build_parser()
    environment = {CONTROLLER_WORKSPACE_ENV_VAR: str(environment_workspace)}

    initialized = runner.invoke(
        parser,
        [
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
            "--workspace",
            configured_workspace.name,
            "--skip-db-upgrade",
            "--non-interactive",
            "--json",
        ],
        env=environment,
    )
    shown = runner.invoke(
        parser,
        ["config", "show", "--config", str(config_path), "--json"],
        env=environment,
    )
    status = runner.invoke(
        parser,
        ["status", "--config", str(config_path), "--json"],
        env=environment,
    )

    assert initialized.exit_code == 0, initialized.output
    assert shown.exit_code == 0, shown.output
    assert status.exit_code == 0, status.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["paths"]["workspace"] == str(configured_workspace.resolve())
    assert json.loads(shown.output)["paths"]["workspace"] == str(environment_workspace.resolve())
    assert json.loads(status.output)["config"]["workspace"] == str(environment_workspace.resolve())


def test_noninteractive_force_preserves_then_replaces_default_workspace(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    preserved_workspace = tmp_path / "preserved-workspace"
    replacement_workspace = tmp_path / "replacement-workspace"
    preserved_workspace.mkdir()
    replacement_workspace.mkdir()
    config_path.write_text(
        (
            f"[paths]\ndata_dir = {json.dumps(str(data_dir))}\n"
            f"workspace = {json.dumps(str(preserved_workspace))}\n"
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    parser = build_parser()
    base_arguments = [
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--force",
        "--skip-db-upgrade",
        "--non-interactive",
        "--json",
    ]

    preserved = runner.invoke(parser, base_arguments)

    assert preserved.exit_code == 0, preserved.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["paths"]["workspace"] == str(preserved_workspace.resolve())

    replaced = runner.invoke(
        parser,
        [
            *base_arguments,
            "--workspace",
            str(replacement_workspace),
        ],
    )

    assert replaced.exit_code == 0, replaced.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["paths"]["workspace"] == str(replacement_workspace.resolve())


def test_noninteractive_force_rejects_invalid_preserved_workspace_without_rewrite(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    invalid_workspace = tmp_path / "missing-workspace"
    config_path.write_text(
        (
            f"[paths]\ndata_dir = {json.dumps(str(data_dir))}\n"
            f"workspace = {json.dumps(str(invalid_workspace))}\n"
        ),
        encoding="utf-8",
    )
    previous_bytes = config_path.read_bytes()
    arguments = [
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--force",
        "--skip-db-upgrade",
        "--non-interactive",
        "--json",
    ]

    result = CliRunner().invoke(build_parser(), arguments)

    assert result.exit_code != 0
    assert "workspace" in result.output.casefold()
    assert config_path.read_bytes() == previous_bytes


def test_init_rejects_invalid_environment_workspace_before_config_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    config_path.write_text('[paths]\ndata_dir = "/previous/data"\n', encoding="utf-8")
    previous_bytes = config_path.read_bytes()
    monkeypatch.setenv(CONTROLLER_WORKSPACE_ENV_VAR, ".")
    arguments = [
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--force",
        "--skip-db-upgrade",
        "--non-interactive",
        "--json",
    ]

    result = cli.main(arguments)

    failure = json.loads(capsys.readouterr().out)
    assert result != 0
    assert CONTROLLER_WORKSPACE_ENV_VAR in failure["error"]["message"]
    assert config_path.read_bytes() == previous_bytes


def test_deleted_configured_workspace_is_configuration_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    unrelated_cwd = tmp_path / "unrelated-cwd"
    workspace.mkdir()
    unrelated_cwd.mkdir()
    initialized = CliRunner().invoke(
        build_parser(),
        [
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
            "--workspace",
            str(workspace),
            "--skip-db-upgrade",
            "--non-interactive",
            "--json",
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    workspace.rmdir()
    monkeypatch.chdir(unrelated_cwd)

    result = cli.main(
        ["config", "show", "--config", str(config_path), "--json"],
    )

    failure = json.loads(capsys.readouterr().out)
    assert result == 1
    assert failure["error"]["kind"] == "configuration_invalid"
    assert "controller_workspace" in failure["error"]["message"]
    assert str(unrelated_cwd) not in failure["error"]["message"]


def test_packaged_starter_workflows_are_available() -> None:
    root = files("oh_my_subagents.workflows.resources.starter_workflows")

    assert tuple(sorted(path.name for path in root.iterdir() if path.name.endswith(".yaml"))) == (
        STARTER_WORKFLOW_FILENAMES
    )
