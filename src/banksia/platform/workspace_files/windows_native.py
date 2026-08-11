from __future__ import annotations

import ctypes
import errno
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any, cast

from banksia.platform.workspace_files.contracts import (
    PrivatePathError,
    WindowsPathIdentity,
)

_ctypes_windows: Any = ctypes

FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

DELETE = 0x00010000
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
SYNCHRONIZE = 0x00100000
FILE_LIST_DIRECTORY = 0x00000001
FILE_READ_DATA = 0x00000001
FILE_WRITE_DATA = 0x00000002
FILE_APPEND_DATA = 0x00000004
FILE_ADD_FILE = 0x00000002
FILE_ADD_SUBDIRECTORY = 0x00000004
FILE_TRAVERSE = 0x00000020
FILE_DELETE_CHILD = 0x00000040
FILE_READ_ATTRIBUTES = 0x00000080
FILE_WRITE_ATTRIBUTES = 0x00000100

FILE_OPEN = 1
FILE_CREATE = 2
FILE_OPEN_IF = 3
FILE_DIRECTORY_FILE = 0x00000001
FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
FILE_NON_DIRECTORY_FILE = 0x00000040
FILE_OPEN_REPARSE_POINT = 0x00200000
OBJ_CASE_INSENSITIVE = 0x00000040

FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
FILE_ID_INFO_CLASS = 18
FILE_DISPOSITION_INFO_CLASS = 4
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _UnicodeString(ctypes.Structure):
    _fields_ = (
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    )


class _ObjectAttributes(ctypes.Structure):
    _fields_ = (
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", wintypes.LPVOID),
        ("SecurityQualityOfService", wintypes.LPVOID),
    )


class _IoStatusBlock(ctypes.Structure):
    _fields_ = (("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t))


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = (("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD))


class _FileId128(ctypes.Structure):
    _fields_ = (("Identifier", ctypes.c_ubyte * 16),)


class _FileIdInfo(ctypes.Structure):
    _fields_ = (("VolumeSerialNumber", ctypes.c_ulonglong), ("FileId", _FileId128))


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = (("DeleteFile", wintypes.BOOL),)


def open_absolute_directory(path: Path, *, should_allow_mutation: bool = False) -> int:
    """Open an existing local directory without following its final reparse point."""

    normalized = require_local_absolute_path(path)
    create_file = _kernel32_function("CreateFileW")
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    desired_access = (
        FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE
    )
    if should_allow_mutation:
        desired_access |= (
            FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY | FILE_DELETE_CHILD | FILE_WRITE_ATTRIBUTES
        )
    handle = create_file(
        str(normalized),
        desired_access,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle in {None, INVALID_HANDLE_VALUE}:
        raise _windows_error(path=str(normalized))
    selected = int(handle)
    try:
        _require_handle_kind(selected, should_be_directory=True)
        return selected
    except BaseException:
        close_handle(selected)
        raise


def open_relative_entry(
    parent_handle: int,
    name: str,
    *,
    should_be_directory: bool | None,
    should_create: bool = False,
    should_open_if: bool = False,
    should_allow_reparse: bool = False,
    should_allow_mutation: bool = False,
    should_allow_security_update: bool = False,
    should_allow_delete: bool = False,
) -> int:
    """Open or create one component relative to a retained Windows directory handle."""

    require_component_name(name)
    encoded_length = len(name.encode("utf-16-le"))
    if encoded_length > 65_532:
        raise PrivatePathError(errno.ENAMETOOLONG, "Windows path component is too long", name)
    name_buffer = ctypes.create_unicode_buffer(name)
    unicode_name = _UnicodeString(
        Length=encoded_length,
        MaximumLength=encoded_length + 2,
        Buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        Length=ctypes.sizeof(_ObjectAttributes),
        RootDirectory=parent_handle,
        ObjectName=ctypes.pointer(unicode_name),
        Attributes=OBJ_CASE_INSENSITIVE,
        SecurityDescriptor=None,
        SecurityQualityOfService=None,
    )
    desired_access, options, disposition = _relative_open_contract(
        should_be_directory=should_be_directory,
        should_create=should_create,
        should_open_if=should_open_if,
        should_allow_mutation=should_allow_mutation,
        should_allow_security_update=should_allow_security_update,
        should_allow_delete=should_allow_delete,
    )
    selected = _create_relative_handle(
        attributes,
        desired_access=desired_access,
        disposition=disposition,
        options=options,
        name=name,
    )
    try:
        _require_handle_kind(
            selected,
            should_be_directory=should_be_directory,
            should_allow_reparse=should_allow_reparse,
        )
        return selected
    except BaseException:
        close_handle(selected)
        raise


def read_handle_attributes(handle: int) -> tuple[bool, bool]:
    information = _FileAttributeTagInfo()
    get_information = _kernel32_function("GetFileInformationByHandleEx")
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    if not get_information(
        handle,
        FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise _windows_error()
    return (
        bool(information.FileAttributes & FILE_ATTRIBUTE_DIRECTORY),
        bool(information.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT),
    )


def read_handle_identity(handle: int) -> WindowsPathIdentity:
    information = _FileIdInfo()
    get_information = _kernel32_function("GetFileInformationByHandleEx")
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    if not get_information(
        handle,
        FILE_ID_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise _windows_error()
    return WindowsPathIdentity(
        volume_serial=int(information.VolumeSerialNumber),
        file_id=bytes(information.FileId.Identifier),
    )


def read_handle_path(handle: int) -> Path:
    get_final_path = _kernel32_function("GetFinalPathNameByHandleW")
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    size = 512
    while size <= 32_768:
        buffer = ctypes.create_unicode_buffer(size)
        written = int(get_final_path(handle, buffer, size, 0))
        if written == 0:
            raise _windows_error()
        if written < size:
            value = buffer.value
            if value.startswith("\\\\?\\UNC\\"):
                raise PrivatePathError(errno.ENOTSUP, "UNC workspaces are unsupported")
            return Path(value.removeprefix("\\\\?\\"))
        size = written + 1
    raise PrivatePathError(errno.ENAMETOOLONG, "Windows final path exceeded its bound")


def mark_handle_for_deletion(handle: int) -> None:
    disposition = _FileDispositionInfo(DeleteFile=True)
    set_information = _kernel32_function("SetFileInformationByHandle")
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL
    if not set_information(
        handle,
        FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise _windows_error()


def write_handle(handle: int, payload: bytes) -> None:
    write_file = _kernel32_function("WriteFile")
    write_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    write_file.restype = wintypes.BOOL
    offset = 0
    while offset < len(payload):
        chunk = payload[offset : offset + 64 * 1024]
        buffer = ctypes.create_string_buffer(chunk)
        written = wintypes.DWORD()
        if not write_file(handle, buffer, len(chunk), ctypes.byref(written), None):
            raise _windows_error()
        if written.value == 0:
            raise OSError(errno.EIO, "Windows file write made no progress")
        offset += int(written.value)
    flush_handle(handle)


def read_handle_range(handle: int, *, offset: int, byte_limit: int) -> tuple[bytes, int]:
    size = ctypes.c_longlong()
    get_size = _kernel32_function("GetFileSizeEx")
    get_size.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
    get_size.restype = wintypes.BOOL
    if not get_size(handle, ctypes.byref(size)):
        raise _windows_error()
    selected_offset = min(offset, int(size.value))
    new_position = ctypes.c_longlong()
    set_pointer = _kernel32_function("SetFilePointerEx")
    set_pointer.argtypes = (
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    )
    set_pointer.restype = wintypes.BOOL
    if not set_pointer(handle, selected_offset, ctypes.byref(new_position), 0):
        raise _windows_error()
    read_file = _kernel32_function("ReadFile")
    read_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    read_file.restype = wintypes.BOOL
    payload = bytearray()
    while len(payload) < byte_limit:
        requested = min(64 * 1024, byte_limit - len(payload))
        buffer = ctypes.create_string_buffer(requested)
        read = wintypes.DWORD()
        if not read_file(handle, buffer, requested, ctypes.byref(read), None):
            raise _windows_error()
        if read.value == 0:
            break
        payload.extend(buffer.raw[: read.value])
    if not get_size(handle, ctypes.byref(size)):
        raise _windows_error()
    return bytes(payload), int(size.value)


def flush_handle(handle: int) -> None:
    flush = _kernel32_function("FlushFileBuffers")
    flush.argtypes = (wintypes.HANDLE,)
    flush.restype = wintypes.BOOL
    if not flush(handle):
        raise _windows_error()


def close_handle(handle: int) -> None:
    close = _kernel32_function("CloseHandle")
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    if not close(handle):
        raise _windows_error()


def require_ntfs(path: Path) -> None:
    normalized = require_local_absolute_path(path)
    volume_path = ctypes.create_unicode_buffer(260)
    get_volume_path = _kernel32_function("GetVolumePathNameW")
    get_volume_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_volume_path.restype = wintypes.BOOL
    if not get_volume_path(str(normalized), volume_path, len(volume_path)):
        raise _windows_error(path=str(normalized))
    filesystem = ctypes.create_unicode_buffer(32)
    get_volume_information = _kernel32_function("GetVolumeInformationW")
    get_volume_information.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_volume_information.restype = wintypes.BOOL
    if not get_volume_information(
        volume_path.value,
        None,
        0,
        None,
        None,
        None,
        filesystem,
        len(filesystem),
    ):
        raise _windows_error(path=str(normalized))
    if filesystem.value.casefold() != "ntfs":
        raise PrivatePathError(
            errno.ENOTSUP,
            f"Banksia requires NTFS on Windows; found {filesystem.value or 'unknown'}",
            normalized,
        )


def require_local_absolute_path(path: Path) -> Path:
    expanded = path.expanduser().absolute()
    value = str(expanded)
    if not expanded.is_absolute() or value.startswith(("\\\\", "\\?\\", "\\.\\")):
        raise PrivatePathError(errno.EINVAL, "Windows path must be local and absolute", path)
    if len(expanded.drive) != 2 or expanded.drive[1:] != ":":
        raise PrivatePathError(errno.EINVAL, "Windows path must use a local drive", path)
    return expanded


def require_component_name(name: str) -> None:
    if (
        not name
        or name in {".", ".."}
        or any(character in name for character in "\\/:\x00")
        or name[-1] in {" ", "."}
    ):
        raise PrivatePathError(errno.EINVAL, "invalid Windows path component", name)


def _kernel32_function(name: str) -> Any:
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "Windows filesystem APIs are unavailable")
    return getattr(_ctypes_windows.WinDLL("kernel32", use_last_error=True), name)


def _ntdll_function(name: str) -> Any:
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "Windows native filesystem APIs are unavailable")
    return getattr(_ctypes_windows.WinDLL("ntdll", use_last_error=True), name)


def _windows_error(error_number: int | None = None, path: str | None = None) -> OSError:
    if error_number is None:
        error_number = int(_ctypes_windows.get_last_error())
    return cast(OSError, _ctypes_windows.WinError(error_number, path))


def _require_handle_kind(
    handle: int,
    *,
    should_be_directory: bool | None,
    should_allow_reparse: bool = False,
) -> None:
    is_directory, is_reparse = read_handle_attributes(handle)
    if is_reparse and not should_allow_reparse:
        raise PrivatePathError(errno.ELOOP, "Windows path contains a reparse point")
    if should_be_directory is True and not is_directory:
        raise NotADirectoryError(errno.ENOTDIR, "Windows path is not a directory")
    if should_be_directory is False and is_directory:
        raise IsADirectoryError(errno.EISDIR, "Windows path is not a regular file")


def _relative_open_contract(
    *,
    should_be_directory: bool | None,
    should_create: bool,
    should_open_if: bool,
    should_allow_mutation: bool,
    should_allow_security_update: bool,
    should_allow_delete: bool,
) -> tuple[int, int, int]:
    desired_access = FILE_READ_ATTRIBUTES | SYNCHRONIZE
    options = FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT
    if should_be_directory is True:
        desired_access |= FILE_LIST_DIRECTORY | FILE_TRAVERSE
        options |= FILE_DIRECTORY_FILE
    elif should_be_directory is False:
        desired_access |= FILE_READ_DATA
        options |= FILE_NON_DIRECTORY_FILE
    else:
        desired_access |= FILE_READ_DATA | FILE_LIST_DIRECTORY
    if should_allow_mutation or should_create or should_open_if:
        desired_access |= FILE_WRITE_ATTRIBUTES
        if should_be_directory is not False:
            desired_access |= FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY | FILE_DELETE_CHILD
        if should_be_directory is not True:
            desired_access |= FILE_WRITE_DATA | FILE_APPEND_DATA
    if should_allow_security_update or should_create or should_open_if:
        desired_access |= READ_CONTROL | WRITE_DAC
    if should_allow_delete:
        desired_access |= DELETE
    disposition = FILE_OPEN_IF if should_open_if else FILE_CREATE if should_create else FILE_OPEN
    return desired_access, options, disposition


def _create_relative_handle(
    attributes: _ObjectAttributes,
    *,
    desired_access: int,
    disposition: int,
    options: int,
    name: str,
) -> int:
    status_block = _IoStatusBlock()
    nt_create_file = _ntdll_function("NtCreateFile")
    nt_create_file.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    nt_create_file.restype = wintypes.LONG
    handle = wintypes.HANDLE()
    status = int(
        nt_create_file(
            ctypes.byref(handle),
            desired_access,
            ctypes.byref(attributes),
            ctypes.byref(status_block),
            None,
            FILE_ATTRIBUTE_NORMAL,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            disposition,
            options,
            None,
            0,
        )
    )
    if status < 0:
        _raise_ntstatus(status, name)
    selected = int(handle.value or 0)
    if selected == 0:
        raise _windows_error(path=name)
    return selected


def _raise_ntstatus(status: int, path: str) -> None:
    rtl_error = _ntdll_function("RtlNtStatusToDosError")
    rtl_error.argtypes = (wintypes.LONG,)
    rtl_error.restype = wintypes.ULONG
    error_number = int(rtl_error(status))
    if error_number in {2, 3}:
        raise FileNotFoundError(error_number, os.strerror(error_number), path)
    if error_number in {80, 183}:
        raise FileExistsError(error_number, os.strerror(error_number), path)
    if error_number == 267:
        raise NotADirectoryError(error_number, os.strerror(error_number), path)
    raise _windows_error(error_number, path)


__all__ = [
    "close_handle",
    "mark_handle_for_deletion",
    "open_absolute_directory",
    "open_relative_entry",
    "read_handle_attributes",
    "read_handle_identity",
    "read_handle_path",
    "read_handle_range",
    "require_component_name",
    "require_local_absolute_path",
    "require_ntfs",
    "write_handle",
]
