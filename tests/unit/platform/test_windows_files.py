from __future__ import annotations

import os
from pathlib import Path

import pytest

from banksia.platform.workspace_files import (
    PrivateMutationTimeoutError,
    acquire_private_mutation_lock,
    ensure_private_directory,
    read_private_text,
    replace_private_text,
    select_workspace_file_operations,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows filesystem proof")


def test_windows_private_text_and_mutation_lock_are_usable(tmp_path: Path) -> None:
    private_directory = tmp_path / "private"
    private_file = private_directory / "config.toml"

    ensure_private_directory(private_directory)
    replace_private_text(private_file, "[server]\nport = 18125\n")

    assert read_private_text(private_file) == "[server]\nport = 18125\n"
    lock_path = private_directory / "config.lock"
    with acquire_private_mutation_lock(lock_path, timeout_seconds=1):
        with pytest.raises(PrivateMutationTimeoutError):
            with acquire_private_mutation_lock(lock_path, timeout_seconds=0.01):
                pass


def test_windows_workspace_backend_keeps_loose_files_inside_retained_tree(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    operations = select_workspace_file_operations()
    workspace_lease = operations.open_workspace(workspace)
    try:
        banksia = operations.create_child_directory(workspace_lease, ".banksia")
        try:
            task = operations.create_child_directory(banksia, "t_01234567")
            try:
                operations.write_new_text(task, "manifest.md", "# Team\n")
                assert (
                    operations.read_small_text(task, "manifest.md", byte_limit=1024) == "# Team\n"
                )
            finally:
                task.close()
        finally:
            banksia.close()
    finally:
        workspace_lease.close()


def test_windows_command_output_allows_live_readback(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    operations = select_workspace_file_operations()
    workspace_lease = operations.open_workspace(workspace)
    try:
        banksia = operations.create_child_directory(workspace_lease, ".banksia")
        try:
            task = operations.create_child_directory(banksia, "t_01234567")
            try:
                command_runs = operations.create_child_directory(task, "command-runs")
                try:
                    command = operations.create_child_directory(command_runs, "c_01234567")
                    try:
                        descriptor = operations.create_output_descriptor(command, "output.log")
                        try:
                            os.write(descriptor, b"ready\n")
                            os.fsync(descriptor)
                            output_path = (
                                workspace
                                / ".banksia"
                                / "t_01234567"
                                / "command-runs"
                                / "c_01234567"
                                / "output.log"
                            )
                            assert output_path.read_bytes() == b"ready\n"
                        finally:
                            os.close(descriptor)
                    finally:
                        command.close()
                finally:
                    command_runs.close()
            finally:
                task.close()
        finally:
            banksia.close()
    finally:
        workspace_lease.close()


def test_windows_workspace_rejects_reparse_components(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    link = workspace / "linked"
    link.symlink_to(outside, target_is_directory=True)
    operations = select_workspace_file_operations()

    with pytest.raises(OSError):
        operations.open_command_directory(workspace, ("linked",))
