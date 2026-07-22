from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import banksia
from banksia.definitions.seeds import get_packaged_seed_definitions_root
from banksia.interfaces.cli.main import main
from banksia.interfaces.web_console import get_packaged_web_console_assets_root
from banksia.main import app, create_app
from banksia.platform.managed_services.resources import get_managed_service_resources_root
from fastapi import FastAPI


def _route_paths(routes: list[Any]) -> set[str]:
    return {str(route.path) for route in routes if hasattr(route, "path")}


def _load_setuptools_configuration() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[4]
    with (repo_root / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    tool_config = cast(dict[str, Any], pyproject["tool"])
    return cast(dict[str, Any], tool_config["setuptools"])


def _load_project_configuration() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[4]
    with (repo_root / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    return cast(dict[str, Any], pyproject["project"])


def test_banksia_package_uses_src_modules_only() -> None:
    package_root = Path(__file__).resolve().parents[2]
    src_root = package_root / "src" / "banksia"
    packaged_definitions = importlib.import_module("banksia.definitions")
    packaged_definitions_contracts = importlib.import_module("banksia.definitions.contracts")
    packaged_definitions_registry = importlib.import_module("banksia.definitions.registry")
    packaged_http = importlib.import_module("banksia.interfaces.http")
    packaged_cli_owner = importlib.import_module("banksia.interfaces.cli")
    packaged_mcp_owner = importlib.import_module("banksia.interfaces.mcp")
    packaged_web_console_owner = importlib.import_module("banksia.interfaces.web_console")
    packaged_main_module = importlib.import_module("banksia.main")
    packaged_persistence = importlib.import_module("banksia.persistence")
    packaged_runtime_contracts = importlib.import_module("banksia.runtime.contracts")

    assert banksia.__file__ is not None
    assert Path(banksia.__file__).resolve() == src_root / "__init__.py"
    assert list(banksia.__path__) == [str(src_root)]
    assert importlib.util.find_spec("banksia.cli") is None
    assert packaged_definitions.__file__ is not None
    assert Path(packaged_definitions.__file__).resolve() == src_root / "definitions" / "__init__.py"
    assert packaged_definitions_contracts.__file__ is not None
    assert (
        Path(packaged_definitions_contracts.__file__).resolve()
        == src_root / "definitions" / "contracts" / "__init__.py"
    )
    assert packaged_definitions_registry.__file__ is not None
    assert (
        Path(packaged_definitions_registry.__file__).resolve()
        == src_root / "definitions" / "registry" / "__init__.py"
    )
    assert packaged_cli_owner.__file__ is not None
    assert (
        Path(packaged_cli_owner.__file__).resolve()
        == src_root / "interfaces" / "cli" / "__init__.py"
    )
    assert packaged_http.__file__ is not None
    assert (
        Path(packaged_http.__file__).resolve() == src_root / "interfaces" / "http" / "__init__.py"
    )
    assert packaged_mcp_owner.__file__ is not None
    assert (
        Path(packaged_mcp_owner.__file__).resolve()
        == src_root / "interfaces" / "mcp" / "__init__.py"
    )
    assert packaged_web_console_owner.__file__ is not None
    assert (
        Path(packaged_web_console_owner.__file__).resolve()
        == src_root / "interfaces" / "web_console" / "__init__.py"
    )
    assert packaged_main_module.__file__ is not None
    assert Path(packaged_main_module.__file__).resolve() == src_root / "main.py"
    assert packaged_persistence.__file__ is not None
    assert Path(packaged_persistence.__file__).resolve() == src_root / "persistence" / "__init__.py"
    assert packaged_runtime_contracts.__file__ is not None
    assert (
        Path(packaged_runtime_contracts.__file__).resolve()
        == src_root / "runtime" / "contracts" / "__init__.py"
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
    assert package_dir == {"": "apps/api/src"}
    assert packages_find == {
        "where": ["apps/api/src"],
        "include": ["banksia*"],
        "namespaces": False,
    }
    assert scripts["banksia"] == "banksia.interfaces.cli.main:main"
    assert "autoclaw" not in scripts
    assert "banksia" in package_data
    assert package_data["banksia"] == [
        "definitions/seeds/policies/*.yaml",
        "definitions/seeds/roles/*.yaml",
        "definitions/seeds/workflows/*.yaml",
        "interfaces/web_console/assets/*",
        "interfaces/web_console/assets/assets/*",
        "platform/managed_services/resources/systemd/*.service",
        "runtime/prompt/assets/instructions/shared/*.md",
        "runtime/prompt/assets/instructions/families/*.md",
    ]


def test_python_m_banksia_invokes_main() -> None:
    package_root = Path(__file__).resolve().parents[2]
    repo_root = package_root.parent.parent
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(package_root / "src")
        if not existing_pythonpath
        else os.pathsep.join((str(package_root / "src"), existing_pythonpath))
    )
    result = subprocess.run(
        [sys.executable, "-m", "banksia", "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage: banksia" in result.stdout


def test_python_m_banksia_interfaces_cli_invokes_main() -> None:
    package_root = Path(__file__).resolve().parents[2]
    repo_root = package_root.parent.parent
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(package_root / "src")
        if not existing_pythonpath
        else os.pathsep.join((str(package_root / "src"), existing_pythonpath))
    )
    result = subprocess.run(
        [sys.executable, "-m", "banksia.interfaces.cli", "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage: banksia" in result.stdout


def test_fresh_interpreter_can_import_canonical_package_roots() -> None:
    package_root = Path(__file__).resolve().parents[2]
    repo_root = package_root.parent.parent
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(package_root / "src")
        if not existing_pythonpath
        else os.pathsep.join((str(package_root / "src"), existing_pythonpath))
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlib import resources; "
                "import banksia.definitions.compiler; "
                "import banksia.definitions.registry; "
                "import banksia.persistence; "
                "import banksia.runtime.contracts; "
                "import banksia.platform.managed_services.resources; "
                "import banksia.runtime.prompt.assets; "
                "import banksia.interfaces.web_console; "
                "seed_root = resources.files('banksia.definitions.seeds'); "
                "service_root = resources.files('banksia.platform.managed_services.resources'); "
                "prompt_root = resources.files('banksia.runtime.prompt.assets'); "
                "console_root = resources.files('banksia.interfaces.web_console'); "
                "assert seed_root.name == 'seeds'; "
                "assert service_root.name == 'resources'; "
                "assert prompt_root.name == 'assets'; "
                "assert console_root.joinpath('assets', 'index.html').is_file()"
            ),
        ],
        cwd=repo_root,
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
    package_root = Path(__file__).resolve().parents[2]
    repo_root = package_root.parent.parent
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(package_root / "src")
        if not existing_pythonpath
        else os.pathsep.join((str(package_root / "src"), existing_pythonpath))
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlib.util import find_spec; assert find_spec('autoclaw') is None",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_resource_owner_helpers_point_to_canonical_package_paths() -> None:
    seed_root = get_packaged_seed_definitions_root()
    service_root = get_managed_service_resources_root()
    console_assets_root = get_packaged_web_console_assets_root()

    assert seed_root.name == "seeds"
    assert seed_root.joinpath("roles", "planning_lead.yaml").is_file()
    assert service_root.name == "resources"
    # WP-01 slice B owns the operational service-resource rename.
    assert service_root.joinpath("systemd", "banksia.service").is_file()
    assert console_assets_root.name == "assets"
    assert console_assets_root.joinpath("index.html").is_file()
    assert console_assets_root.joinpath("app-icon.png").is_file()
