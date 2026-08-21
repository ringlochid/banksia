from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from http.client import HTTPConnection
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .artifacts import (
    ADVANCED_REFERENCE_WORKFLOW_IDS,
    STARTER_WORKFLOW_FILENAMES,
    STARTER_WORKFLOW_IDS,
)
from .processes import merged_environment, run_checked, venv_python

SERVER_START_TIMEOUT_SECONDS = 20.0
SERVER_STOP_TIMEOUT_SECONDS = 10.0
SERVER_REQUEST_TIMEOUT_SECONDS = 1.0


def run_installed_lifespan_smoke(
    *,
    venv_path: Path,
    cwd: Path,
    env: dict[str, str],
    repo_root: Path,
) -> subprocess.CompletedProcess[str]:
    script = f"""
import asyncio
import os
from pathlib import Path

import banksia
from banksia.config import load_settings
from importlib.util import find_spec
from importlib.resources import files
from banksia.main import create_app
from banksia.platform.managed_services.resources import get_systemd_service_template
from banksia.runtime.prompt import InstructionAsset, load_instruction_asset

package_path = Path(banksia.__file__).resolve()
venv_path = Path(os.environ["OMS_ORACLE_VENV"]).resolve()
repo_root = Path(os.environ["OMS_ORACLE_REPO_ROOT"]).resolve()
assert package_path.is_relative_to(venv_path)
assert not package_path.is_relative_to(repo_root / "src")
starter_root = files("banksia.workflows.resources.starter_workflows")
actual_starters = tuple(sorted(
    entry.name for entry in starter_root.iterdir() if entry.name.endswith(".yaml")
))
assert actual_starters == {STARTER_WORKFLOW_FILENAMES!r}
assert get_systemd_service_template().is_file()
assert find_spec("banksia.interfaces.web_console") is not None
assert files("banksia.interfaces.web_console").joinpath("assets", "index.html").is_file()
assert load_instruction_asset(InstructionAsset.CORE).strip()
assert load_settings().postgres_schema == "banksia"

async def smoke() -> None:
    app = create_app(should_enable_mcp_mounts=False)
    async with app.router.lifespan_context(app):
        assert app.title == "Oh My Subagents API"

asyncio.run(smoke())
print(package_path)
"""
    return run_checked(
        (str(venv_python(venv_path)), "-c", script),
        cwd=cwd,
        env={
            **env,
            "OMS_ORACLE_REPO_ROOT": str(repo_root),
            "OMS_ORACLE_VENV": str(venv_path),
        },
    )


def run_installed_server_smoke(
    *,
    executable: Path,
    config_path: Path,
    port: int,
    cwd: Path,
    env: dict[str, str],
    task_id: str | None = None,
    while_running: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, object]:
    log_path = cwd / "installed-serve.log"
    process_environment = merged_environment(env)
    failure: Exception | None = None
    health_payloads: dict[str, dict[str, object]] = {}
    while_running_result: dict[str, Any] | None = None

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
            if while_running is not None:
                while_running_result = while_running()
            if task_id is not None:
                health_payloads["task"] = read_loopback_json(
                    f"http://127.0.0.1:{port}/api/tasks/{task_id}"
                )
        except Exception as exc:
            failure = exc
        finally:
            return_code = stop_process(process)
            server_log.flush()
            server_log.seek(0)
            output = server_log.read()

    if failure is not None:
        raise RuntimeError(
            f"installed `oms serve` did not become healthy\nserver output:\n{output[-4000:]}"
        ) from failure
    accepted_shutdown_codes = {0, 1} if os.name == "nt" else {0, -signal.SIGTERM}
    if return_code not in accepted_shutdown_codes:
        raise RuntimeError(
            f"installed `oms serve` exited with {return_code} after shutdown\n"
            f"server output:\n{output[-4000:]}"
        )
    result: dict[str, object] = {
        "host": "127.0.0.1",
        "port": port,
        "health": health_payloads["healthz"],
        "readiness": health_payloads["readyz"],
        "shutdown_return_code": return_code,
    }
    if task_id is not None:
        result["task"] = health_payloads["task"]
    if while_running_result is not None:
        result["while_running"] = while_running_result
    return result


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


def verify_installed_console(port: int) -> dict[str, object]:
    root_status, root_headers, _ = read_loopback_response(port, "/")
    if root_status != 307 or root_headers.get("location") != "/workflows":
        raise AssertionError(
            f"installed Console root did not redirect to Workflows: {root_status}, {root_headers}"
        )
    page_bodies: dict[str, str] = {}
    for path in ("/workflows", "/workflows/production-feature-delivery", "/runs"):
        status_code, headers, body = read_loopback_response(port, path)
        if (
            status_code != 200
            or "text/html" not in headers.get("content-type", "")
            or "<title>Oh My Subagents</title>" not in body
        ):
            raise AssertionError(f"installed Console route {path} did not return the packaged app")
        page_bodies[path] = body
    workflow_library = read_loopback_json(f"http://127.0.0.1:{port}/api/workflows")
    workflow_items = workflow_library.get("items")
    if not isinstance(workflow_items, list):
        raise AssertionError(
            f"installed Workflow library returned an unexpected shape: {workflow_library}"
        )
    workflow_ids = tuple(
        item.get("workflow_id") for item in workflow_items if isinstance(item, dict)
    )
    if workflow_ids != STARTER_WORKFLOW_IDS:
        raise AssertionError(
            f"installed Workflow library does not match the exact Starter catalog: {workflow_ids}"
        )
    if set(workflow_ids) & set(ADVANCED_REFERENCE_WORKFLOW_IDS):
        raise AssertionError(
            "installed Workflow library exposed maintained advanced reference examples"
        )
    asset_paths = tuple(
        sorted(
            {
                match
                for match in re.findall(
                    r'(?:src|href)="(/assets/[^"]+)"',
                    page_bodies["/workflows"],
                )
            }
        )
    )
    if not asset_paths:
        raise AssertionError("installed Console HTML did not reference packaged assets")
    for asset_path in asset_paths:
        status_code, _, body = read_loopback_response(port, asset_path)
        if status_code != 200 or body == "":
            raise AssertionError(f"installed Console asset was unavailable: {asset_path}")
    for path in (
        "/not-a-console-route",
        "/assets/not-a-real-asset.js",
        "/api/not-a-product-route",
    ):
        status_code, _, _ = read_loopback_response(port, path)
        if status_code != 404:
            raise AssertionError(f"installed Console rewrote unknown path {path}: {status_code}")
    return {
        "routes": tuple(page_bodies),
        "assets": asset_paths,
        "starter_workflows": workflow_ids,
    }


def read_loopback_response(
    port: int,
    path: str,
) -> tuple[int, dict[str, str], str]:
    connection = HTTPConnection(
        "127.0.0.1",
        port,
        timeout=SERVER_REQUEST_TIMEOUT_SECONDS,
    )
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        headers = {key.casefold(): value for key, value in response.getheaders()}
        return (
            response.status,
            headers,
            response.read().decode("utf-8"),
        )
    finally:
        connection.close()


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
