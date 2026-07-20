from __future__ import annotations

from pathlib import Path
from typing import Literal

from autoclaw.runtime.contracts import (
    TaskComposeInput,
    TaskRootBindingInput,
    TaskRootMode,
    TaskRootPaths,
)


def resolve_task_root_paths(
    *,
    task_root: Path,
    task_compose: TaskComposeInput,
) -> TaskRootPaths:
    roots = task_compose.roots
    task_root_path = coerce_path(task_root)
    workspace_binding = _binding_or_default(roots.workspace if roots is not None else None)
    runtime_path = task_root_path / "_runtime"
    outputs_path = task_root_path / "outputs"
    transfers_path = task_root_path / "tmp" / "transfers"
    return TaskRootPaths(
        task_root=task_root_path,
        workspace_path=_resolve_workspace_root(
            task_root=task_root_path,
            binding=workspace_binding,
        ),
        outputs_path=outputs_path,
        artifacts_path=outputs_path / "artifacts",
        tmp_path=task_root_path / "tmp",
        transfers_path=transfers_path,
        localized_path=transfers_path / "localized",
        runtime_path=runtime_path,
        criteria_path=runtime_path / "criteria",
        attempts_path=runtime_path / "attempts",
        dispatch_path=runtime_path / "dispatch",
    )


def ensure_task_root_layout(paths: TaskRootPaths) -> None:
    for path in (
        paths.task_root,
        paths.workspace_path,
        paths.outputs_path,
        paths.artifacts_path,
        paths.tmp_path,
        paths.transfers_path,
        paths.localized_path,
        paths.runtime_path,
        paths.criteria_path,
        paths.attempts_path,
        paths.dispatch_path,
    ):
        path.mkdir(parents=True, exist_ok=True)


def assignment_json_path(*, paths: TaskRootPaths, attempt_id: str) -> Path:
    return attempt_dir_path(paths=paths, attempt_id=attempt_id) / "assignment.json"


def assignment_markdown_path(*, paths: TaskRootPaths, attempt_id: str) -> Path:
    return attempt_dir_path(paths=paths, attempt_id=attempt_id) / "assignment.md"


def checkpoint_json_path(*, paths: TaskRootPaths, attempt_id: str) -> Path:
    return attempt_dir_path(paths=paths, attempt_id=attempt_id) / "latest-checkpoint.json"


def checkpoint_markdown_path(*, paths: TaskRootPaths, attempt_id: str) -> Path:
    return attempt_dir_path(paths=paths, attempt_id=attempt_id) / "latest-checkpoint.md"


def artifact_index_json_path(*, paths: TaskRootPaths, attempt_id: str) -> Path:
    return attempt_dir_path(paths=paths, attempt_id=attempt_id) / "artifact-index.json"


def transient_index_json_path(*, paths: TaskRootPaths, attempt_id: str) -> Path:
    return attempt_dir_path(paths=paths, attempt_id=attempt_id) / "transient-index.json"


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


def criteria_file_path(
    *,
    paths: TaskRootPaths,
    slot: str,
    version: int | None = None,
) -> Path:
    return paths.task_root / criteria_logical_path(slot=slot, version=version)


def criteria_logical_path(*, slot: str, version: int | None = None) -> Path:
    criteria_root = Path("_runtime") / "criteria"
    if version is None:
        return criteria_root / f"{slot}.md"
    return criteria_root / f"{slot}.v{version:02d}.md"


def manifest_json_path(paths: TaskRootPaths) -> Path:
    return paths.runtime_path / "workflow-manifest.json"


def manifest_markdown_path(paths: TaskRootPaths) -> Path:
    return paths.runtime_path / "workflow-manifest.md"


def artifact_current_json_path(
    *,
    paths: TaskRootPaths,
    owner_node_key: str,
    slot: str,
) -> Path:
    return paths.artifacts_path / owner_node_key / slot / "current.json"


def attempt_dir_path(*, paths: TaskRootPaths, attempt_id: str) -> Path:
    return paths.attempts_path / attempt_id


def dispatch_dir_path(*, paths: TaskRootPaths, dispatch_id: str) -> Path:
    return paths.dispatch_path / dispatch_id


def coerce_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _validate_path_component(value: str, *, label: str) -> None:
    if not value or value in {".", ".."} or any(char in value for char in ("/", "\\", "\x00")):
        raise ValueError(f"{label} is not a safe path component")


def _binding_or_default(binding: TaskRootBindingInput | None) -> TaskRootBindingInput:
    if binding is not None:
        return binding
    return TaskRootBindingInput()


def _resolve_workspace_root(
    *,
    task_root: Path,
    binding: TaskRootBindingInput,
) -> Path:
    if binding.mode == TaskRootMode.ENSURE_TASK_DEFAULT:
        return task_root / "workspace"

    assert binding.host_path is not None
    host_path = coerce_path(binding.host_path)
    if binding.mode == TaskRootMode.USE_EXISTING_HOST and not host_path.exists():
        raise FileNotFoundError(
            f"workspace host path does not exist for use_existing_host: {host_path}"
        )
    if host_path.exists() and not host_path.is_dir():
        raise NotADirectoryError(f"workspace host path is not a directory: {host_path}")
    return host_path
