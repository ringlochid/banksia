from __future__ import annotations

from pathlib import Path

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


def command_run_output_path(
    *,
    task_id: str,
    run_id: str,
) -> Path:
    """Return the sole workspace-relative full-output path for one Command Run."""

    _validate_path_component(task_id, label="Task ID")
    _validate_path_component(run_id, label="command run ID")
    return Path(".banksia") / task_id / "command-runs" / run_id / "output.log"


def coerce_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _validate_path_component(value: str, *, label: str) -> None:
    if not value or value in {".", ".."} or any(char in value for char in ("/", "\\", "\x00")):
        raise ValueError(f"{label} is not a safe path component")
