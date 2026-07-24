from __future__ import annotations

import fcntl
import os
import stat
import subprocess
from pathlib import Path, PurePosixPath

from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError

_GIT_MARKER_READ_LIMIT = 4_096
_READ_CHUNK_SIZE = 64 * 1024


def prepare_workspace_git_exclusion(workspace: Path) -> Path | None:
    """Exclude one workspace-local Banksia tree through Git's private metadata."""

    workspace = workspace.expanduser().resolve(strict=True)
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
    repository_root = Path(repository_root_text).resolve(strict=True)
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
    if not hasattr(os, "O_NOFOLLOW"):
        raise _invalid_workspace("This platform cannot safely update the Git exclude file")
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise _invalid_workspace(f"Git exclude path cannot be opened safely: {path}") from exc
    is_locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _invalid_workspace(f"Git exclude path is not a regular file: {path}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        is_locked = True
        _require_descriptor_path_identity(path, descriptor)
        current = _read_exclusion_bytes(descriptor)
        encoded = exclusion.encode("utf-8")
        if encoded in current.splitlines():
            return
        suffix = (b"\n" if current and not current.endswith(b"\n") else b"") + encoded + b"\n"
        os.lseek(descriptor, 0, os.SEEK_END)
        _write_all(descriptor, suffix)
        os.fsync(descriptor)
        _require_descriptor_path_identity(path, descriptor)
    except RuntimeOperationError:
        raise
    except OSError as exc:
        raise _invalid_workspace(f"Git exclude file could not be updated safely: {path}") from exc
    finally:
        if is_locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)


def _require_descriptor_path_identity(path: Path, descriptor: int) -> None:
    descriptor_metadata = os.fstat(descriptor)
    try:
        path_metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise _invalid_workspace(
            f"Git exclude path changed while it was being updated: {path}"
        ) from exc
    if (
        not stat.S_ISREG(path_metadata.st_mode)
        or path_metadata.st_dev != descriptor_metadata.st_dev
        or path_metadata.st_ino != descriptor_metadata.st_ino
    ):
        raise _invalid_workspace(f"Git exclude path changed while it was being updated: {path}")


def _read_exclusion_bytes(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    payload = bytearray()
    while True:
        chunk = os.read(descriptor, _READ_CHUNK_SIZE)
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("Git exclude write made no progress")
        remaining = remaining[written:]


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
