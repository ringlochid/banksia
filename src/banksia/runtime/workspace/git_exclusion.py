from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path, PurePosixPath

from banksia.platform.workspace_files import select_workspace_file_operations
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.file_references import validate_workspace

_GIT_MARKER_READ_LIMIT = 4_096


def prepare_workspace_git_exclusion(workspace: Path) -> Path | None:
    """Exclude one workspace-local Banksia tree through Git's private metadata."""

    workspace = validate_workspace(workspace)
    try:
        repository_root_text = _git_output(
            workspace,
            "rev-parse",
            "--show-toplevel",
            allow_not_repository=True,
        )
    except FileNotFoundError as exc:
        if _has_git_worktree_marker(workspace):
            raise _invalid_workspace(
                "Git is required to prepare the Task workspace exclusion for this worktree"
            ) from exc
        return None
    if repository_root_text is None:
        return None
    repository_root = validate_workspace(Path(repository_root_text))
    try:
        workspace_relative = workspace.relative_to(repository_root)
    except ValueError as exc:
        raise _invalid_workspace(
            "Git reported a repository root that does not contain the Task workspace"
        ) from exc

    banksia_relative = workspace_relative / ".banksia"
    tracked = _run_git(
        repository_root,
        "ls-files",
        "-z",
        "--",
        f":(literal){banksia_relative.as_posix()}",
    ).stdout
    if tracked:
        raise _invalid_workspace("Task workspace contains tracked content under its .banksia path")

    exclude_text = _git_output(
        workspace,
        "rev-parse",
        "--path-format=absolute",
        "--git-path",
        "info/exclude",
    )
    assert exclude_text is not None
    exclude_path = Path(exclude_text)
    exclusion = _workspace_exclusion(workspace_relative)
    _append_exclusion(exclude_path, exclusion)
    return exclude_path


def _workspace_exclusion(workspace_relative: Path) -> str:
    parts = () if workspace_relative == Path(".") else workspace_relative.parts
    escaped_parts = tuple(_escape_gitignore_component(part) for part in parts)
    path = PurePosixPath(*escaped_parts, ".banksia").as_posix()
    return f"/{path}/"


def _escape_gitignore_component(component: str) -> str:
    if "\n" in component or "\r" in component:
        raise _invalid_workspace("Git workspaces with newline path components are unsupported")
    escaped = component.replace("\\", "\\\\")
    for character in (" ", "*", "?", "[", "]"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _has_git_worktree_marker(workspace: Path) -> bool:
    for candidate in (workspace, *workspace.parents):
        marker = candidate / ".git"
        try:
            metadata = marker.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            return True
        if stat.S_ISDIR(metadata.st_mode):
            if (marker / "HEAD").is_file():
                return True
            continue
        if stat.S_ISREG(metadata.st_mode):
            marker_state = _read_regular_git_marker(marker)
            if marker_state is None:
                return True
            if marker_state:
                return True
            continue
        return True
    return False


def _read_regular_git_marker(marker: Path) -> bool | None:
    if not hasattr(os, "O_NOFOLLOW"):
        return None
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(marker, flags)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _GIT_MARKER_READ_LIMIT:
            return None
        payload = os.read(descriptor, _GIT_MARKER_READ_LIMIT + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    if len(payload) > _GIT_MARKER_READ_LIMIT:
        return None
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeError:
        return None
    return text.startswith("gitdir:")


def _append_exclusion(path: Path, exclusion: str) -> None:
    try:
        select_workspace_file_operations().append_text_line_locked(path, exclusion)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise _invalid_workspace(
            f"Git exclude file could not be updated safely ({reason}): {path}"
        ) from exc


def _git_output(
    workspace: Path,
    *arguments: str,
    allow_not_repository: bool = False,
) -> str | None:
    result = _run_git(workspace, *arguments, check=False)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        if allow_not_repository and "not a git repository" in error.casefold():
            return None
        raise RuntimeError(f"Git command failed: {error or result.returncode}")
    return result.stdout.decode("utf-8").rstrip("\r\n")


def _run_git(
    workspace: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", "-C", str(workspace), *arguments),
        check=check,
        capture_output=True,
    )


def _invalid_workspace(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INVALID_TASK_ROOT,
        summary=summary,
        is_retryable=False,
        suggested_next_step=(
            "Remove or relocate conflicting tracked workspace content, then retry."
        ),
        status_code_override=422,
    )


__all__ = ["prepare_workspace_git_exclusion"]
