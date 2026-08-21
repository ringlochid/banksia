from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

COMMAND_TIMEOUT_SECONDS = 60.0


def validate_external_workspace(*, workspace: Path, repo_root: Path) -> None:
    if workspace == repo_root or repo_root in workspace.parents:
        raise AssertionError(
            f"installed-distribution workspace must be outside the repository: {workspace}"
        )


def read_optional_file(path: Path) -> tuple[bool, bytes]:
    if not path.exists():
        return False, b""
    return True, path.read_bytes()


def assert_optional_file_unchanged(
    path: Path,
    *,
    before: tuple[bool, bytes],
) -> None:
    after = read_optional_file(path)
    if after != before:
        raise AssertionError(f"installed-distribution proof changed repository file: {path}")


def create_offline_venv(venv_path: Path, dependency_site_packages: Path) -> None:
    run_checked((sys.executable, "-m", "venv", str(venv_path)), cwd=venv_path.parent)
    child_python = venv_python(venv_path)
    child_site_packages = Path(
        run_checked(
            (
                str(child_python),
                "-c",
                "import sysconfig; print(sysconfig.get_paths()['purelib'])",
            ),
            cwd=venv_path.parent,
        ).stdout.strip()
    )
    child_site_packages.joinpath("oms-oracle-dependencies.pth").write_text(
        f"import site; site.addsitedir({str(dependency_site_packages)!r})\n",
        encoding="utf-8",
    )


def install_wheel(venv_path: Path, wheel_path: Path, cwd: Path) -> None:
    run_checked(
        (
            str(venv_python(venv_path)),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--ignore-installed",
            str(wheel_path),
        ),
        cwd=cwd,
        env={"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INDEX": "1"},
    )


def isolated_environment(home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONHOME", "PYTHONPATH"}
        and not key.startswith(("OMS_", "BANKSIA_", "AUTOCLAW_"))
    }
    environment.update(
        {
            "HOME": str(home),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_STATE_HOME": str(home / "state"),
        }
    )
    if os.name == "nt":
        environment.update(
            {
                "APPDATA": str(home / "config"),
                "LOCALAPPDATA": str(home / "data"),
                "USERPROFILE": str(home),
                "WIN_PD_OVERRIDE_APPDATA": str(home / "config"),
                "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(home / "data"),
            }
        )
    return environment


def available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_socket:
        test_socket.bind(("127.0.0.1", 0))
        return int(test_socket.getsockname()[1])


def venv_python(venv_path: Path) -> Path:
    return venv_executable(venv_path, "python")


def venv_executable(venv_path: Path, name: str) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_path / directory / f"{name}{suffix}"


def run_json_command(
    executable: Path,
    arguments: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    result = run_checked((str(executable), *arguments), cwd=cwd, env=env)
    payload: Any = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise AssertionError(
            f"command returned a non-object JSON payload: {executable} {' '.join(arguments)}"
        )
    return payload


def merged_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    process_environment = os.environ.copy()
    if env is not None:
        process_environment.update(env)
        process_environment.pop("PYTHONHOME", None)
        process_environment.pop("PYTHONPATH", None)
    return process_environment


def run_checked(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=merged_environment(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"command exceeded {COMMAND_TIMEOUT_SECONDS:.0f}s: {' '.join(command)}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result
