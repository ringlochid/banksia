from __future__ import annotations

import argparse
import asyncio
import json
import socket
import tomllib
from pathlib import Path

import autoclaw.interfaces.cli as cli
import pytest
from autoclaw.config import DEFAULT_API_PORT, get_settings
from autoclaw.persistence.session import dispose_db_engine
from autoclaw.platform.provider_environment import ProviderEnvironmentError

from .cli_test_support import (
    build_cli_init_args,
    find_available_loopback_port,
    write_systemctl_show_script,
)


def test_service_install_and_status_use_systemd_user_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    unit_dir = tmp_path / "systemd-user"
    env_file = tmp_path / "autoclaw.env"
    systemctl_log = tmp_path / "systemctl.log"
    systemctl_bin = tmp_path / "systemctl"
    write_systemctl_show_script(
        systemctl_bin,
        systemctl_log,
        active_state="active",
        sub_state="running",
    )
    monkeypatch.setenv("AUTOCLAW_SYSTEMCTL_BIN", str(systemctl_bin))

    try:
        asyncio.run(cli.cmd_init(build_cli_init_args(config_path, data_dir)))
        capsys.readouterr()
        install_result = cli.cmd_service_install(
            argparse.Namespace(
                config=str(config_path),
                name="autoclaw",
                unit_dir=str(unit_dir),
                port=19123,
                no_start=True,
            )
        )
        status_result = cli.cmd_service_status(argparse.Namespace(name="autoclaw", json=True))
    finally:
        get_settings.cache_clear()
        asyncio.run(dispose_db_engine())

    assert install_result == 0
    assert status_result == 0
    assert unit_dir.joinpath("autoclaw.service").exists()
    assert env_file.exists()
    config_payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config_payload["server"]["port"] == 19123
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["manager"] == "systemd-user"
    assert payload["installed"] is True
    assert payload["running"] is True
    assert payload["healthy"] is None
    assert "OpenClaw" not in captured.err
    assert "Checking local API bind target" in captured.err
    assert "Running" in captured.err
    assert "daemon-reload" in captured.err
    assert "enable autoclaw.service" in captured.err
    log_lines = systemctl_log.read_text(encoding="utf-8").splitlines()
    assert "daemon-reload" in log_lines[0]
    assert any("enable autoclaw.service" in line for line in log_lines)


def test_service_install_fails_before_unit_write_when_requested_port_is_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    unit_dir = tmp_path / "systemd-user"
    env_file = tmp_path / "autoclaw.env"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy_socket:
        busy_socket.bind(("127.0.0.1", 0))
        busy_socket.listen(1)
        busy_port = busy_socket.getsockname()[1]

        try:
            asyncio.run(cli.cmd_init(build_cli_init_args(config_path, data_dir)))
            capsys.readouterr()
            result = cli.cmd_service_install(
                argparse.Namespace(
                    config=str(config_path),
                    name="autoclaw",
                    unit_dir=str(unit_dir),
                    port=busy_port,
                    no_start=True,
                )
            )
        finally:
            get_settings.cache_clear()
            asyncio.run(dispose_db_engine())

    output = capsys.readouterr().out
    config_payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert result == 1
    assert "Local API bind check failed" in output
    assert config_payload["server"]["port"] == DEFAULT_API_PORT
    assert not unit_dir.joinpath("autoclaw.service").exists()
    assert not env_file.exists()


def test_service_install_rejects_unowned_environment_assignments(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    unit_dir = tmp_path / "systemd-user"
    env_file = tmp_path / "autoclaw.env"
    env_file.write_text("CUSTOM_FLAG=1\n", encoding="utf-8")

    try:
        init_args = build_cli_init_args(config_path, data_dir)
        init_args.port = find_available_loopback_port()
        asyncio.run(cli.cmd_init(init_args))
        with pytest.raises(ProviderEnvironmentError, match="does not support CUSTOM_FLAG"):
            cli.cmd_service_install(
                argparse.Namespace(
                    config=str(config_path),
                    name="autoclaw",
                    unit_dir=str(unit_dir),
                    port=None,
                    no_start=True,
                )
            )
    finally:
        get_settings.cache_clear()
        asyncio.run(dispose_db_engine())

    assert not unit_dir.joinpath("autoclaw.service").exists()


def test_service_install_reconciles_unit_without_overwriting_private_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    unit_dir = tmp_path / "systemd-user"
    env_file = tmp_path / "autoclaw.env"
    systemctl_log = tmp_path / "systemctl-reconcile.log"
    systemctl_bin = tmp_path / "systemctl-reconcile"
    unit_dir.mkdir(parents=True, exist_ok=True)
    env_file.write_text("# Existing provider credentials stay here.\n", encoding="utf-8")
    unit_dir.joinpath("autoclaw.service").write_text("stale unit\n", encoding="utf-8")
    write_systemctl_show_script(
        systemctl_bin,
        systemctl_log,
        active_state="inactive",
        sub_state="dead",
    )
    monkeypatch.setenv("AUTOCLAW_SYSTEMCTL_BIN", str(systemctl_bin))

    try:
        init_args = build_cli_init_args(config_path, data_dir)
        init_args.port = find_available_loopback_port()
        asyncio.run(cli.cmd_init(init_args))
        result = cli.cmd_service_install(
            argparse.Namespace(
                config=str(config_path),
                name="autoclaw",
                unit_dir=str(unit_dir),
                port=None,
                no_start=True,
            )
        )
    finally:
        get_settings.cache_clear()
        asyncio.run(dispose_db_engine())

    assert result == 0
    assert env_file.read_text(encoding="utf-8") == "# Existing provider credentials stay here.\n"
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert "ExecStart=" in unit_dir.joinpath("autoclaw.service").read_text(encoding="utf-8")


def test_service_install_reconciles_a_running_service_without_a_false_port_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    unit_dir = tmp_path / "systemd-user"
    systemctl_log = tmp_path / "systemctl-running.log"
    systemctl_bin = tmp_path / "systemctl-running"
    write_systemctl_show_script(
        systemctl_bin,
        systemctl_log,
        active_state="active",
        sub_state="running",
    )
    monkeypatch.setenv("AUTOCLAW_SYSTEMCTL_BIN", str(systemctl_bin))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy_socket:
        busy_socket.bind(("127.0.0.1", 0))
        busy_socket.listen(1)
        busy_port = int(busy_socket.getsockname()[1])
        try:
            init_args = build_cli_init_args(config_path, data_dir)
            init_args.port = busy_port
            asyncio.run(cli.cmd_init(init_args))
            capsys.readouterr()
            result = cli.cmd_service_install(
                argparse.Namespace(
                    config=str(config_path),
                    name="autoclaw",
                    unit_dir=str(unit_dir),
                    port=None,
                    no_start=True,
                )
            )
        finally:
            get_settings.cache_clear()
            asyncio.run(dispose_db_engine())

    output = capsys.readouterr()
    assert result == 0
    assert "Reusing the bind target owned by the running managed service" in output.err
    assert unit_dir.joinpath("autoclaw.service").exists()


@pytest.mark.asyncio
async def test_service_start_and_status_use_managed_service_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    systemctl_log = tmp_path / "systemctl-start.log"
    systemctl_bin = tmp_path / "systemctl-start"
    write_systemctl_show_script(
        systemctl_bin,
        systemctl_log,
        active_state="active",
        sub_state="running",
    )
    monkeypatch.setenv("AUTOCLAW_SYSTEMCTL_BIN", str(systemctl_bin))

    try:
        await cli.cmd_init(build_cli_init_args(config_path, data_dir))
        capsys.readouterr()
        result = cli.cmd_service_start(argparse.Namespace(name="autoclaw", json=False))
        start_output = capsys.readouterr()
        status_result = cli.cmd_service_status(argparse.Namespace(name="autoclaw", json=True))
    finally:
        get_settings.cache_clear()
        await dispose_db_engine()

    assert result == 0
    assert status_result == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["manager"] == "systemd-user"
    assert status_payload["installed"] is True
    assert status_payload["running"] is True
    assert status_payload["healthy"] is None
    assert "systemctl --user start autoclaw.service" in start_output.err
    log_lines = systemctl_log.read_text(encoding="utf-8").splitlines()
    assert any("start autoclaw.service" in line for line in log_lines)


@pytest.mark.asyncio
async def test_service_stop_and_restart_use_managed_service_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    systemctl_log = tmp_path / "systemctl-stop.log"
    systemctl_bin = tmp_path / "systemctl-stop"
    write_systemctl_show_script(
        systemctl_bin,
        systemctl_log,
        active_state="inactive",
        sub_state="dead",
    )
    monkeypatch.setenv("AUTOCLAW_SYSTEMCTL_BIN", str(systemctl_bin))

    try:
        await cli.cmd_init(build_cli_init_args(config_path, data_dir))
        stop_result = cli.cmd_service_stop(argparse.Namespace(name="autoclaw", json=False))
        restart_result = cli.cmd_service_restart(argparse.Namespace(name="autoclaw", json=False))
    finally:
        get_settings.cache_clear()
        await dispose_db_engine()

    assert stop_result == 0
    assert restart_result == 0
    log_lines = systemctl_log.read_text(encoding="utf-8").splitlines()
    assert any("stop autoclaw.service" in line for line in log_lines)
    assert any("restart autoclaw.service" in line for line in log_lines)


def test_service_start_failure_reports_systemd_reason_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    systemctl_bin = tmp_path / "systemctl-failure"
    systemctl_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "sys.stderr.write('simulated unit failure\\n')",
                "sys.exit(1)",
            ]
        ),
        encoding="utf-8",
    )
    systemctl_bin.chmod(0o755)
    monkeypatch.setenv("AUTOCLAW_SYSTEMCTL_BIN", str(systemctl_bin))

    result = cli.main(["service", "start"])

    output = capsys.readouterr().out
    assert result == 1
    assert "Managed service start failed" in output
    assert "simulated unit failure" in output
    assert "journalctl --user -u autoclaw.service -n 50 --no-pager" in output
    assert "autoclaw service install" in output
    assert "Command '['" not in output
