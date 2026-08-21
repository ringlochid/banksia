from __future__ import annotations

import errno
import os
from typing import Any

from oh_my_subagents.platform.workspace_files.contracts import PrivatePathError


def protect_private_handle(handle: int, *, is_directory: bool) -> None:
    """Apply and verify a protected current-user plus SYSTEM DACL."""

    if os.name != "nt":
        raise PrivatePathError(errno.ENOTSUP, "Windows DACL operations are unavailable")

    import ntsecuritycon
    import win32con
    import win32security

    current_user, system_user = _private_sids()

    dacl = win32security.ACL()
    inheritance_flags = (
        win32con.CONTAINER_INHERIT_ACE | win32con.OBJECT_INHERIT_ACE if is_directory else 0
    )
    for sid in (current_user, system_user):
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION_DS,
            inheritance_flags,
            ntsecuritycon.FILE_ALL_ACCESS,
            sid,
        )
    security_information = (
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION
    )
    set_security_info: Any = win32security.SetSecurityInfo
    set_security_info(
        handle,
        win32security.SE_FILE_OBJECT,
        security_information,
        None,
        None,
        dacl,
        None,
    )
    verify_private_handle(handle, is_directory=is_directory)


def verify_private_handle(handle: int, *, is_directory: bool) -> None:
    """Verify an existing private DACL without changing the filesystem object."""

    if os.name != "nt":
        raise PrivatePathError(errno.ENOTSUP, "Windows DACL operations are unavailable")

    import ntsecuritycon
    import win32con
    import win32security

    current_user, system_user = _private_sids()
    get_security_info: Any = win32security.GetSecurityInfo
    descriptor = get_security_info(
        handle,
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
    )
    observed = descriptor.GetSecurityDescriptorDacl()
    if observed is None or observed.GetAceCount() != 2:
        raise PrivatePathError(errno.EPERM, "private Windows path has an unexpected DACL")
    control, _revision = descriptor.GetSecurityDescriptorControl()
    protected_dacl = getattr(win32security, "SE_DACL_PROTECTED", 0x1000)
    if not control & protected_dacl:
        raise PrivatePathError(errno.EPERM, "private Windows path has an inherited DACL")
    expected_flags = (
        win32con.CONTAINER_INHERIT_ACE | win32con.OBJECT_INHERIT_ACE if is_directory else 0
    )
    observed_sids: set[str] = set()
    for index in range(observed.GetAceCount()):
        header, access_mask, sid = observed.GetAce(index)
        ace_type, ace_flags = header
        if (
            ace_type != win32security.ACCESS_ALLOWED_ACE_TYPE
            or ace_flags != expected_flags
            or access_mask != ntsecuritycon.FILE_ALL_ACCESS
        ):
            raise PrivatePathError(errno.EPERM, "private Windows path has unexpected access")
        observed_sids.add(str(sid))
    expected_sids = {str(current_user), str(system_user)}
    if observed_sids != expected_sids:
        raise PrivatePathError(errno.EPERM, "private Windows path grants an unexpected identity")


def _private_sids() -> tuple[Any, Any]:
    if os.name != "nt":
        raise PrivatePathError(errno.ENOTSUP, "Windows DACL operations are unavailable")

    import win32api
    import win32con
    import win32security

    token: Any = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        current_user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        win32api.CloseHandle(int(token))
    system_user = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    return current_user, system_user


__all__ = ["protect_private_handle", "verify_private_handle"]
