from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .artifacts import EXPECTED_DISTRIBUTION_VERSION, LEGACY_COMMAND_NOTICE
from .legacy_state import (
    LegacyStateOracle,
    assert_legacy_state_unchanged,
    create_legacy_state_oracle,
)
from .processes import (
    available_loopback_port,
    isolated_environment,
    run_checked,
    run_json_command,
    venv_executable,
    venv_python,
)
from .server import (
    run_installed_lifespan_smoke,
    run_installed_server_smoke,
    verify_installed_console,
)
from .task import verify_installed_task_start

REMOVED_ROOT_COMMANDS = ("onboard", "configure", "doctor", "openclaw")


@dataclass(frozen=True)
class RuntimeProbeContext:
    venv_path: Path
    repo_root: Path
    config_path: Path
    data_dir: Path
    cwd: Path
    port: int
    env: dict[str, str]
    executable: Path


def verify_installed_runtime(
    venv_path: Path,
    workspace: Path,
    repo_root: Path,
) -> dict[str, object]:
    context, legacy_state = prepare_runtime_probe(
        venv_path=venv_path,
        workspace=workspace,
        repo_root=repo_root,
    )
    configure_installed_runtime(context)
    results = verify_installed_runtime_surfaces(context)
    assert_legacy_state_unchanged(legacy_state)
    return {
        "config_path": str(context.config_path),
        "data_dir": str(context.data_dir),
        **results,
        "legacy_state_untouched": True,
    }


def prepare_runtime_probe(
    *,
    venv_path: Path,
    workspace: Path,
    repo_root: Path,
) -> tuple[RuntimeProbeContext, LegacyStateOracle]:
    home = workspace / "installed-home"
    cwd = workspace / "installed-cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    venv_path.joinpath(".env").write_text(
        "OMS_POSTGRES_SCHEMA=poisoned\n",
        encoding="utf-8",
    )
    cwd.joinpath(".env").write_text(
        "OMS_POSTGRES_SCHEMA=also_poisoned\n",
        encoding="utf-8",
    )
    context = RuntimeProbeContext(
        venv_path=venv_path,
        repo_root=repo_root,
        config_path=home / "config" / "banksia" / "config.toml",
        data_dir=home / "data" / "banksia",
        cwd=cwd,
        port=available_loopback_port(),
        env=isolated_environment(home),
        executable=venv_executable(venv_path, "oms"),
    )
    if venv_executable(venv_path, "autoclaw").exists():
        raise AssertionError("installed wheel retained the removed legacy executable")
    if not venv_executable(venv_path, "banksia").exists():
        raise AssertionError("installed wheel omitted the Oh My Subagents compatibility executable")
    legacy_version = run_checked(
        (str(venv_executable(venv_path, "banksia")), "--version"),
        cwd=cwd,
        env=context.env,
    )
    if LEGACY_COMMAND_NOTICE not in legacy_version.stderr:
        raise AssertionError("legacy compatibility executable omitted its migration notice")
    assert_installed_import_contract(
        venv_path=context.venv_path,
        cwd=context.cwd,
        env=context.env,
    )
    legacy_state = create_legacy_state_oracle(
        config_home=home / "config",
        data_home=home / "data",
        cache_home=home / "cache",
    )
    return context, legacy_state


def configure_installed_runtime(context: RuntimeProbeContext) -> None:
    help_result = run_checked(
        (str(context.executable), "--help"),
        cwd=context.cwd,
        env=context.env,
    )
    for command in REMOVED_ROOT_COMMANDS:
        if f"  {command}\n" in help_result.stdout:
            raise AssertionError(f"installed CLI retained removed root command: {command}")
    run_checked(
        (
            str(context.executable),
            "init",
            "--config",
            str(context.config_path),
            "--data-dir",
            str(context.data_dir),
            "--port",
            str(context.port),
            "--json",
        ),
        cwd=context.cwd,
        env=context.env,
    )
    run_checked(
        (
            str(context.executable),
            "setup",
            "--config",
            str(context.config_path),
            "--json",
        ),
        cwd=context.cwd,
        env=context.env,
    )
    config_payload = run_json_command(
        context.executable,
        ("config", "show", "--config", str(context.config_path), "--json"),
        cwd=context.cwd,
        env=context.env,
    )
    if config_payload["database"]["postgres_schema"] != "banksia":
        raise AssertionError("installed settings loaded an implicit .env file")
    run_checked(
        (str(context.executable), "providers", "list", "--json"),
        cwd=context.cwd,
        env=context.env,
    )
    rendered_unit = run_checked(
        (
            str(context.executable),
            "service",
            "render",
            "--config",
            str(context.config_path),
        ),
        cwd=context.cwd,
        env=context.env,
    ).stdout
    rendered_interpreter = (
        venv_python(context.venv_path).with_name("pythonw.exe")
        if os.name == "nt"
        else venv_python(context.venv_path)
    )
    if str(rendered_interpreter) not in rendered_unit:
        raise AssertionError("installed service template did not use the installed interpreter")


def verify_installed_runtime_surfaces(
    context: RuntimeProbeContext,
) -> dict[str, object]:
    runtime_result = run_installed_lifespan_smoke(
        venv_path=context.venv_path,
        cwd=context.cwd,
        env={**context.env, "OMS_CONFIG": str(context.config_path)},
        repo_root=context.repo_root,
    )
    server_result = run_installed_server_smoke(
        executable=context.executable,
        config_path=context.config_path,
        port=context.port,
        cwd=context.cwd,
        env=context.env,
        while_running=lambda: verify_installed_console(context.port),
    )
    database_result = verify_installed_database_commands(
        executable=context.executable,
        config_path=context.config_path,
        cwd=context.cwd,
        env=context.env,
    )
    provider_result = verify_installed_provider_configuration(
        executable=context.executable,
        config_path=context.config_path,
        cwd=context.cwd,
        env=context.env,
    )
    workflow_result = verify_installed_workflow_import(
        executable=context.executable,
        venv_path=context.venv_path,
        config_path=context.config_path,
        cwd=context.cwd,
        env=context.env,
    )
    task_result = verify_installed_task_start(
        executable=context.executable,
        config_path=context.config_path,
        port=context.port,
        cwd=context.cwd,
        env=context.env,
    )
    return {
        "package_path": runtime_result.stdout.strip(),
        "server": server_result,
        "database": database_result,
        "providers": provider_result,
        "workflow_import": workflow_result,
        "task_start": task_result,
    }


def assert_installed_import_contract(
    *,
    venv_path: Path,
    cwd: Path,
    env: dict[str, str],
) -> None:
    run_checked(
        (
            str(venv_python(venv_path)),
            "-c",
            (
                "from importlib.util import find_spec; "
                "from importlib.metadata import version; "
                "assert find_spec('autoclaw') is None; "
                "assert find_spec('banksia.interfaces.web_console') is not None; "
                f"assert version('oh-my-subagents') == '{EXPECTED_DISTRIBUTION_VERSION}'"
            ),
        ),
        cwd=cwd,
        env=env,
    )


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
    claude = run_json_command(
        executable,
        ("providers", "configure", "claude", "--config", str(config_path), "--json"),
        cwd=cwd,
        env=env,
    )
    selected = run_json_command(
        executable,
        ("providers", "set-default", "claude", "--config", str(config_path), "--json"),
        cwd=cwd,
        env=env,
    )
    status = run_json_command(
        executable,
        ("providers", "status", "claude", "--config", str(config_path), "--json"),
        cwd=cwd,
        env=env,
    )
    if codex.get("default_provider") != "codex":
        raise AssertionError(f"first installed provider was not selected by default: {codex}")
    if claude.get("default_provider") != "codex":
        raise AssertionError(f"second installed provider replaced the default implicitly: {claude}")
    if selected.get("default_provider") != "claude" or selected.get("default_changed") is not True:
        raise AssertionError(f"installed provider default selection failed: {selected}")
    statuses = status.get("providers")
    if not isinstance(statuses, list) or len(statuses) != 1:
        raise AssertionError(f"installed provider status returned an unexpected shape: {status}")
    claude_status = statuses[0]
    if not isinstance(claude_status, dict):
        raise AssertionError(f"installed provider status returned a non-object: {status}")
    if claude_status.get("configured") is not True or claude_status.get("is_default") is not True:
        raise AssertionError(f"installed Claude configuration was not persisted: {status}")
    return {
        "configured": [codex, claude],
        "selected_default": selected,
        "status": status,
        "omitted_external_actions": [
            "providers check: requires a real provider endpoint",
            "providers login: may mutate a native provider account",
            "providers logout: may mutate a native provider account",
        ],
    }


def verify_installed_workflow_import(
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
                    "from importlib.resources import files; "
                    "print(files('banksia.workflows.resources.starter_workflows') / "
                    "'production-feature-delivery.yaml')"
                ),
            ),
            cwd=cwd,
            env=env,
        ).stdout.strip()
    ).resolve()
    if not source_path.is_file() or not source_path.is_relative_to(venv_path):
        raise AssertionError(
            f"Workflow import source was not installed package data: {source_path}"
        )

    import_path = cwd / "installed_oracle_workflow.yaml"
    source_text = source_path.read_text(encoding="utf-8")
    imported_text = source_text.replace(
        "id: production-feature-delivery\n",
        "id: installed-oracle-production-feature-delivery\n",
        1,
    )
    if imported_text == source_text:
        raise AssertionError("installed Starter Workflow no longer has the expected identifier")
    import_path.write_text(imported_text, encoding="utf-8")
    payload = run_json_command(
        executable,
        (
            "workflow",
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
    draft = payload.get("draft")
    if not isinstance(draft, dict) or draft.get("workflow_id") != (
        "installed-oracle-production-feature-delivery"
    ):
        raise AssertionError(f"installed Workflow import returned an unexpected shape: {payload}")
    return payload
