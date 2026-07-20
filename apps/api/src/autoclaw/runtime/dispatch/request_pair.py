from __future__ import annotations

import errno
import os
import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from autoclaw.runtime.contracts import TaskRootPaths

_INSTRUCTIONS_FILENAME = "instructions.md"
_INPUT_FILENAME = "input.md"


@dataclass(frozen=True, slots=True)
class DispatchRequestPairRefs:
    instructions_logical_path: str
    input_logical_path: str


def publish_dispatch_request_pair(
    *,
    paths: TaskRootPaths,
    dispatch_id: str,
    instructions_bytes: bytes,
    input_bytes: bytes,
) -> DispatchRequestPairRefs:
    """Publish one immutable dispatch request directory before its DB transaction."""

    _validate_dispatch_id(dispatch_id)
    if not isinstance(instructions_bytes, bytes) or not isinstance(input_bytes, bytes):
        raise TypeError("dispatch request contents must be bytes")

    dispatch_root = _resolve_canonical_dispatch_root(paths)
    dispatch_root.mkdir(parents=True, exist_ok=True)
    final_directory = dispatch_root / dispatch_id
    if os.path.lexists(final_directory):
        raise FileExistsError(f"dispatch request directory already exists: {final_directory}")

    staging_directory = Path(
        tempfile.mkdtemp(
            prefix=".dispatch-stage-",
            dir=dispatch_root,
        )
    )
    is_final_directory_owned = False
    try:
        _write_file_and_sync(staging_directory / _INSTRUCTIONS_FILENAME, instructions_bytes)
        _write_file_and_sync(staging_directory / _INPUT_FILENAME, input_bytes)
        _sync_directory_if_supported(staging_directory)
        os.mkdir(final_directory)
        is_final_directory_owned = True
        _move_staged_file(staging_directory, final_directory, _INSTRUCTIONS_FILENAME)
        _move_staged_file(staging_directory, final_directory, _INPUT_FILENAME)
        _sync_directory_if_supported(final_directory)
        staging_directory.rmdir()
        _sync_directory_if_supported(dispatch_root)
    except BaseException:
        if os.path.lexists(staging_directory):
            with suppress(OSError):
                shutil.rmtree(staging_directory)
        if is_final_directory_owned and os.path.lexists(final_directory):
            with suppress(OSError):
                shutil.rmtree(final_directory)
        raise

    logical_root = PurePosixPath("_runtime", "dispatch", dispatch_id)
    return DispatchRequestPairRefs(
        instructions_logical_path=str(logical_root / _INSTRUCTIONS_FILENAME),
        input_logical_path=str(logical_root / _INPUT_FILENAME),
    )


def _validate_dispatch_id(dispatch_id: str) -> None:
    """Require one bounded filesystem segment for a prospective dispatch ID."""

    try:
        encoded_dispatch_id = dispatch_id.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("dispatch_id must be valid UTF-8") from exc
    if (
        not dispatch_id
        or len(encoded_dispatch_id) > 255
        or dispatch_id in {".", ".."}
        or "/" in dispatch_id
        or "\\" in dispatch_id
        or "\x00" in dispatch_id
    ):
        raise ValueError("dispatch_id must be one safe path segment of at most 255 UTF-8 bytes")


def _resolve_canonical_dispatch_root(paths: TaskRootPaths) -> Path:
    """Validate and return the controller-owned `_runtime/dispatch` directory."""

    if not all(
        path.is_absolute() for path in (paths.task_root, paths.runtime_path, paths.dispatch_path)
    ):
        raise ValueError("task runtime paths must be absolute")
    lexical_task_root = Path(os.path.abspath(paths.task_root))
    lexical_runtime_root = Path(os.path.abspath(paths.runtime_path))
    lexical_dispatch_root = Path(os.path.abspath(paths.dispatch_path))
    expected_runtime_root = lexical_task_root / "_runtime"
    expected_dispatch_root = expected_runtime_root / "dispatch"
    if (
        lexical_runtime_root != expected_runtime_root
        or lexical_dispatch_root != expected_dispatch_root
    ):
        raise ValueError("dispatch path must use the canonical task runtime root")

    resolved_task_root = lexical_task_root.resolve(strict=False)
    resolved_runtime_root = lexical_runtime_root.resolve(strict=False)
    resolved_dispatch_root = lexical_dispatch_root.resolve(strict=False)
    if not resolved_runtime_root.is_relative_to(resolved_task_root):
        raise ValueError("runtime root escapes the task root")
    if not resolved_dispatch_root.is_relative_to(resolved_task_root):
        raise ValueError("dispatch root escapes the task root")
    if resolved_dispatch_root != (resolved_runtime_root / "dispatch").resolve(strict=False):
        raise ValueError("dispatch path must use the canonical task runtime root")
    return resolved_dispatch_root


def _write_file_and_sync(path: Path, payload: bytes) -> None:
    """Create, flush, and file-sync one staged regular file."""

    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _move_staged_file(
    staging_directory: Path,
    final_directory: Path,
    filename: str,
) -> None:
    os.rename(staging_directory / filename, final_directory / filename)


def _sync_directory_if_supported(path: Path) -> None:
    """Sync directory metadata on platforms that expose a directory descriptor."""

    if os.name != "posix" or not getattr(os, "O_DIRECTORY", 0):
        return
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    try:
        directory_fd = os.open(path, flags)
    except OSError as exc:
        if _is_unsupported_directory_sync(exc):
            return
        raise
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        if not _is_unsupported_directory_sync(exc):
            raise
    finally:
        os.close(directory_fd)


def _is_unsupported_directory_sync(exc: OSError) -> bool:
    unsupported_errors = {
        errno.EBADF,
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
    return exc.errno in unsupported_errors


__all__ = [
    "DispatchRequestPairRefs",
    "publish_dispatch_request_pair",
]
