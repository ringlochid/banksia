from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from autoclaw.runtime.contracts import TaskRootPaths
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError

LOGICAL_TASK_ROOTS = ("workspace", "outputs", "tmp", "_runtime")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class ResolvedLogicalTaskPath:
    logical_path: str
    physical_path: Path
    physical_root: Path


def resolve_logical_task_path(
    paths: TaskRootPaths,
    logical_path: str,
    *,
    is_root_listing_allowed: bool = False,
) -> ResolvedLogicalTaskPath | None:
    normalized = normalize_logical_task_path(
        logical_path,
        is_root_listing_allowed=is_root_listing_allowed,
    )
    if normalized == ".":
        return None
    pure_path = PurePosixPath(normalized)
    root_name = pure_path.parts[0]
    physical_root = _physical_root(paths, root_name).resolve()
    if root_name != "workspace" and not physical_root.is_relative_to(paths.task_root.absolute()):
        raise _path_error(
            OperationFailureCode.PATH_ESCAPE,
            "controller-owned logical root leaves the task root",
        )
    candidate = physical_root.joinpath(*pure_path.parts[1:]).resolve(strict=False)
    if not candidate.is_relative_to(physical_root):
        raise _path_error(
            OperationFailureCode.PATH_ESCAPE,
            "resolved task path leaves its selected logical root",
        )
    return ResolvedLogicalTaskPath(
        logical_path=normalized,
        physical_path=candidate,
        physical_root=physical_root,
    )


def normalize_logical_task_path(
    value: str,
    *,
    is_root_listing_allowed: bool = False,
) -> str:
    if "\x00" in value or "\\" in value:
        raise _invalid_path("task path contains a forbidden character")
    if value.startswith(("/", "//")) or _WINDOWS_DRIVE.match(value):
        raise _invalid_path("task path must be relative to a logical task root")
    if not value:
        raise _invalid_path("task path must not be empty")
    parts = tuple(part for part in value.split("/") if part not in ("", "."))
    if not parts:
        if is_root_listing_allowed and value == ".":
            return "."
        raise _invalid_path("task path must name a logical task root")
    if ".." in parts:
        raise _invalid_path("task path must not traverse to a parent")
    if parts[0] not in LOGICAL_TASK_ROOTS:
        raise _path_error(
            OperationFailureCode.INVALID_TASK_ROOT,
            f"unknown logical task root '{parts[0]}'",
        )
    return "/".join(parts)


def _physical_root(paths: TaskRootPaths, root_name: str) -> Path:
    roots = {
        "workspace": paths.workspace_path,
        "outputs": paths.outputs_path,
        "tmp": paths.tmp_path,
        "_runtime": paths.runtime_path,
    }
    root = roots.get(root_name)
    if root is None:
        raise _path_error(
            OperationFailureCode.INVALID_TASK_ROOT,
            f"logical task root '{root_name}' is unavailable",
        )
    return root


def _invalid_path(summary: str) -> RuntimeOperationError:
    return _path_error(OperationFailureCode.INVALID_TASK_PATH, summary)


def _path_error(code: OperationFailureCode, summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=code,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Use a contained path under workspace, outputs, tmp, or _runtime.",
    )


__all__ = [
    "LOGICAL_TASK_ROOTS",
    "ResolvedLogicalTaskPath",
    "normalize_logical_task_path",
    "resolve_logical_task_path",
]
