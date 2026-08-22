from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tomllib
from importlib import resources
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI

import oh_my_subagents
from oh_my_subagents.interfaces.cli.main import LEGACY_COMMAND_NOTICE, legacy_main, main
from oh_my_subagents.main import app, create_app
from oh_my_subagents.platform.managed_services.resources import get_managed_service_resources_root
from oh_my_subagents.workflows.bootstrap import STARTER_WORKFLOW_FILENAMES
from scripts.testing.installed_distribution.processes import validate_external_workspace
from scripts.testing.installed_distribution.task import (
    INSTALLED_TASK_PROMPT,
    verify_installed_task_view,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src"
OMS_PACKAGE_ROOT = SOURCE_ROOT / "oh_my_subagents"


def _route_paths(routes: list[Any]) -> set[str]:
    return {str(route.path) for route in routes if hasattr(route, "path")}


def _load_setuptools_configuration() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    tool_config = cast(dict[str, Any], pyproject["tool"])
    return cast(dict[str, Any], tool_config["setuptools"])


def _load_project_configuration() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    return cast(dict[str, Any], pyproject["project"])


def test_oms_package_uses_src_modules_only() -> None:
    packaged_workflows = importlib.import_module("oh_my_subagents.workflows")
    packaged_workflow_resources = importlib.import_module(
        "oh_my_subagents.workflows.resources.starter_workflows"
    )
    packaged_http = importlib.import_module("oh_my_subagents.interfaces.http")
    packaged_cli_owner = importlib.import_module("oh_my_subagents.interfaces.cli")
    packaged_mcp_owner = importlib.import_module("oh_my_subagents.interfaces.mcp")
    packaged_web_console = importlib.import_module("oh_my_subagents.interfaces.web_console")
    packaged_main_module = importlib.import_module("oh_my_subagents.main")
    packaged_persistence = importlib.import_module("oh_my_subagents.persistence")
    packaged_runtime_contracts = importlib.import_module("oh_my_subagents.runtime.contracts")

    assert oh_my_subagents.__file__ is not None
    assert Path(oh_my_subagents.__file__).resolve() == OMS_PACKAGE_ROOT / "__init__.py"
    assert importlib.util.find_spec("banksia") is not None
    assert importlib.util.find_spec("banksia.persistence") is None
    assert packaged_workflows.__file__ is not None
    assert (
        Path(packaged_workflows.__file__).resolve()
        == OMS_PACKAGE_ROOT / "workflows" / "__init__.py"
    )
    assert packaged_workflow_resources.__file__ is not None
    assert (
        Path(packaged_workflow_resources.__file__).resolve()
        == OMS_PACKAGE_ROOT / "workflows" / "resources" / "starter_workflows" / "__init__.py"
    )
    assert packaged_cli_owner.__file__ is not None
    assert (
        Path(packaged_cli_owner.__file__).resolve()
        == OMS_PACKAGE_ROOT / "interfaces" / "cli" / "__init__.py"
    )
    assert packaged_http.__file__ is not None
    assert (
        Path(packaged_http.__file__).resolve()
        == OMS_PACKAGE_ROOT / "interfaces" / "http" / "__init__.py"
    )
    assert packaged_mcp_owner.__file__ is not None
    assert (
        Path(packaged_mcp_owner.__file__).resolve()
        == OMS_PACKAGE_ROOT / "interfaces" / "mcp" / "__init__.py"
    )
    assert packaged_web_console.__file__ is not None
    assert (
        Path(packaged_web_console.__file__).resolve()
        == OMS_PACKAGE_ROOT / "interfaces" / "web_console" / "__init__.py"
    )
    assert packaged_main_module.__file__ is not None
    assert Path(packaged_main_module.__file__).resolve() == OMS_PACKAGE_ROOT / "main.py"
    assert packaged_persistence.__file__ is not None
    assert (
        Path(packaged_persistence.__file__).resolve()
        == OMS_PACKAGE_ROOT / "persistence" / "__init__.py"
    )
    assert packaged_runtime_contracts.__file__ is not None
    assert (
        Path(packaged_runtime_contracts.__file__).resolve()
        == OMS_PACKAGE_ROOT / "runtime" / "contracts" / "__init__.py"
    )


def test_cli_and_main_entrypoints_use_only_canonical_modules() -> None:
    project_config = _load_project_configuration()
    project_version = cast(str, project_config["version"])
    packaged_main_module = importlib.import_module("oh_my_subagents.main")
    packaged_app = cast(FastAPI, packaged_main_module.app)
    packaged_create_app = cast(Any, packaged_main_module.create_app)

    assert main(["--help"]) == 0
    assert app.title == packaged_app.title == "Oh My Subagents API"
    assert app.version == packaged_app.version == project_version
    assert _route_paths(create_app(should_enable_mcp_mounts=False).routes) == _route_paths(
        packaged_create_app(should_enable_mcp_mounts=False).routes
    )


def test_pyproject_installs_sqlalchemy_asyncio_support() -> None:
    project_config = _load_project_configuration()
    dependencies = cast(list[str], project_config["dependencies"])

    assert "sqlalchemy[asyncio]>=2.0.40,<3.0.0" in dependencies


def test_pyproject_ships_canonical_packages_only() -> None:
    setuptools_config = _load_setuptools_configuration()
    project_config = _load_project_configuration()
    package_dir = cast(dict[str, str], setuptools_config["package-dir"])
    packages_find = cast(
        dict[str, Any], cast(dict[str, Any], setuptools_config["packages"])["find"]
    )
    package_data = cast(dict[str, list[str]], setuptools_config["package-data"])
    scripts = cast(dict[str, str], project_config["scripts"])

    assert project_config["name"] == "oh-my-subagents"
    assert project_config["version"] == "0.3.1"
    assert version("oh-my-subagents") == "0.3.1"
    assert package_dir == {"": "src"}
    assert packages_find == {
        "where": ["src"],
        "include": ["oh_my_subagents*", "banksia"],
        "namespaces": False,
    }
    assert scripts["oms"] == "oh_my_subagents.interfaces.cli.main:main"
    assert scripts["banksia"] == "oh_my_subagents.interfaces.cli.main:legacy_main"
    assert "autoclaw" not in scripts
    assert "oh_my_subagents" in package_data
    assert package_data["oh_my_subagents"] == [
        "interfaces/web_console/assets/index.html",
        "interfaces/web_console/assets/assets/*",
        "interfaces/web_console/assets/LICENSE.txt",
        "interfaces/web_console/assets/NOTICE.txt",
        "workflows/resources/starter_workflows/*.yaml",
        "platform/managed_services/resources/systemd/*.service",
        "operator/prompt/assets/*.txt",
        "runtime/prompt/assets/shared/*.txt",
        "runtime/prompt/assets/positions/*.txt",
        "runtime/prompt/assets/behaviors/*.txt",
        "runtime/prompt/assets/actions/*.txt",
        "runtime/prompt/assets/situations/*.txt",
    ]


def test_python_m_banksia_invokes_main() -> None:
    env = _source_import_env()
    result = subprocess.run(
        [sys.executable, "-m", "banksia", "--help"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage: banksia" in result.stdout
    assert LEGACY_COMMAND_NOTICE in result.stderr


def test_python_m_oms_interfaces_cli_invokes_main() -> None:
    env = _source_import_env()
    result = subprocess.run(
        [sys.executable, "-m", "oh_my_subagents.interfaces.cli", "--help"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage: oms" in result.stdout
    assert LEGACY_COMMAND_NOTICE not in result.stderr


def test_canonical_and_legacy_cli_entrypoints_are_explicit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--help"]) == 0
    canonical = capsys.readouterr()
    assert "Usage: oms" in canonical.out
    assert LEGACY_COMMAND_NOTICE not in canonical.err

    assert legacy_main(["--help"]) == 0
    legacy = capsys.readouterr()
    assert "Usage: banksia" in legacy.out
    assert LEGACY_COMMAND_NOTICE in legacy.err


def test_fresh_interpreter_can_import_canonical_package_roots() -> None:
    env = _source_import_env()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlib import resources; "
                "import oh_my_subagents.workflows; "
                "import oh_my_subagents.persistence; "
                "import oh_my_subagents.runtime.contracts; "
                "import oh_my_subagents.interfaces.web_console; "
                "import oh_my_subagents.platform.managed_services.resources; "
                "import oh_my_subagents.runtime.prompt.assets; "
                "from importlib.util import find_spec; "
                "workflow_root = resources.files("
                "'oh_my_subagents.workflows.resources.starter_workflows'); "
                "service_root = resources.files("
                "'oh_my_subagents.platform.managed_services.resources'); "
                "prompt_root = resources.files('oh_my_subagents.runtime.prompt.assets'); "
                f"assert tuple(sorted(entry.name for entry in workflow_root.iterdir() "
                f"if entry.name.endswith('.yaml'))) == {STARTER_WORKFLOW_FILENAMES!r}; "
                "assert service_root.name == 'resources'; "
                "assert prompt_root.name == 'assets'; "
                "assert find_spec('oh_my_subagents.interfaces.web_console') is not None"
            ),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "fresh interpreter canonical import smoke failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_fresh_interpreter_cannot_import_removed_autoclaw_package() -> None:
    env = _source_import_env()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlib.util import find_spec; assert find_spec('autoclaw') is None",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _source_import_env() -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SOURCE_ROOT)
        if not existing_pythonpath
        else os.pathsep.join((str(SOURCE_ROOT), existing_pythonpath))
    )
    return env


def test_resource_owner_helpers_point_to_canonical_package_paths() -> None:
    workflow_root = resources.files("oh_my_subagents.workflows.resources.starter_workflows")
    service_root = get_managed_service_resources_root()

    assert (
        tuple(
            sorted(entry.name for entry in workflow_root.iterdir() if entry.name.endswith(".yaml"))
        )
        == STARTER_WORKFLOW_FILENAMES
    )
    assert service_root.name == "resources"
    assert service_root.joinpath("systemd", "oh-my-subagents.service").is_file()


@pytest.mark.skipif(shutil.which("make") is None, reason="GNU Make is not installed")
def test_clean_local_preserves_ignored_research(tmp_path: Path) -> None:
    research_note = tmp_path / "tmp" / "codex" / "target" / "keep.md"
    research_note.parent.mkdir(parents=True)
    research_note.write_text("keep\n", encoding="utf-8")
    generated_paths = (
        tmp_path / ".pytest_cache",
        tmp_path / "dist",
        tmp_path / "console" / "dist",
        tmp_path / "src" / "oh_my_subagents" / "interfaces" / "web_console" / "assets",
    )
    for generated_path in generated_paths:
        generated_path.mkdir(parents=True)
        generated_path.joinpath("generated.txt").write_text("remove\n", encoding="utf-8")

    result = subprocess.run(
        ["make", "-f", str(REPO_ROOT / "Makefile"), "clean-local"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert research_note.read_text(encoding="utf-8") == "keep\n"
    assert all(not generated_path.exists() for generated_path in generated_paths)


def test_installed_distribution_workspace_must_be_external(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with pytest.raises(AssertionError, match="must be outside the repository"):
        validate_external_workspace(
            workspace=repo_root / "tmp" / "installed-proof",
            repo_root=repo_root,
        )

    validate_external_workspace(
        workspace=tmp_path / "external-installed-proof",
        repo_root=repo_root,
    )


def test_installed_task_verifier_matches_current_member_plan_contract() -> None:
    task_id = "t_12345678"

    verify_installed_task_view(
        {
            "id": task_id,
            "prompt_excerpt": INSTALLED_TASK_PROMPT,
            "workflow": {
                "id": "production-feature-delivery",
                "description": "Deliver and independently verify a consequential feature.",
            },
            "status": "starting",
            "status_message": "The run was accepted.",
            "started_at": "2026-08-05T00:00:00Z",
            "updated_at": "2026-08-05T00:00:00Z",
            "team": {
                "id": "lead",
                "name": "Lead",
                "purpose": None,
                "state": "working",
                "latest_update": None,
                "plan": None,
                "steer_action": None,
                "children": [],
            },
            "attention": [],
            "actions": [],
            "result": None,
            "activities": [],
            "activities_href": f"/api/tasks/{task_id}/activities",
            "activities_truncated": False,
            "human_requests": [],
            "human_request_count": 0,
            "human_requests_truncated": False,
            "command_runs": [],
            "command_runs_href": f"/api/tasks/{task_id}/command-runs",
            "command_run_count": 0,
            "command_runs_truncated": False,
        },
        task_id=task_id,
    )
