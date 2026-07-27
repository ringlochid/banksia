from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def replace_service_definition(path: Path, content: bytes) -> None:
    """Atomically replace one regular definition without following the target."""

    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_nonregular_definition(path)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _reject_nonregular_definition(path)
        os.replace(temporary_path, path)
    except BaseException:
        os.close(file_descriptor) if _is_open_file_descriptor(file_descriptor) else None
        temporary_path.unlink(missing_ok=True)
        raise


def remove_service_definition(path: Path) -> None:
    _reject_nonregular_definition(path)
    path.unlink(missing_ok=True)


def read_service_definition(path: Path) -> bytes | None:
    try:
        file_status = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(file_status.st_mode):
        raise RuntimeError(f"service definition must be a regular file: {path}")
    return path.read_bytes()


def _reject_nonregular_definition(path: Path) -> None:
    try:
        file_status = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(file_status.st_mode):
        raise RuntimeError(f"service definition must be a regular file: {path}")


def _is_open_file_descriptor(file_descriptor: int) -> bool:
    try:
        os.fstat(file_descriptor)
    except OSError:
        return False
    return True


__all__ = [
    "read_service_definition",
    "remove_service_definition",
    "replace_service_definition",
]
