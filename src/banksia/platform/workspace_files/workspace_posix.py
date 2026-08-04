from __future__ import annotations

import errno
import fcntl
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from banksia.platform.private_paths import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    protect_private_directory_descriptor,
    protect_private_file_descriptor,
)
from banksia.platform.workspace_files.contracts import (
    DirectoryLease,
    PosixPathIdentity,
    PrivatePathError,
    RegularFileLease,
)
from banksia.platform.workspace_files.posix_leases import (
    PosixDirectoryLease,
    PosixRegularFileLease,
    build_posix_directory_lease,
    move_descriptor_above_standard_streams,
    require_posix_directory_lease,
    require_posix_regular_file_lease,
)

_READ_CHUNK_BYTES = 64 * 1024
_TREE_REMOVAL_PASSES = 64


class PosixWorkspaceFileOperations:
    """Descriptor-relative Task workspace operations for Linux and macOS."""

    def open_workspace(self, path: Path) -> DirectoryLease:
        _require_posix_primitives()
        return _open_absolute_directory(path)

    def open_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
        *,
        should_require_private: bool,
    ) -> DirectoryLease:
        parent_lease = require_posix_directory_lease(parent)
        descriptor = os.open(
            name,
            _directory_open_flags(),
            dir_fd=parent_lease.descriptor,
        )
        try:
            if should_require_private:
                protect_private_directory_descriptor(descriptor)
            return build_posix_directory_lease(descriptor)
        except BaseException:
            os.close(descriptor)
            raise

    def create_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
    ) -> DirectoryLease:
        parent_lease = require_posix_directory_lease(parent)
        os.mkdir(name, PRIVATE_DIRECTORY_MODE, dir_fd=parent_lease.descriptor)
        try:
            return self.open_child_directory(parent, name, should_require_private=True)
        except BaseException:
            with suppress(OSError):
                os.rmdir(name, dir_fd=parent_lease.descriptor)
            raise

    def ensure_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
        *,
        should_require_private: bool,
    ) -> None:
        parent_lease = require_posix_directory_lease(parent)
        was_created = False
        try:
            os.mkdir(name, PRIVATE_DIRECTORY_MODE, dir_fd=parent_lease.descriptor)
            was_created = True
        except FileExistsError:
            pass
        child = self.open_child_directory(
            parent,
            name,
            should_require_private=should_require_private or was_created,
        )
        child.close()

    def write_new_text(
        self,
        parent: DirectoryLease,
        name: str,
        text: str,
    ) -> None:
        parent_lease = require_posix_directory_lease(parent)
        descriptor = os.open(
            name,
            _file_create_flags(),
            PRIVATE_FILE_MODE,
            dir_fd=parent_lease.descriptor,
        )
        try:
            protect_private_file_descriptor(descriptor)
            _write_text(descriptor, text)
        except BaseException:
            with suppress(OSError):
                os.unlink(name, dir_fd=parent_lease.descriptor)
            raise
        finally:
            os.close(descriptor)

    def replace_text(
        self,
        parent: DirectoryLease,
        name: str,
        text: str,
    ) -> None:
        parent_lease = require_posix_directory_lease(parent)
        _reject_unsafe_replace_target(parent_lease, name)
        temporary_name = f".{name}.{secrets.token_hex(8)}.repair"
        self.write_new_text(parent, temporary_name, text)
        try:
            os.replace(
                temporary_name,
                name,
                src_dir_fd=parent_lease.descriptor,
                dst_dir_fd=parent_lease.descriptor,
            )
            os.fsync(parent_lease.descriptor)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_lease.descriptor)
            raise

    def read_small_text(
        self,
        parent: DirectoryLease,
        name: str,
        *,
        byte_limit: int,
    ) -> str | None:
        parent_lease = require_posix_directory_lease(parent)
        try:
            descriptor = os.open(
                name,
                _regular_file_open_flags(),
                dir_fd=parent_lease.descriptor,
            )
        except OSError as exc:
            if exc.errno in {
                errno.ELOOP,
                errno.ENOENT,
                errno.EISDIR,
                errno.ENOTDIR,
            }:
                return None
            raise
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > byte_limit:
                return None
            payload = _read_bounded(descriptor, byte_limit + 1)
            if len(payload) > byte_limit:
                return None
            try:
                return payload.decode("utf-8", errors="strict")
            except UnicodeError:
                return None
        finally:
            os.close(descriptor)

    def unlink_entry(self, parent: DirectoryLease, name: str) -> None:
        os.unlink(name, dir_fd=require_posix_directory_lease(parent).descriptor)

    def list_directory_names(self, directory: DirectoryLease) -> tuple[str, ...]:
        return tuple(os.listdir(require_posix_directory_lease(directory).descriptor))

    def is_real_child_directory(self, parent: DirectoryLease, name: str) -> bool:
        parent_lease = require_posix_directory_lease(parent)
        try:
            metadata = os.stat(
                name,
                dir_fd=parent_lease.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        return stat.S_ISDIR(metadata.st_mode)

    def remove_retained_tree(
        self,
        parent: DirectoryLease,
        name: str,
        directory: DirectoryLease,
    ) -> bool:
        parent_lease = require_posix_directory_lease(parent)
        directory_lease = require_posix_directory_lease(directory)
        _remove_directory_contents(directory_lease)
        if not _child_matches_lease(parent_lease, name, directory_lease):
            raise PrivatePathError(
                errno.ESTALE,
                "retained Task directory changed name or identity before removal",
                name,
            )
        try:
            os.rmdir(name, dir_fd=parent_lease.descriptor)
        except FileNotFoundError:
            return False
        return True

    def open_regular_file(
        self,
        workspace: Path,
        components: tuple[str, ...],
    ) -> RegularFileLease:
        current = _open_absolute_directory(workspace)
        try:
            for component in components[:-1]:
                following = self.open_child_directory(
                    current,
                    component,
                    should_require_private=False,
                )
                current.close()
                current = require_posix_directory_lease(following)
            descriptor = os.open(
                components[-1],
                _regular_file_open_flags(),
                dir_fd=current.descriptor,
            )
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise PrivatePathError(
                        errno.EINVAL,
                        "workspace path is not a regular file",
                        components[-1],
                    )
                return PosixRegularFileLease(
                    descriptor,
                    PosixPathIdentity(metadata.st_dev, metadata.st_ino),
                )
            except BaseException:
                os.close(descriptor)
                raise
        finally:
            current.close()

    def read_regular_file_range(
        self,
        file: RegularFileLease,
        *,
        offset: int,
        byte_limit: int,
    ) -> tuple[bytes, int]:
        file_lease = require_posix_regular_file_lease(file)
        metadata = os.fstat(file_lease.descriptor)
        selected_offset = min(offset, metadata.st_size)
        os.lseek(file_lease.descriptor, selected_offset, os.SEEK_SET)
        payload = _read_bounded(file_lease.descriptor, byte_limit)
        return payload, os.fstat(file_lease.descriptor).st_size

    def open_command_directory(
        self,
        workspace: Path,
        components: tuple[str, ...],
    ) -> DirectoryLease:
        current = _open_absolute_directory(workspace)
        try:
            for component in components:
                following = self.open_child_directory(
                    current,
                    component,
                    should_require_private=False,
                )
                current.close()
                current = require_posix_directory_lease(following)
            return current
        except BaseException:
            current.close()
            raise

    def directory_descriptor(self, directory: DirectoryLease) -> int:
        return require_posix_directory_lease(directory).descriptor

    def create_output_descriptor(
        self,
        parent: DirectoryLease,
        name: str,
    ) -> int:
        parent_lease = require_posix_directory_lease(parent)
        descriptor = os.open(
            name,
            _file_create_flags(),
            PRIVATE_FILE_MODE,
            dir_fd=parent_lease.descriptor,
        )
        try:
            protect_private_file_descriptor(descriptor)
            descriptor = move_descriptor_above_standard_streams(descriptor)
            os.set_inheritable(descriptor, False)
            return descriptor
        except BaseException:
            os.close(descriptor)
            with suppress(OSError):
                os.unlink(name, dir_fd=parent_lease.descriptor)
            raise

    def append_text_line_locked(self, path: Path, line: str) -> None:
        parent, file_name = _open_absolute_parent(path)
        descriptor: int | None = None
        is_locked = False
        try:
            descriptor = os.open(
                file_name,
                _git_file_open_flags(),
                0o600,
                dir_fd=parent.descriptor,
            )
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PrivatePathError(
                    errno.EINVAL,
                    "Git exclude path is not a regular file",
                    path,
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            is_locked = True
            identity = PosixPathIdentity(metadata.st_dev, metadata.st_ino)
            _require_child_identity(parent, file_name, identity)
            current = _read_all(descriptor)
            encoded = line.encode("utf-8")
            if encoded in current.splitlines():
                return
            separator = b"\n" if current and not current.endswith(b"\n") else b""
            os.lseek(descriptor, 0, os.SEEK_END)
            _write_all(descriptor, separator + encoded + b"\n")
            os.fsync(descriptor)
            _require_child_identity(parent, file_name, identity)
        finally:
            if descriptor is not None:
                if is_locked:
                    with suppress(OSError):
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            parent.close()


def _open_absolute_parent(path: Path) -> tuple[PosixDirectoryLease, str]:
    if not path.is_absolute() or path == Path(path.anchor):
        raise PrivatePathError(errno.EINVAL, "path must name an absolute non-root file", path)
    return _open_absolute_directory(path.parent), path.name


def _open_absolute_directory(path: Path) -> PosixDirectoryLease:
    if not path.is_absolute():
        raise PrivatePathError(errno.EINVAL, "workspace path must be absolute", path)
    current = os.open(path.anchor, _directory_open_flags())
    try:
        for component in path.parts[1:]:
            following = os.open(
                component,
                _directory_open_flags(),
                dir_fd=current,
            )
            os.close(current)
            current = following
        return build_posix_directory_lease(current)
    except BaseException:
        os.close(current)
        raise


def _remove_directory_contents(directory: PosixDirectoryLease) -> None:
    for _attempt in range(_TREE_REMOVAL_PASSES):
        names = tuple(os.listdir(directory.descriptor))
        if not names:
            return
        for name in names:
            _remove_child_entry(directory, name)
    raise PrivatePathError(
        errno.EBUSY,
        "Task directory remained busy during bounded removal",
    )


def _remove_child_entry(parent: PosixDirectoryLease, name: str) -> None:
    try:
        metadata = os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if stat.S_ISDIR(metadata.st_mode):
        descriptor = os.open(
            name,
            _directory_open_flags(),
            dir_fd=parent.descriptor,
        )
        child = build_posix_directory_lease(descriptor)
        try:
            _remove_directory_contents(child)
            if not _child_matches_lease(parent, name, child):
                raise PrivatePathError(
                    errno.ESTALE,
                    "Task child directory changed identity during removal",
                    name,
                )
            os.rmdir(name, dir_fd=parent.descriptor)
        finally:
            child.close()
        return
    with suppress(FileNotFoundError):
        os.unlink(name, dir_fd=parent.descriptor)


def _child_matches_lease(
    parent: PosixDirectoryLease,
    name: str,
    child: PosixDirectoryLease,
) -> bool:
    try:
        metadata = os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_dev == child.identity.device
        and metadata.st_ino == child.identity.inode
    )


def _require_child_identity(
    parent: PosixDirectoryLease,
    name: str,
    identity: PosixPathIdentity,
) -> None:
    try:
        metadata = os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise PrivatePathError(
            errno.ESTALE,
            "filesystem entry changed while retained",
            name,
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_dev != identity.device
        or metadata.st_ino != identity.inode
    ):
        raise PrivatePathError(
            errno.ESTALE,
            "filesystem entry changed while retained",
            name,
        )


def _reject_unsafe_replace_target(
    parent: PosixDirectoryLease,
    name: str,
) -> None:
    try:
        metadata = os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        error_number = errno.ELOOP if stat.S_ISLNK(metadata.st_mode) else errno.EINVAL
        raise PrivatePathError(
            error_number,
            "refusing to replace a non-regular filesystem entry",
            name,
        )


def _write_text(descriptor: int, text: str) -> None:
    with os.fdopen(
        descriptor,
        "w",
        encoding="utf-8",
        newline="",
        closefd=False,
    ) as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def _read_bounded(descriptor: int, byte_limit: int) -> bytes:
    payload = bytearray()
    while len(payload) < byte_limit:
        chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, byte_limit - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
    return bytes(payload)


def _read_all(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    payload = bytearray()
    while True:
        chunk = os.read(descriptor, _READ_CHUNK_BYTES)
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError(errno.EIO, "filesystem write made no progress")
        remaining = remaining[written:]


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | _no_follow_flag() | getattr(os, "O_CLOEXEC", 0)


def _regular_file_open_flags() -> int:
    return (
        os.O_RDONLY | _no_follow_flag() | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    )


def _file_create_flags() -> int:
    return os.O_WRONLY | os.O_CREAT | os.O_EXCL | _no_follow_flag() | getattr(os, "O_CLOEXEC", 0)


def _git_file_open_flags() -> int:
    return (
        os.O_RDWR
        | os.O_CREAT
        | _no_follow_flag()
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _no_follow_flag() -> int:
    flag = getattr(os, "O_NOFOLLOW", None)
    if flag is None:
        raise PrivatePathError(
            errno.ENOTSUP,
            "this POSIX host cannot reject a final symlink for workspace files",
        )
    return int(flag)


def _require_posix_primitives() -> None:
    required = (
        os.name == "posix",
        hasattr(os, "O_DIRECTORY"),
        hasattr(os, "O_NOFOLLOW"),
        os.open in os.supports_dir_fd,
        os.mkdir in os.supports_dir_fd,
        os.stat in os.supports_dir_fd,
        os.stat in os.supports_follow_symlinks,
        os.unlink in os.supports_dir_fd,
    )
    if not all(required):
        raise PrivatePathError(
            errno.ENOTSUP,
            "safe descriptor-relative workspace operations are unavailable",
        )


__all__ = [
    "PosixDirectoryLease",
    "PosixRegularFileLease",
    "PosixWorkspaceFileOperations",
]
