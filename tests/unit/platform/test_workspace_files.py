from __future__ import annotations

import pytest

from banksia.platform.workspace_files import (
    PrivatePathError,
    select_workspace_file_operations,
)


def test_workspace_backend_selection_has_no_unsupported_fallback() -> None:
    assert (
        type(select_workspace_file_operations("posix")).__name__ == "PosixWorkspaceFileOperations"
    )
    with pytest.raises(PrivatePathError, match="Linux and macOS only"):
        select_workspace_file_operations("nt")
