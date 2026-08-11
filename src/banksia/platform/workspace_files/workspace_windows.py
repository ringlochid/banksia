from __future__ import annotations

import errno
import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from banksia.platform.workspace_files.contracts import (
    DirectoryLease,
    PrivatePathError,
    RegularFileLease,
    WindowsPathIdentity,
)
from banksia.platform.workspace_files.windows_native import (
    close_handle,
    mark_handle_for_deletion,
    open_absolute_directory,
    open_relative_entry,
    read_handle_attributes,
    read_handle_identity,
    read_handle_path,
    read_handle_range,
    require_component_name,
    require_local_absolute_path,
    require_ntfs,
    write_handle,
)
from banksia.platform.workspace_files.windows_security import protect_private_handle

_TREE_REMOVAL_PASSES = 64


@dataclass(slots=True)
class WindowsDirectoryLease:
    _handle: int | None
    identity: WindowsPathIdentity

    @property
    def native_handle(self) -> int:
        if self._handle is None:
            raise RuntimeError("Windows directory lease is closed")
        return self._handle

    @property
    def path(self) -> Path:
        return read_handle_path(self.native_handle)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            close_handle(handle)


@dataclass(slots=True)
class WindowsRegularFileLease:
    _handle: int | None
    identity: WindowsPathIdentity

    @property
    def native_handle(self) -> int:
        if self._handle is None:
            raise RuntimeError("Windows regular-file lease is closed")
        return self._handle

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            close_handle(handle)


class WindowsWorkspaceFileOperations:
    """Handle-relative Task workspace operations for local Windows NTFS paths."""

    def open_workspace(self, path: Path) -> DirectoryLease:
        normalized = require_local_absolute_path(path)
        require_ntfs(normalized)
        current = _build_directory_lease(open_absolute_directory(Path(normalized.anchor)))
        try:
            components = normalized.parts[1:]
            if not components:
                current.close()
                return _build_directory_lease(
                    open_absolute_directory(normalized, should_allow_mutation=True)
                )
            for index, component in enumerate(components):
                handle = open_relative_entry(
                    current.native_handle,
                    component,
                    should_be_directory=True,
                    should_allow_mutation=index == len(components) - 1,
                )
                following = _build_directory_lease(handle)
                current.close()
                current = following
            return current
        except BaseException:
            current.close()
            raise

    def open_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
        *,
        should_require_private: bool,
    ) -> DirectoryLease:
        handle = open_relative_entry(
            require_windows_directory_lease(parent).native_handle,
            name,
            should_be_directory=True,
            should_allow_mutation=should_require_private,
            should_allow_security_update=should_require_private,
        )
        try:
            if should_require_private:
                protect_private_handle(handle)
            return _build_directory_lease(handle)
        except BaseException:
            close_handle(handle)
            raise

    def create_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
    ) -> DirectoryLease:
        handle = open_relative_entry(
            require_windows_directory_lease(parent).native_handle,
            name,
            should_be_directory=True,
            should_create=True,
            should_allow_mutation=True,
            should_allow_security_update=True,
            should_allow_delete=True,
        )
        try:
            protect_private_handle(handle)
            return _build_directory_lease(handle)
        except BaseException:
            with suppress(OSError):
                mark_handle_for_deletion(handle)
            close_handle(handle)
            raise

    def ensure_child_directory(
        self,
        parent: DirectoryLease,
        name: str,
        *,
        should_require_private: bool,
    ) -> None:
        try:
            child = self.create_child_directory(parent, name)
        except FileExistsError:
            child = self.open_child_directory(
                parent,
                name,
                should_require_private=should_require_private,
            )
        child.close()

    def write_new_text(
        self,
        parent: DirectoryLease,
        name: str,
        text: str,
    ) -> None:
        handle = self._create_private_file(parent, name)
        try:
            write_handle(handle, text.encode("utf-8"))
        except BaseException:
            with suppress(OSError):
                mark_handle_for_deletion(handle)
            raise
        finally:
            close_handle(handle)

    def replace_text(
        self,
        parent: DirectoryLease,
        name: str,
        text: str,
    ) -> None:
        parent_lease = require_windows_directory_lease(parent)
        require_component_name(name)
        self._reject_unsafe_replace_target(parent_lease, name)
        temporary_name = f".{name}.{secrets.token_hex(8)}.repair"
        self.write_new_text(parent, temporary_name, text)
        parent_path = parent_lease.path
        self._require_unchanged(parent_lease)
        try:
            os.replace(parent_path / temporary_name, parent_path / name)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(parent_path / temporary_name)
            raise
        self._require_unchanged(parent_lease)

    def read_small_text(
        self,
        parent: DirectoryLease,
        name: str,
        *,
        byte_limit: int,
    ) -> str | None:
        try:
            handle = open_relative_entry(
                require_windows_directory_lease(parent).native_handle,
                name,
                should_be_directory=False,
            )
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError, PrivatePathError):
            return None
        try:
            payload, file_size = read_handle_range(handle, offset=0, byte_limit=byte_limit + 1)
            if file_size > byte_limit or len(payload) > byte_limit:
                return None
            try:
                return payload.decode("utf-8", errors="strict")
            except UnicodeError:
                return None
        finally:
            close_handle(handle)

    def unlink_entry(self, parent: DirectoryLease, name: str) -> None:
        handle = open_relative_entry(
            require_windows_directory_lease(parent).native_handle,
            name,
            should_be_directory=None,
            should_allow_reparse=True,
            should_allow_delete=True,
        )
        try:
            mark_handle_for_deletion(handle)
        finally:
            close_handle(handle)

    def list_directory_names(self, directory: DirectoryLease) -> tuple[str, ...]:
        lease = require_windows_directory_lease(directory)
        self._require_unchanged(lease)
        names = tuple(os.listdir(lease.path))
        self._require_unchanged(lease)
        return names

    def is_real_child_directory(self, parent: DirectoryLease, name: str) -> bool:
        try:
            child = self.open_child_directory(
                parent,
                name,
                should_require_private=False,
            )
        except (FileNotFoundError, NotADirectoryError, PrivatePathError):
            return False
        child.close()
        return True

    def remove_retained_tree(
        self,
        parent: DirectoryLease,
        name: str,
        directory: DirectoryLease,
    ) -> bool:
        parent_lease = require_windows_directory_lease(parent)
        directory_lease = require_windows_directory_lease(directory)
        self._remove_directory_contents(directory_lease)
        current = open_relative_entry(
            parent_lease.native_handle,
            name,
            should_be_directory=True,
            should_allow_delete=True,
        )
        try:
            if read_handle_identity(current) != directory_lease.identity:
                raise PrivatePathError(
                    errno.ESTALE,
                    "retained Task directory changed name or identity before removal",
                    name,
                )
            try:
                mark_handle_for_deletion(current)
            except FileNotFoundError:
                return False
        finally:
            close_handle(current)
        return True

    def open_regular_file(
        self,
        workspace: Path,
        components: tuple[str, ...],
    ) -> RegularFileLease:
        if not components:
            raise PrivatePathError(errno.EINVAL, "workspace file path is empty")
        current = require_windows_directory_lease(self.open_workspace(workspace))
        try:
            for component in components[:-1]:
                following = self.open_child_directory(
                    current,
                    component,
                    should_require_private=False,
                )
                current.close()
                current = require_windows_directory_lease(following)
            handle = open_relative_entry(
                current.native_handle,
                components[-1],
                should_be_directory=False,
            )
            return WindowsRegularFileLease(handle, read_handle_identity(handle))
        finally:
            current.close()

    def read_regular_file_range(
        self,
        file: RegularFileLease,
        *,
        offset: int,
        byte_limit: int,
    ) -> tuple[bytes, int]:
        return read_handle_range(
            require_windows_regular_file_lease(file).native_handle,
            offset=offset,
            byte_limit=byte_limit,
        )

    def open_command_directory(
        self,
        workspace: Path,
        components: tuple[str, ...],
    ) -> DirectoryLease:
        current = require_windows_directory_lease(self.open_workspace(workspace))
        try:
            for component in components:
                following = self.open_child_directory(
                    current,
                    component,
                    should_require_private=False,
                )
                current.close()
                current = require_windows_directory_lease(following)
            return current
        except BaseException:
            current.close()
            raise

    def create_output_descriptor(
        self,
        parent: DirectoryLease,
        name: str,
    ) -> int:
        handle = self._create_private_file(parent, name)
        try:
            import msvcrt

            msvcrt_module: Any = msvcrt
            descriptor = int(
                msvcrt_module.open_osfhandle(
                    handle,
                    os.O_WRONLY | getattr(os, "O_BINARY", 0),
                )
            )
        except BaseException:
            with suppress(OSError):
                mark_handle_for_deletion(handle)
            close_handle(handle)
            raise
        return descriptor

    def _create_private_file(self, parent: DirectoryLease, name: str) -> int:
        handle = open_relative_entry(
            require_windows_directory_lease(parent).native_handle,
            name,
            should_be_directory=False,
            should_create=True,
            should_allow_mutation=True,
            should_allow_security_update=True,
            should_allow_delete=True,
        )
        try:
            protect_private_handle(handle)
            return handle
        except BaseException:
            with suppress(OSError):
                mark_handle_for_deletion(handle)
            close_handle(handle)
            raise

    def _reject_unsafe_replace_target(
        self,
        parent: WindowsDirectoryLease,
        name: str,
    ) -> None:
        try:
            handle = open_relative_entry(
                parent.native_handle,
                name,
                should_be_directory=False,
            )
        except FileNotFoundError:
            return
        close_handle(handle)

    def _remove_directory_contents(self, directory: WindowsDirectoryLease) -> None:
        for _attempt in range(_TREE_REMOVAL_PASSES):
            names = self.list_directory_names(directory)
            if not names:
                return
            for name in names:
                self._remove_child_entry(directory, name)
        raise PrivatePathError(errno.EBUSY, "Task directory remained busy during bounded removal")

    def _remove_child_entry(self, parent: WindowsDirectoryLease, name: str) -> None:
        try:
            handle = open_relative_entry(
                parent.native_handle,
                name,
                should_be_directory=None,
                should_allow_reparse=True,
                should_allow_delete=True,
            )
        except FileNotFoundError:
            return
        try:
            is_directory, is_reparse = read_handle_attributes(handle)
            if is_directory and not is_reparse:
                child = _build_directory_lease(handle)
                handle = 0
                try:
                    self._remove_directory_contents(child)
                    mark_handle_for_deletion(child.native_handle)
                finally:
                    child.close()
            else:
                mark_handle_for_deletion(handle)
        finally:
            if handle:
                close_handle(handle)

    @staticmethod
    def _require_unchanged(lease: WindowsDirectoryLease) -> None:
        if read_handle_identity(lease.native_handle) != lease.identity:
            raise PrivatePathError(errno.ESTALE, "retained Windows directory changed identity")


def require_windows_directory_lease(directory: DirectoryLease) -> WindowsDirectoryLease:
    if not isinstance(directory, WindowsDirectoryLease):
        raise TypeError("directory lease does not belong to the Windows workspace backend")
    return directory


def require_windows_regular_file_lease(file: RegularFileLease) -> WindowsRegularFileLease:
    if not isinstance(file, WindowsRegularFileLease):
        raise TypeError("regular-file lease does not belong to the Windows workspace backend")
    return file


def _build_directory_lease(handle: int) -> WindowsDirectoryLease:
    return WindowsDirectoryLease(handle, read_handle_identity(handle))


__all__ = [
    "WindowsDirectoryLease",
    "WindowsRegularFileLease",
    "WindowsWorkspaceFileOperations",
    "require_windows_directory_lease",
    "require_windows_regular_file_lease",
]
