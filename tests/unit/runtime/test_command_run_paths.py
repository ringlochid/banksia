from __future__ import annotations

from pathlib import Path

import pytest

from oh_my_subagents.platform.workspace_files import PrivatePathError
from oh_my_subagents.runtime.command_run.task_paths import (
    close_command_working_directory,
    open_stable_command_working_directory,
)


def test_stable_command_working_directory_keeps_admitted_identity(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    admitted = workspace / "admitted"
    admitted.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    working_directory = open_stable_command_working_directory(
        workspace,
        "admitted",
    )

    moved = workspace / "admitted-after-rename"
    admitted.rename(moved)
    admitted.symlink_to(outside, target_is_directory=True)
    try:
        moved_directory = open_stable_command_working_directory(workspace, moved.name)
        outside_directory = open_stable_command_working_directory(tmp_path, outside.name)
        try:
            assert working_directory.directory.identity == moved_directory.directory.identity
            assert working_directory.directory.identity != outside_directory.directory.identity
        finally:
            close_command_working_directory(moved_directory)
            close_command_working_directory(outside_directory)
    finally:
        close_command_working_directory(working_directory)


def test_stable_command_working_directory_rejects_symlink_component(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises((NotADirectoryError, PrivatePathError)):
        open_stable_command_working_directory(
            workspace,
            "linked",
        )


@pytest.mark.parametrize("cwd", ("", "..", "../outside", "/tmp", "C:/tmp", "a//b", "./a"))
def test_stable_command_working_directory_rejects_unsafe_relative_path(
    tmp_path: Path,
    cwd: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError, match="workspace-relative"):
        open_stable_command_working_directory(workspace, cwd)


def test_stable_command_working_directory_accepts_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    working_directory = open_stable_command_working_directory(workspace, ".")
    try:
        reopened = open_stable_command_working_directory(workspace, ".")
        try:
            assert working_directory.directory.identity == reopened.directory.identity
        finally:
            close_command_working_directory(reopened)
    finally:
        close_command_working_directory(working_directory)
