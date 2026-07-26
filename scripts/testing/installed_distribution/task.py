from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .processes import run_json_command
from .server import run_installed_server_smoke

INSTALLED_TASK_PROMPT = "Prove the installed Banksia Task contract remains durable after restart."
TASK_START_STATUS_MESSAGE = (
    "The run was accepted. Work starts asynchronously and may still need attention."
)
TASK_VIEW_KEYS = frozenset(
    {
        "id",
        "prompt_excerpt",
        "workflow",
        "status",
        "status_message",
        "started_at",
        "updated_at",
        "team",
        "plan",
        "attention",
        "actions",
        "result",
        "activities",
        "activities_href",
        "activities_truncated",
        "human_requests",
        "human_request_count",
        "human_requests_truncated",
        "command_runs",
        "command_run_count",
        "command_runs_truncated",
    }
)
TASK_PRODUCT_STATUSES = frozenset(
    {
        "starting",
        "working",
        "waiting_for_you",
        "paused",
        "completed",
        "blocked",
        "cancelled",
    }
)


def verify_installed_task_start(
    *,
    executable: Path,
    config_path: Path,
    port: int,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    request_path = write_installed_task_request(cwd)
    started, running = start_installed_task(
        executable=executable,
        config_path=config_path,
        port=port,
        cwd=cwd,
        env=env,
        request_path=request_path,
    )
    task_id = verify_installed_task_start_receipt(started, cwd=cwd)
    task, reopened = read_installed_task_after_restart(
        executable=executable,
        config_path=config_path,
        port=port,
        cwd=cwd,
        env=env,
        task_id=task_id,
    )
    verify_installed_task_view(task, task_id=task_id)
    return {
        "start": started,
        "live_server": running,
        "durable_readback": task,
        "restart": reopened,
    }


def write_installed_task_request(cwd: Path) -> Path:
    request_path = cwd / "installed-oracle-task.json"
    request_path.write_text(
        json.dumps(
            {
                "workflow": "reviewed-code-change",
                "prompt": INSTALLED_TASK_PROMPT,
            }
        ),
        encoding="utf-8",
    )
    return request_path


def start_installed_task(
    *,
    executable: Path,
    config_path: Path,
    port: int,
    cwd: Path,
    env: dict[str, str],
    request_path: Path,
) -> tuple[dict[str, Any], dict[str, object]]:
    running = run_installed_server_smoke(
        executable=executable,
        config_path=config_path,
        port=port,
        cwd=cwd,
        env=env,
        while_running=lambda: run_json_command(
            executable,
            (
                "task",
                "start",
                "--config",
                str(config_path),
                "--json",
                f"@{request_path}",
            ),
            cwd=cwd,
            env=env,
        ),
    )
    started = running.pop("while_running", None)
    if not isinstance(started, dict):
        raise AssertionError(f"installed Task start returned no receipt: {running}")
    return started, running


def verify_installed_task_start_receipt(
    started: dict[str, Any],
    *,
    cwd: Path,
) -> str:
    expected_receipt_keys = {
        "receipt_id",
        "task_id",
        "workflow_id",
        "workflow_revision",
        "workspace",
        "manifest",
        "status",
        "status_message",
    }
    if set(started) != expected_receipt_keys:
        raise AssertionError(f"installed Task start returned an unexpected receipt: {started}")
    task_id = started.get("task_id")
    if not isinstance(task_id, str) or len(task_id) != 10 or not task_id.startswith("t_"):
        raise AssertionError(f"installed Task start returned an unexpected task id: {started}")
    expected_receipt = {
        "workflow_id": "reviewed-code-change",
        "workspace": str(cwd.resolve()),
        "manifest": f".banksia/{task_id}/manifest.md",
        "status": "accepted",
        "status_message": TASK_START_STATUS_MESSAGE,
    }
    actual_receipt = {key: started.get(key) for key in expected_receipt}
    if actual_receipt != expected_receipt:
        raise AssertionError(f"installed Task start receipt was not semantic: {started}")
    if (
        not isinstance(started.get("receipt_id"), str)
        or not str(started["receipt_id"]).startswith("receipt.")
        or not isinstance(started.get("workflow_revision"), int)
        or int(started["workflow_revision"]) < 1
    ):
        raise AssertionError(f"installed Task start receipt identities were invalid: {started}")
    return task_id


def read_installed_task_after_restart(
    *,
    executable: Path,
    config_path: Path,
    port: int,
    cwd: Path,
    env: dict[str, str],
    task_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    reopened = run_installed_server_smoke(
        executable=executable,
        config_path=config_path,
        port=port,
        cwd=cwd,
        env=env,
        task_id=task_id,
    )
    task = reopened.pop("task", None)
    if not isinstance(task, dict):
        raise AssertionError(f"installed server did not return the committed Task: {reopened}")
    return task, reopened


def verify_installed_task_view(task: dict[str, object], *, task_id: str) -> None:
    workflow = task.get("workflow")
    team = task.get("team")
    if (
        set(task) != TASK_VIEW_KEYS
        or task.get("id") != task_id
        or task.get("prompt_excerpt") != INSTALLED_TASK_PROMPT
        or task.get("status") not in TASK_PRODUCT_STATUSES
        or not isinstance(task.get("status_message"), str)
        or not task["status_message"]
        or task.get("activities_href") != f"/api/tasks/{task_id}/activities"
        or not isinstance(workflow, dict)
        or set(workflow) != {"id", "description"}
        or workflow.get("id") != "reviewed-code-change"
        or not isinstance(workflow.get("description"), str)
        or not workflow["description"]
        or not isinstance(team, dict)
        or set(team) != {"id", "name", "purpose", "state", "latest_update", "children"}
    ):
        raise AssertionError(
            f"installed Task readback was not the durable product TaskView: {task}"
        )
    serialized_task = json.dumps(task, sort_keys=True)
    for removed_field in (
        "active_flow_revision_id",
        "flow_status",
        "task_id",
        "workflow_key",
    ):
        if f'"{removed_field}"' in serialized_task:
            raise AssertionError(
                f"installed Task readback retained legacy field {removed_field}: {task}"
            )
