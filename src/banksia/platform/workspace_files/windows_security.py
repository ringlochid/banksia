from __future__ import annotations

import errno
import os
from typing import Any

from banksia.platform.workspace_files.contracts import PrivatePathError


def protect_private_handle(handle: int) -> None:
    """Apply and verify a protected current-user plus SYSTEM DACL."""

    if os.name != "nt":
        raise PrivatePathError(errno.ENOTSUP, "Windows DACL operations are unavailable")

    import ntsecuritycon
    import win32api
    import win32con
    import win32security

    token: Any = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        current_user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        win32api.CloseHandle(int(token))
    system_user = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)

    dacl = win32security.ACL()
    for sid in (current_user, system_user):
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION_DS,
            0,
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
    get_security_info: Any = win32security.GetSecurityInfo
    descriptor = get_security_info(
        handle,
        win32security.SE_FILE_OBJECT,
        security_information,
    )
    observed = descriptor.GetSecurityDescriptorDacl()
    if observed is None or observed.GetAceCount() != 2:
        raise PrivatePathError(errno.EPERM, "private Windows path has an unexpected DACL")
    observed_sids = {str(observed.GetAce(index)[2]) for index in range(observed.GetAceCount())}
    expected_sids = {str(current_user), str(system_user)}
    if observed_sids != expected_sids:
        raise PrivatePathError(errno.EPERM, "private Windows path grants an unexpected identity")


__all__ = ["protect_private_handle"]
