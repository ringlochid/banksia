from __future__ import annotations

import fcntl
import os
import stat
from dataclasses import dataclass

from banksia.platform.workspace_files.contracts import (
    DirectoryLease,
    PosixPathIdentity,
    RegularFileLease,
)


@dataclass(slots=True)
class PosixDirectoryLease:
    """Retained descriptor authority over one verified POSIX directory."""

    _descriptor: int | None
    identity: PosixPathIdentity

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise RuntimeError("POSIX directory lease is closed")
        return self._descriptor

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)


@dataclass(slots=True)
class PosixRegularFileLease:
    """Retained descriptor authority over one verified POSIX regular file."""

    _descriptor: int | None
    identity: PosixPathIdentity

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise RuntimeError("POSIX regular-file lease is closed")
        return self._descriptor

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)


def build_posix_directory_lease(descriptor: int) -> PosixDirectoryLease:
    descriptor = move_descriptor_above_standard_streams(descriptor)
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise NotADirectoryError("retained POSIX path is not a directory")
    return PosixDirectoryLease(
        descriptor,
        PosixPathIdentity(metadata.st_dev, metadata.st_ino),
    )


def require_posix_directory_lease(
    directory: DirectoryLease,
) -> PosixDirectoryLease:
    if not isinstance(directory, PosixDirectoryLease):
        raise TypeError("directory lease does not belong to the POSIX workspace backend")
    return directory


def require_posix_regular_file_lease(
    file: RegularFileLease,
) -> PosixRegularFileLease:
    if not isinstance(file, PosixRegularFileLease):
        raise TypeError("regular-file lease does not belong to the POSIX workspace backend")
    return file


def move_descriptor_above_standard_streams(descriptor: int) -> int:
    if descriptor > 2:
        return descriptor
    replacement = fcntl.fcntl(
        descriptor,
        fcntl.F_DUPFD_CLOEXEC,
        3,
    )
    os.close(descriptor)
    return int(replacement)


__all__ = [
    "PosixDirectoryLease",
    "PosixRegularFileLease",
    "build_posix_directory_lease",
    "move_descriptor_above_standard_streams",
    "require_posix_directory_lease",
    "require_posix_regular_file_lease",
]
