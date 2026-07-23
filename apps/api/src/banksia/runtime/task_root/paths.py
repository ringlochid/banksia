from __future__ import annotations

from pathlib import Path
from typing import Literal

from banksia.runtime.contracts import TaskRootPaths


def resolve_task_root_paths(
    *,
    task_root: Path,
    workspace: Path,
) -> TaskRootPaths:
    task_root_path = coerce_path(task_root)
    runtime_path = task_root_path / "_runtime"
    notes_path = task_root_path / "notes"
    return TaskRootPaths(
        task_root=task_root_path,
        workspace_path=coerce_path(workspace),
        outputs_path=task_root_path,
        artifacts_path=task_root_path / "artifacts",
        tmp_path=notes_path,
        runtime_path=runtime_path,
        dispatch_path=runtime_path / "dispatch",
    )


def ensure_task_root_layout(paths: TaskRootPaths) -> None:
    for path in (
        paths.task_root,
        paths.workspace_path,
        paths.outputs_path,
        paths.artifacts_path,
        paths.tmp_path,
        paths.runtime_path,
        paths.dispatch_path,
    ):
        path.mkdir(parents=True, exist_ok=True)


def instructions_markdown_path(*, paths: TaskRootPaths, dispatch_id: str) -> Path:
    return dispatch_dir_path(paths=paths, dispatch_id=dispatch_id) / "instructions.md"


def input_markdown_path(*, paths: TaskRootPaths, dispatch_id: str) -> Path:
    return dispatch_dir_path(paths=paths, dispatch_id=dispatch_id) / "input.md"


def command_run_log_path(
    *,
    paths: TaskRootPaths,
    run_id: str,
    stream: Literal["stdout", "stderr"],
) -> Path:
    return paths.task_root / command_run_logical_path(run_id=run_id, stream=stream)


def command_run_logical_path(
    *,
    run_id: str,
    stream: Literal["stdout", "stderr"],
) -> Path:
    _validate_path_component(run_id, label="command run ID")
    return Path("_runtime") / "command-runs" / run_id / f"{stream}.log"


def dispatch_dir_path(*, paths: TaskRootPaths, dispatch_id: str) -> Path:
    return paths.dispatch_path / dispatch_id


def coerce_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _validate_path_component(value: str, *, label: str) -> None:
    if not value or value in {".", ".."} or any(char in value for char in ("/", "\\", "\x00")):
        raise ValueError(f"{label} is not a safe path component")
