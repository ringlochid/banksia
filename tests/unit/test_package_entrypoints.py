from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import tomllib
from importlib import resources
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI

import banksia
from banksia.interfaces.cli.main import main
from banksia.main import app, create_app
from banksia.platform.managed_services.resources import get_managed_service_resources_root
from banksia.workflows.bootstrap import STARTER_WORKFLOW_FILENAMES
from scripts.testing.installed_distribution.processes import validate_external_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src"
BANKSIA_PACKAGE_ROOT = SOURCE_ROOT / "banksia"


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


def test_banksia_package_uses_src_modules_only() -> None:
    packaged_workflows = importlib.import_module("banksia.workflows")
    packaged_workflow_resources = importlib.import_module(
        "banksia.workflows.resources.starter_workflows"
    )
    packaged_http = importlib.import_module("banksia.interfaces.http")
    packaged_cli_owner = importlib.import_module("banksia.interfaces.cli")
    packaged_mcp_owner = importlib.import_module("banksia.interfaces.mcp")
    packaged_web_console = importlib.import_module("banksia.interfaces.web_console")
    packaged_main_module = importlib.import_module("banksia.main")
    packaged_persistence = importlib.import_module("banksia.persistence")
    packaged_runtime_contracts = importlib.import_module("banksia.runtime.contracts")

    assert banksia.__file__ is not None
    assert Path(banksia.__file__).resolve() == BANKSIA_PACKAGE_ROOT / "__init__.py"
    assert list(banksia.__path__) == [str(BANKSIA_PACKAGE_ROOT)]
    assert importlib.util.find_spec("banksia.cli") is None
    assert importlib.util.find_spec("banksia.definitions") is None
    assert packaged_workflows.__file__ is not None
    assert (
        Path(packaged_workflows.__file__).resolve()
        == BANKSIA_PACKAGE_ROOT / "workflows" / "__init__.py"
    )
    assert packaged_workflow_resources.__file__ is not None
    assert (
        Path(packaged_workflow_resources.__file__).resolve()
        == BANKSIA_PACKAGE_ROOT / "workflows" / "resources" / "starter_workflows" / "__init__.py"
    )
    assert packaged_cli_owner.__file__ is not None
    assert (
        Path(packaged_cli_owner.__file__).resolve()
        == BANKSIA_PACKAGE_ROOT / "interfaces" / "cli" / "__init__.py"
    )
    assert packaged_http.__file__ is not None
    assert (
        Path(packaged_http.__file__).resolve()
        == BANKSIA_PACKAGE_ROOT / "interfaces" / "http" / "__init__.py"
    )
    assert packaged_mcp_owner.__file__ is not None
    assert (
        Path(packaged_mcp_owner.__file__).resolve()
        == BANKSIA_PACKAGE_ROOT / "interfaces" / "mcp" / "__init__.py"
    )
    assert packaged_web_console.__file__ is not None
    assert (
        Path(packaged_web_console.__file__).resolve()
        == BANKSIA_PACKAGE_ROOT / "interfaces" / "web_console" / "__init__.py"
    )
    assert packaged_main_module.__file__ is not None
    assert Path(packaged_main_module.__file__).resolve() == BANKSIA_PACKAGE_ROOT / "main.py"
    assert packaged_persistence.__file__ is not None
    assert (
        Path(packaged_persistence.__file__).resolve()
        == BANKSIA_PACKAGE_ROOT / "persistence" / "__init__.py"
    )
    assert packaged_runtime_contracts.__file__ is not None
    assert (
        Path(packaged_runtime_contracts.__file__).resolve()
        == BANKSIA_PACKAGE_ROOT / "runtime" / "contracts" / "__init__.py"
    )


def test_cli_and_main_entrypoints_use_only_canonical_modules() -> None:
    project_config = _load_project_configuration()
    project_version = cast(str, project_config["version"])
    packaged_main_module = importlib.import_module("banksia.main")
    packaged_app = cast(FastAPI, packaged_main_module.app)
    packaged_create_app = cast(Any, packaged_main_module.create_app)

    assert main(["--help"]) == 0
    assert app.title == packaged_app.title == "Banksia API"
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

    assert project_config["name"] == "banksia"
    assert project_config["version"] == "0.1.4"
    assert version("banksia") == "0.1.4"
    assert package_dir == {"": "src"}
    assert packages_find == {
        "where": ["src"],
        "include": ["banksia*"],
        "namespaces": False,
    }
    assert scripts["banksia"] == "banksia.interfaces.cli.main:main"
    assert "autoclaw" not in scripts
    assert "banksia" in package_data
    assert package_data["banksia"] == [
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


def test_python_m_banksia_interfaces_cli_invokes_main() -> None:
    env = _source_import_env()
    result = subprocess.run(
        [sys.executable, "-m", "banksia.interfaces.cli", "--help"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage: banksia" in result.stdout


def test_fresh_interpreter_can_import_canonical_package_roots() -> None:
    env = _source_import_env()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlib import resources; "
                "import banksia.workflows; "
                "import banksia.persistence; "
                "import banksia.runtime.contracts; "
                "import banksia.interfaces.web_console; "
                "import banksia.platform.managed_services.resources; "
                "import banksia.runtime.prompt.assets; "
                "from importlib.util import find_spec; "
                "workflow_root = resources.files("
                "'banksia.workflows.resources.starter_workflows'); "
                "service_root = resources.files('banksia.platform.managed_services.resources'); "
                "prompt_root = resources.files('banksia.runtime.prompt.assets'); "
                f"assert tuple(sorted(entry.name for entry in workflow_root.iterdir() "
                f"if entry.name.endswith('.yaml'))) == {STARTER_WORKFLOW_FILENAMES!r}; "
                "assert service_root.name == 'resources'; "
                "assert prompt_root.name == 'assets'; "
                "assert find_spec('banksia.interfaces.web_console') is not None"
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
    workflow_root = resources.files("banksia.workflows.resources.starter_workflows")
    service_root = get_managed_service_resources_root()

    assert (
        tuple(
            sorted(entry.name for entry in workflow_root.iterdir() if entry.name.endswith(".yaml"))
        )
        == STARTER_WORKFLOW_FILENAMES
    )
    assert service_root.name == "resources"
    assert service_root.joinpath("systemd", "banksia.service").is_file()


def test_clean_local_preserves_ignored_research(tmp_path: Path) -> None:
    research_note = tmp_path / "tmp" / "codex" / "target" / "keep.md"
    research_note.parent.mkdir(parents=True)
    research_note.write_text("keep\n", encoding="utf-8")
    generated_paths = (
        tmp_path / ".pytest_cache",
        tmp_path / "dist",
        tmp_path / "console" / "dist",
        tmp_path / "src" / "banksia" / "interfaces" / "web_console" / "assets",
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
