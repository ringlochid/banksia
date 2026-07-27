from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from banksia.platform.workspace_files.contracts import PrivatePathError

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_MACOS_ACL_TYPE_EXTENDED = 0x00000100
_MACOS_ACL_FIRST_ENTRY = 0


def protect_private_directory_descriptor(descriptor: int) -> None:
    """Apply and verify owner-only protection on an open Banksia directory."""

    _require_posix_descriptor_policy()
    _protect_posix_descriptor(
        descriptor,
        expected_mode=PRIVATE_DIRECTORY_MODE,
        expected_file_kind=stat.S_ISDIR,
    )


def protect_private_file_descriptor(descriptor: int) -> None:
    """Apply and verify owner-only protection on an open Banksia file."""

    _require_posix_descriptor_policy()
    _protect_posix_descriptor(
        descriptor,
        expected_mode=PRIVATE_FILE_MODE,
        expected_file_kind=stat.S_ISREG,
    )


def protect_private_path(path: Path, *, is_directory: bool) -> None:
    """Open one real Banksia-owned path and prove its private access policy."""

    from banksia.platform.workspace_files.selection import (
        protect_private_path as protect_selected_private_path,
    )

    protect_selected_private_path(path, is_directory=is_directory)


def _protect_posix_descriptor(
    descriptor: int,
    *,
    expected_mode: int,
    expected_file_kind: Callable[[int], bool],
) -> None:
    metadata = os.fstat(descriptor)
    if not expected_file_kind(metadata.st_mode):
        raise PrivatePathError(errno.EINVAL, "private Banksia path has the wrong file type")
    if metadata.st_uid != os.geteuid():
        raise PrivatePathError(errno.EPERM, "private Banksia path is owned by another user")

    os.fchmod(descriptor, expected_mode)
    if sys.platform == "darwin":
        _clear_macos_extended_acl(descriptor)
    metadata = os.fstat(descriptor)
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise PrivatePathError(
            errno.EPERM,
            "private Banksia path does not enforce owner-only permissions",
        )


def _require_posix_descriptor_policy() -> None:
    if os.name != "posix" or not hasattr(os, "fchmod") or not hasattr(os, "geteuid"):
        raise PrivatePathError(
            errno.ENOTSUP,
            "owner-only POSIX descriptor permissions are unavailable",
        )


def _clear_macos_extended_acl(descriptor: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    acl_init = libc.acl_init
    acl_init.argtypes = (ctypes.c_int,)
    acl_init.restype = ctypes.c_void_p
    acl_set_fd_np = libc.acl_set_fd_np
    acl_set_fd_np.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
    acl_set_fd_np.restype = ctypes.c_int
    acl_get_fd_np = libc.acl_get_fd_np
    acl_get_fd_np.argtypes = (ctypes.c_int, ctypes.c_int)
    acl_get_fd_np.restype = ctypes.c_void_p
    acl_get_entry = libc.acl_get_entry
    acl_get_entry.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
    )
    acl_get_entry.restype = ctypes.c_int
    acl_free = libc.acl_free
    acl_free.argtypes = (ctypes.c_void_p,)
    acl_free.restype = ctypes.c_int

    empty_acl = acl_init(0)
    if not empty_acl:
        _raise_macos_acl_error("could not allocate an empty macOS ACL")
    try:
        if acl_set_fd_np(descriptor, empty_acl, _MACOS_ACL_TYPE_EXTENDED) != 0:
            _raise_macos_acl_error("could not remove inherited macOS ACL entries")
    finally:
        acl_free(empty_acl)

    ctypes.set_errno(0)
    current_acl = acl_get_fd_np(descriptor, _MACOS_ACL_TYPE_EXTENDED)
    if not current_acl:
        error_number = ctypes.get_errno()
        if error_number:
            _raise_macos_acl_error("could not verify the macOS ACL")
        return
    try:
        entry = ctypes.c_void_p()
        ctypes.set_errno(0)
        result = acl_get_entry(current_acl, _MACOS_ACL_FIRST_ENTRY, ctypes.byref(entry))
        if result == 0:
            raise PrivatePathError(
                errno.EPERM,
                "private Banksia path retains a macOS ACL entry",
            )
        if ctypes.get_errno() not in {0, errno.EINVAL}:
            _raise_macos_acl_error("could not inspect the macOS ACL")
    finally:
        acl_free(current_acl)


def _raise_macos_acl_error(summary: str) -> None:
    error_number = ctypes.get_errno() or errno.EPERM
    raise PrivatePathError(error_number, summary)


__all__ = [
    "PRIVATE_DIRECTORY_MODE",
    "PRIVATE_FILE_MODE",
    "PrivatePathError",
    "protect_private_directory_descriptor",
    "protect_private_file_descriptor",
    "protect_private_path",
]
