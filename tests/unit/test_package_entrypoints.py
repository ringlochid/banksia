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

from fastapi import FastAPI

import banksia
from banksia.interfaces.cli.main import main
from banksia.main import app, create_app
from banksia.platform.managed_services.resources import get_managed_service_resources_root

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


def test_pyproject_ships_canonical_packages_only() -> None:
    setuptools_config = _load_setuptools_configuration()
    project_config = _load_project_configuration()
    package_dir = cast(dict[str, str], setuptools_config["package-dir"])
    packages_find = cast(
        dict[str, Any], cast(dict[str, Any], setuptools_config["packages"])["find"]
    )
    package_data = cast(dict[str, list[str]], setuptools_config["package-data"])
    scripts = cast(dict[str, str], project_config["scripts"])

    assert project_config["name"] == "banksia-ai"
    assert project_config["version"] == "0.1.8"
    assert version("banksia-ai") == "0.1.8"
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
        "workflows/resources/starter_workflows/*.yaml",
        "platform/managed_services/resources/systemd/*.service",
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
                "assert workflow_root.joinpath('reviewed-delivery.yaml').is_file(); "
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

    assert workflow_root.joinpath("reviewed-delivery.yaml").is_file()
    assert service_root.name == "resources"
    # WP-01 slice B owns the operational service-resource rename.
    assert service_root.joinpath("systemd", "banksia.service").is_file()
