from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class PrivatePathError(OSError):
    """Raised when Banksia cannot prove its private filesystem policy."""


class PrivateMutationTimeoutError(TimeoutError):
    """Raised when another process retains a private mutation lock."""


@dataclass(frozen=True)
class PosixPathIdentity:
    """Stable identity for one retained POSIX filesystem object."""

    device: int
    inode: int


type PathIdentity = PosixPathIdentity


class DirectoryLease(Protocol):
    """Opaque retained authority over one verified directory."""

    @property
    def identity(self) -> PathIdentity: ...

    def close(self) -> None: ...


class RegularFileLease(Protocol):
    """Opaque retained authority over one verified regular file."""

    @property
    def identity(self) -> PathIdentity: ...

    def close(self) -> None: ...


class WorkspaceFileOperations(Protocol):
    """Native filesystem operations required by the Task workspace runtime."""

    def open_workspace(self, path: Path) -> DirectoryLease: ...

    def open_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
        *,
        should_require_private: bool,
    ) -> DirectoryLease: ...

    def create_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
    ) -> DirectoryLease: ...

    def ensure_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
    ) -> None: ...

    def write_new_text(
        self,
        parent: DirectoryLease,
        name: str,
        text: str,
    ) -> None: ...

    def replace_text(
        self,
        parent: DirectoryLease,
        name: str,
        text: str,
    ) -> None: ...

    def read_small_text(
        self,
        parent: DirectoryLease,
        name: str,
        *,
        byte_limit: int,
    ) -> str | None: ...

    def unlink_entry(self, parent: DirectoryLease, name: str) -> None: ...

    def list_directory_names(self, directory: DirectoryLease) -> tuple[str, ...]: ...

    def is_real_child_directory(self, parent: DirectoryLease, name: str) -> bool: ...

    def remove_retained_tree(
        self,
        parent: DirectoryLease,
        name: str,
        directory: DirectoryLease,
    ) -> bool: ...

    def open_regular_file(
        self,
        workspace: Path,
        components: tuple[str, ...],
    ) -> RegularFileLease: ...

    def read_regular_file_range(
        self,
        file: RegularFileLease,
        *,
        offset: int,
        byte_limit: int,
    ) -> tuple[bytes, int]: ...

    def open_command_directory(
        self,
        workspace: Path,
        components: tuple[str, ...],
    ) -> DirectoryLease: ...

    def directory_descriptor(self, directory: DirectoryLease) -> int: ...

    def create_output_descriptor(
        self,
        parent: DirectoryLease,
        name: str,
    ) -> int: ...

    def append_text_line_locked(self, path: Path, line: str) -> None: ...


class PrivateFileOperations(Protocol):
    """Platform boundary for Banksia-owned private text files."""

    def ensure_directory(self, path: Path) -> None: ...

    def protect_path(self, path: Path, *, is_directory: bool) -> None: ...

    def read_text(self, path: Path) -> str | None: ...

    def replace_text(self, path: Path, text: str) -> None: ...

    def acquire_mutation_lock(
        self,
        path: Path,
        *,
        timeout_seconds: float,
    ) -> AbstractContextManager[None]: ...


__all__ = [
    "DirectoryLease",
    "PathIdentity",
    "PosixPathIdentity",
    "PrivateFileOperations",
    "PrivateMutationTimeoutError",
    "PrivatePathError",
    "RegularFileLease",
    "WorkspaceFileOperations",
]
