from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import sysconfig
import tarfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

REQUIRED_PACKAGE_MEMBERS = (
    "autoclaw/config.py",
    "autoclaw/main.py",
    "autoclaw/definitions/seeds/roles/planning_lead.yaml",
    "autoclaw/platform/managed_services/resources/systemd/autoclaw.service",
    "autoclaw/runtime/prompt/assets/instructions/shared/authority.md",
    "autoclaw/runtime/prompt/assets/instructions/families/worker.md",
    "autoclaw/interfaces/web_console/assets/index.html",
    "autoclaw/interfaces/web_console/assets/site.webmanifest",
)
FORBIDDEN_MEMBER_FRAGMENTS = (
    ".env",
    "callback",
    "prompt-request.json",
    "prompt.md",
    "session_key",
)
REMOVED_ROOT_COMMANDS = ("onboard", "configure", "doctor", "openclaw")
COMMAND_TIMEOUT_SECONDS = 60.0
SERVER_START_TIMEOUT_SECONDS = 20.0
SERVER_STOP_TIMEOUT_SECONDS = 10.0
SERVER_REQUEST_TIMEOUT_SECONDS = 1.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify built AutoClaw artifacts and the isolated user-service installer."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()

    dist_dir = args.dist_dir.resolve()
    workspace = args.workspace.resolve()
    repo_root = args.repo_root.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    wheel_path = select_one_artifact(dist_dir, "*.whl")
    sdist_path = select_one_artifact(dist_dir, "*.tar.gz")

    wheel_members = inspect_wheel(wheel_path)
    sdist_members = inspect_sdist(sdist_path)
    dependency_site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    installed_venv = workspace / "installed-venv"
    create_offline_venv(installed_venv, dependency_site_packages)
    install_wheel(installed_venv, wheel_path, workspace)
    installed_smoke = verify_installed_runtime(installed_venv, workspace, repo_root)
    installer_smoke = verify_user_service_installer(
        wheel_path=wheel_path,
        workspace=workspace,
        repo_root=repo_root,
        dependency_site_packages=dependency_site_packages,
    )

    print(
        json.dumps(
            {
                "ok": True,
                "wheel": artifact_result(wheel_path, wheel_members),
                "sdist": artifact_result(sdist_path, sdist_members),
                "installed": installed_smoke,
                "installer": installer_smoke,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def select_one_artifact(dist_dir: Path, pattern: str) -> Path:
    artifacts = sorted(dist_dir.glob(pattern))
    if len(artifacts) != 1:
        raise AssertionError(
            f"expected exactly one {pattern} artifact in {dist_dir}, found {len(artifacts)}"
        )
    return artifacts[0].resolve()


def inspect_wheel(wheel_path: Path) -> tuple[str, ...]:
    with zipfile.ZipFile(wheel_path) as archive:
        members = tuple(sorted(archive.namelist()))
    verify_package_members(members)
    verify_console_assets(members)
    verify_forbidden_members(members)
    return members


def inspect_sdist(sdist_path: Path) -> tuple[str, ...]:
    with tarfile.open(sdist_path, mode="r:gz") as archive:
        raw_members = tuple(sorted(member.name for member in archive.getmembers()))
    members = tuple(remove_sdist_root(member) for member in raw_members)
    required = (*REQUIRED_PACKAGE_MEMBERS, "LICENSE", "README.md", "pyproject.toml")
    verify_required_suffixes(members, required)
    verify_console_assets(members)
    verify_forbidden_members(members)
    return raw_members


def verify_package_members(members: tuple[str, ...]) -> None:
    verify_required_suffixes(members, REQUIRED_PACKAGE_MEMBERS)
    if any("apps/api/src/" in member for member in members):
        raise AssertionError("wheel retained a source-tree package prefix")


def verify_required_suffixes(members: tuple[str, ...], required: tuple[str, ...]) -> None:
    missing = [
        suffix for suffix in required if not any(member.endswith(suffix) for member in members)
    ]
    if missing:
        raise AssertionError(f"distribution is missing required members: {missing}")


def verify_console_assets(members: tuple[str, ...]) -> None:
    asset_members = [
        member for member in members if "autoclaw/interfaces/web_console/assets/" in member
    ]
    for suffix in (".css", ".js"):
        if not any(member.endswith(suffix) for member in asset_members):
            raise AssertionError(f"distribution has no packaged console {suffix} asset")


def verify_forbidden_members(members: tuple[str, ...]) -> None:
    for member in members:
        normalized = member.casefold().replace("-", "_")
        if any(fragment in normalized for fragment in FORBIDDEN_MEMBER_FRAGMENTS):
            raise AssertionError(f"distribution retained forbidden member: {member}")
        parts = PurePosixPath(member).parts
        if "__pycache__" in parts or member.endswith((".pyc", ".pyo")):
            raise AssertionError(f"distribution retained Python cache state: {member}")


def remove_sdist_root(member: str) -> str:
    parts = PurePosixPath(member).parts
    return PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else member


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
    child_site_packages.joinpath("autoclaw-oracle-dependencies.pth").write_text(
        f"{dependency_site_packages}\n",
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


def verify_installed_runtime(
    venv_path: Path, workspace: Path, repo_root: Path
) -> dict[str, object]:
    home = workspace / "installed-home"
    config_path = home / "config" / "autoclaw" / "config.toml"
    data_dir = home / "data" / "autoclaw"
    non_repo_cwd = workspace / "installed-cwd"
    non_repo_cwd.mkdir(parents=True, exist_ok=True)
    venv_path.joinpath(".env").write_text("AUTOCLAW_POSTGRES_SCHEMA=poisoned\n", encoding="utf-8")
    non_repo_cwd.joinpath(".env").write_text(
        "AUTOCLAW_POSTGRES_SCHEMA=also_poisoned\n",
        encoding="utf-8",
    )
    port = available_loopback_port()
    env = isolated_environment(home)
    executable = venv_executable(venv_path, "autoclaw")

    help_result = run_checked((str(executable), "--help"), cwd=non_repo_cwd, env=env)
    for command in REMOVED_ROOT_COMMANDS:
        if f"  {command}\n" in help_result.stdout:
            raise AssertionError(f"installed CLI retained removed root command: {command}")
    run_checked(
        (
            str(executable),
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
            "--port",
            str(port),
            "--json",
        ),
        cwd=non_repo_cwd,
        env=env,
    )
    run_checked(
        (str(executable), "setup", "--config", str(config_path), "--json"),
        cwd=non_repo_cwd,
        env=env,
    )
    config_payload = run_json_command(
        executable,
        ("config", "show", "--config", str(config_path), "--json"),
        cwd=non_repo_cwd,
        env=env,
    )
    if config_payload["database"]["postgres_schema"] != "autoclaw":
        raise AssertionError("installed settings loaded an implicit .env file")
    run_checked((str(executable), "providers", "list", "--json"), cwd=non_repo_cwd, env=env)
    rendered_unit = run_checked(
        (str(executable), "service", "render", "--config", str(config_path)),
        cwd=non_repo_cwd,
        env=env,
    ).stdout
    if str(venv_python(venv_path)) not in rendered_unit:
        raise AssertionError("installed service template did not use the installed interpreter")

    runtime_result = run_installed_lifespan_smoke(
        venv_path=venv_path,
        cwd=non_repo_cwd,
        env={**env, "AUTOCLAW_CONFIG": str(config_path)},
        repo_root=repo_root,
    )
    server_result = run_installed_server_smoke(
        executable=executable,
        config_path=config_path,
        port=port,
        cwd=non_repo_cwd,
        env=env,
    )
    database_result = verify_installed_database_commands(
        executable=executable,
        config_path=config_path,
        cwd=non_repo_cwd,
        env=env,
    )
    provider_result = verify_installed_provider_configuration(
        executable=executable,
        config_path=config_path,
        cwd=non_repo_cwd,
        env=env,
    )
    definition_result = verify_installed_definition_import(
        executable=executable,
        venv_path=venv_path,
        config_path=config_path,
        cwd=non_repo_cwd,
        env=env,
    )
    task_result = verify_installed_task_start(
        executable=executable,
        config_path=config_path,
        cwd=non_repo_cwd,
        env=env,
    )
    return {
        "config_path": str(config_path),
        "data_dir": str(data_dir),
        "package_path": runtime_result.stdout.strip(),
        "server": server_result,
        "database": database_result,
        "providers": provider_result,
        "definition_import": definition_result,
        "task_start": task_result,
    }


def run_installed_lifespan_smoke(
    *,
    venv_path: Path,
    cwd: Path,
    env: dict[str, str],
    repo_root: Path,
) -> subprocess.CompletedProcess[str]:
    script = """
import asyncio
import os
from pathlib import Path

import autoclaw
from autoclaw.config import load_settings
from autoclaw.definitions.seeds import get_packaged_seed_definitions_root
from autoclaw.interfaces.web_console import get_packaged_web_console_assets_root
from autoclaw.main import create_app
from autoclaw.platform.managed_services.resources import get_systemd_service_template
from autoclaw.runtime.prompt import InstructionAsset, load_instruction_asset

package_path = Path(autoclaw.__file__).resolve()
venv_path = Path(os.environ["AUTOCLAW_ORACLE_VENV"]).resolve()
repo_root = Path(os.environ["AUTOCLAW_ORACLE_REPO_ROOT"]).resolve()
assert package_path.is_relative_to(venv_path)
assert not package_path.is_relative_to(repo_root)
assert get_packaged_seed_definitions_root().joinpath("roles", "planning_lead.yaml").is_file()
assert get_systemd_service_template().is_file()
assert get_packaged_web_console_assets_root().joinpath("index.html").is_file()
assert load_instruction_asset(InstructionAsset.AUTHORITY).strip()
assert load_settings().postgres_schema == "autoclaw"

async def smoke() -> None:
    app = create_app(should_enable_mcp_mounts=False)
    async with app.router.lifespan_context(app):
        assert app.title == "AutoClaw API"

asyncio.run(smoke())
print(package_path)
"""
    return run_checked(
        (str(venv_python(venv_path)), "-c", script),
        cwd=cwd,
        env={
            **env,
            "AUTOCLAW_ORACLE_REPO_ROOT": str(repo_root),
            "AUTOCLAW_ORACLE_VENV": str(venv_path),
        },
    )


def run_installed_server_smoke(
    *,
    executable: Path,
    config_path: Path,
    port: int,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    log_path = cwd / "installed-serve.log"
    process_environment = merged_environment(env)
    failure: Exception | None = None
    health_payloads: dict[str, dict[str, object]] = {}

    with log_path.open("w+", encoding="utf-8") as server_log:
        process = subprocess.Popen(
            (str(executable), "serve", "--config", str(config_path)),
            cwd=cwd,
            env=process_environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            health_payloads = wait_for_server_health(process, port=port)
        except Exception as exc:
            failure = exc
        finally:
            return_code = stop_process(process)
            server_log.flush()
            server_log.seek(0)
            output = server_log.read()

    if failure is not None:
        raise RuntimeError(
            f"installed `autoclaw serve` did not become healthy\nserver output:\n{output[-4000:]}"
        ) from failure
    accepted_shutdown_codes = {0, -signal.SIGTERM}
    if return_code not in accepted_shutdown_codes:
        raise RuntimeError(
            f"installed `autoclaw serve` exited with {return_code} after shutdown\n"
            f"server output:\n{output[-4000:]}"
        )
    return {
        "host": "127.0.0.1",
        "port": port,
        "health": health_payloads["healthz"],
        "readiness": health_payloads["readyz"],
        "shutdown_return_code": return_code,
    }


def wait_for_server_health(
    process: subprocess.Popen[str],
    *,
    port: int,
) -> dict[str, dict[str, object]]:
    deadline = time.monotonic() + SERVER_START_TIMEOUT_SECONDS
    last_error = "server did not accept a request"
    endpoints = {"healthz": "ok", "readyz": "ready"}

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited before health checks: {process.returncode}")
        payloads: dict[str, dict[str, object]] = {}
        try:
            for endpoint, expected_status in endpoints.items():
                payload = read_loopback_json(f"http://127.0.0.1:{port}/{endpoint}")
                if payload.get("status") != expected_status:
                    raise ValueError(f"unexpected {endpoint} payload: {payload}")
                payloads[endpoint] = payload
        except (OSError, URLError, ValueError) as exc:
            last_error = str(exc)
            time.sleep(0.1)
            continue
        return payloads

    raise TimeoutError(
        f"server health checks exceeded {SERVER_START_TIMEOUT_SECONDS:.0f}s: {last_error}"
    )


def read_loopback_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=SERVER_REQUEST_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise ValueError(f"{url} returned HTTP {response.status}")
        payload: Any = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{url} returned a non-object JSON payload")
    return payload


def stop_process(process: subprocess.Popen[str]) -> int:
    if process.poll() is None:
        process.terminate()
    try:
        return process.wait(timeout=SERVER_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=SERVER_STOP_TIMEOUT_SECONDS)


def verify_installed_database_commands(
    *,
    executable: Path,
    config_path: Path,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    upgrade = run_json_command(
        executable,
        ("db", "upgrade", "--config", str(config_path), "--json"),
        cwd=cwd,
        env=env,
    )
    reset = run_json_command(
        executable,
        ("db", "reset", "--config", str(config_path), "--json"),
        cwd=cwd,
        env=env,
    )
    if upgrade.get("ok") is not True or reset.get("ok") is not True:
        raise AssertionError("installed database commands did not report success")
    if reset.get("database_backend") != "sqlite":
        raise AssertionError(f"installed database reset used an unexpected backend: {reset}")
    return {"upgrade": upgrade, "reset": reset}


def verify_installed_provider_configuration(
    *,
    executable: Path,
    config_path: Path,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    codex = run_json_command(
        executable,
        ("providers", "configure", "codex", "--config", str(config_path), "--json"),
        cwd=cwd,
        env=env,
    )
    openclaw = run_json_command(
        executable,
        (
            "providers",
            "configure",
            "openclaw",
            "--config",
            str(config_path),
            "--gateway-url",
            "ws://127.0.0.1:9",
            "--gateway-profile",
            "installed-wheel-oracle",
            "--json",
        ),
        cwd=cwd,
        env=env,
    )
    selected = run_json_command(
        executable,
        ("providers", "set-default", "openclaw", "--config", str(config_path), "--json"),
        cwd=cwd,
        env=env,
    )
    status = run_json_command(
        executable,
        ("providers", "status", "openclaw", "--config", str(config_path), "--json"),
        cwd=cwd,
        env=env,
    )
    if codex.get("default_provider") != "codex":
        raise AssertionError(f"first installed provider was not selected by default: {codex}")
    if openclaw.get("default_provider") != "codex":
        raise AssertionError(
            f"second installed provider replaced the default implicitly: {openclaw}"
        )
    if (
        selected.get("default_provider") != "openclaw"
        or selected.get("default_changed") is not True
    ):
        raise AssertionError(f"installed provider default selection failed: {selected}")
    statuses = status.get("providers")
    if not isinstance(statuses, list) or len(statuses) != 1:
        raise AssertionError(f"installed provider status returned an unexpected shape: {status}")
    openclaw_status = statuses[0]
    if not isinstance(openclaw_status, dict):
        raise AssertionError(f"installed provider status returned a non-object: {status}")
    if (
        openclaw_status.get("configured") is not True
        or openclaw_status.get("is_default") is not True
    ):
        raise AssertionError(f"installed OpenClaw configuration was not persisted: {status}")
    return {
        "configured": [codex, openclaw],
        "selected_default": selected,
        "status": status,
        "omitted_external_actions": [
            "providers check: requires a real provider endpoint",
            "providers login: may mutate a native provider account",
            "providers logout: may mutate a native provider account",
        ],
    }


def verify_installed_definition_import(
    *,
    executable: Path,
    venv_path: Path,
    config_path: Path,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    source_path = Path(
        run_checked(
            (
                str(venv_python(venv_path)),
                "-c",
                (
                    "from autoclaw.definitions.seeds import "
                    "get_packaged_seed_definitions_root; "
                    "print(get_packaged_seed_definitions_root() / "
                    "'roles' / 'planning_lead.yaml')"
                ),
            ),
            cwd=cwd,
            env=env,
        ).stdout.strip()
    ).resolve()
    if not source_path.is_file() or not source_path.is_relative_to(venv_path):
        raise AssertionError(
            f"definition import source was not installed package data: {source_path}"
        )

    import_path = cwd / "installed_oracle_role.yaml"
    source_text = source_path.read_text(encoding="utf-8")
    imported_text = source_text.replace(
        "id: planning_lead\n",
        "id: installed_oracle_planning_lead\n",
        1,
    )
    if imported_text == source_text:
        raise AssertionError("installed role seed no longer has the expected identifier")
    import_path.write_text(imported_text, encoding="utf-8")
    payload = run_json_command(
        executable,
        (
            "definitions",
            "import",
            "--config",
            str(config_path),
            "--file",
            str(import_path),
            "--json",
        ),
        cwd=cwd,
        env=env,
    )
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise AssertionError(f"installed definition import returned an unexpected shape: {payload}")
    result = results[0]
    if not isinstance(result, dict):
        raise AssertionError(f"installed definition import returned a non-object: {payload}")
    if result.get("status") != "imported" or result.get("key") != "installed_oracle_planning_lead":
        raise AssertionError(
            f"installed definition import did not create the oracle role: {payload}"
        )
    return payload


def verify_installed_task_start(
    *,
    executable: Path,
    config_path: Path,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    task_compose_path = cwd / "installed-oracle-task.yaml"
    task_compose_path.write_text(
        """task:
    key: installed-wheel-oracle
    title: Installed wheel oracle
    summary: Prove that the installed task-compose command commits a real task.
    instruction: Keep this isolated launch as packaging verification only.
workflow:
    key: planning-only
""",
        encoding="utf-8",
    )
    payload = run_json_command(
        executable,
        (
            "task-compose",
            "start",
            "--config",
            str(config_path),
            "--file",
            str(task_compose_path),
            "--json",
        ),
        cwd=cwd,
        env=env,
    )
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.startswith("task_installed-wheel-oracle_"):
        raise AssertionError(f"installed task start returned an unexpected task id: {payload}")
    if payload.get("flow_status") != "running":
        raise AssertionError(f"installed task start did not commit a running flow: {payload}")
    return payload


def verify_user_service_installer(
    *,
    wheel_path: Path,
    workspace: Path,
    repo_root: Path,
    dependency_site_packages: Path,
) -> dict[str, object]:
    install_root = workspace / "installer"
    home = install_root / "home"
    config_home = install_root / "config"
    data_home = install_root / "data"
    state_home = install_root / "state"
    venv_path = install_root / "venv"
    unit_dir = config_home / "systemd" / "user"
    config_path = config_home / "autoclaw" / "config.toml"
    env_file = config_home / "autoclaw" / "autoclaw.env"
    systemctl_log = install_root / "systemctl.log"
    systemctl_state = install_root / "systemctl.state"
    fake_systemctl = install_root / "systemctl"
    install_root.mkdir(parents=True, exist_ok=True)
    create_offline_venv(venv_path, dependency_site_packages)
    write_fake_systemctl(fake_systemctl)
    port = available_loopback_port()
    env = isolated_environment(home)
    env.update(
        {
            "AUTOCLAW_CONFIG": str(config_path),
            "AUTOCLAW_DATA_DIR": str(data_home / "autoclaw"),
            "AUTOCLAW_PYTHON_BIN": sys.executable,
            "AUTOCLAW_SYSTEMCTL_BIN": str(fake_systemctl),
            "AUTOCLAW_SYSTEMCTL_LOG": str(systemctl_log),
            "AUTOCLAW_SYSTEMCTL_STATE": str(systemctl_state),
            "AUTOCLAW_VENV_DIR": str(venv_path),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_IGNORE_INSTALLED": "1",
            "PIP_NO_INDEX": "1",
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_DATA_HOME": str(data_home),
            "XDG_STATE_HOME": str(state_home),
        }
    )
    installer = repo_root / "scripts" / "install-systemd-user.sh"
    run_checked(
        (
            "bash",
            str(installer),
            "--wheel",
            str(wheel_path),
            "--no-deps",
            "--port",
            str(port),
            "--no-start",
        ),
        cwd=install_root,
        env=env,
    )

    unit_path = unit_dir / "autoclaw.service"
    for generated_path in (config_path, data_home / "autoclaw", env_file, unit_path):
        if not generated_path.exists() or not generated_path.resolve().is_relative_to(install_root):
            raise AssertionError(f"installer wrote outside its isolated tree: {generated_path}")
    unit_text = unit_path.read_text(encoding="utf-8")
    if str(venv_python(venv_path)) not in unit_text:
        raise AssertionError("installed unit does not use the dedicated virtual environment")
    systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()
    if systemctl_calls != ["--user daemon-reload", "--user enable autoclaw.service"]:
        raise AssertionError(f"unexpected install systemctl calls: {systemctl_calls}")

    installed_executable = venv_executable(venv_path, "autoclaw")
    lifecycle_payloads = {
        verb: run_json_command(
            installed_executable,
            ("service", verb, "--json"),
            cwd=install_root,
            env=env,
        )
        for verb in ("start", "status", "restart", "stop")
    }
    if any(payload.get("manager") != "systemd-user" for payload in lifecycle_payloads.values()):
        raise AssertionError(
            f"installed service lifecycle returned unexpected data: {lifecycle_payloads}"
        )
    for verb in ("start", "status", "restart"):
        if (
            lifecycle_payloads[verb].get("running") is not True
            or lifecycle_payloads[verb].get("healthy") is not None
        ):
            raise AssertionError(
                f"installed service {verb} did not report the active fake service: "
                f"{lifecycle_payloads[verb]}"
            )
    if (
        lifecycle_payloads["stop"].get("running") is not False
        or lifecycle_payloads["stop"].get("healthy") is not None
    ):
        raise AssertionError(
            "installed service stop did not report the inactive fake service: "
            f"{lifecycle_payloads['stop']}"
        )

    run_checked(
        (
            str(installed_executable),
            "service",
            "uninstall",
            "--config",
            str(config_path),
            "--unit-dir",
            str(unit_dir),
            "--remove-env-file",
        ),
        cwd=install_root,
        env=env,
    )
    if unit_path.exists() or env_file.exists():
        raise AssertionError("service uninstall left managed files behind")
    final_calls = systemctl_log.read_text(encoding="utf-8").splitlines()
    status_call = (
        "--user show autoclaw.service "
        "--property=LoadState,UnitFileState,ActiveState,SubState,FragmentPath"
    )
    expected_calls = [
        "--user daemon-reload",
        "--user enable autoclaw.service",
        "--user start autoclaw.service",
        status_call,
        status_call,
        "--user restart autoclaw.service",
        status_call,
        "--user stop autoclaw.service",
        status_call,
        "--user disable --now autoclaw.service",
        "--user daemon-reload",
    ]
    if final_calls != expected_calls:
        raise AssertionError(f"unexpected service lifecycle systemctl calls: {final_calls}")
    return {
        "config_path": str(config_path),
        "lifecycle": lifecycle_payloads,
        "systemctl_calls": final_calls,
        "unit_removed": True,
    }


def write_fake_systemctl(path: Path) -> None:
    path.write_text(
        """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$AUTOCLAW_SYSTEMCTL_LOG"
case "${2:-}" in
  start|restart)
    printf '%s\n' active > "$AUTOCLAW_SYSTEMCTL_STATE"
    ;;
  stop|disable)
    printf '%s\n' inactive > "$AUTOCLAW_SYSTEMCTL_STATE"
    ;;
esac
if [ "${2:-}" = "show" ]; then
  state=inactive
  if [ -f "$AUTOCLAW_SYSTEMCTL_STATE" ]; then
    state=$(cat "$AUTOCLAW_SYSTEMCTL_STATE")
  fi
  if [ "$state" = active ]; then
    sub_state=running
  else
    sub_state=dead
  fi
  printf '%s\n' \
    'LoadState=loaded' \
    'UnitFileState=enabled' \
    "ActiveState=$state" \
    "SubState=$sub_state" \
    "FragmentPath=$XDG_CONFIG_HOME/systemd/user/autoclaw.service"
fi
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def isolated_environment(home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONHOME", "PYTHONPATH"} and not key.startswith("AUTOCLAW_")
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
    return environment


def available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_socket:
        test_socket.bind(("127.0.0.1", 0))
        return int(test_socket.getsockname()[1])


def artifact_result(path: Path, members: tuple[str, ...]) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "member_count": len(members),
    }


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


if __name__ == "__main__":
    raise SystemExit(main())
