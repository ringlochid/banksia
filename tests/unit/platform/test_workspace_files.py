from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from banksia.paths import default_database_path, default_database_url
from banksia.platform.workspace_files import (
    PrivatePathError,
    select_workspace_file_operations,
)


def test_workspace_backend_selection_has_no_unsupported_fallback() -> None:
    expected_name = (
        "WindowsWorkspaceFileOperations" if os.name == "nt" else "PosixWorkspaceFileOperations"
    )
    assert type(select_workspace_file_operations()).__name__ == expected_name
    with pytest.raises(PrivatePathError, match="Linux, macOS, and Windows only"):
        select_workspace_file_operations("unsupported")


def test_default_sqlite_url_uses_sqlalchemy_portable_path(
    tmp_path: Path,
) -> None:
    url = make_url(default_database_url(tmp_path))

    assert url.drivername == "sqlite+aiosqlite"
    assert url.database == default_database_path(tmp_path).as_posix()
