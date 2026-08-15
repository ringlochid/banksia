from __future__ import annotations

import os
from pathlib import Path

import pytest

import banksia.platform.workspace_files.workspace_windows as workspace_windows_module
from banksia.platform.workspace_files import (
    PrivateMutationTimeoutError,
    acquire_private_mutation_lock,
    ensure_private_directory,
    read_private_text,
    replace_private_text,
    select_workspace_file_operations,
)
from banksia.platform.workspace_files.contracts import PrivatePathError, WindowsPathIdentity
from banksia.platform.workspace_files.workspace_windows import (
    WindowsDirectoryLease,
    WindowsWorkspaceFileOperations,
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


def test_windows_existing_private_file_parent_keeps_its_acl(tmp_path: Path) -> None:
    import win32security

    security_information = (
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.GROUP_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION
    )

    def read_security_descriptor() -> str:
        descriptor = win32security.GetFileSecurity(
            str(tmp_path),
            security_information,
        )
        return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            descriptor,
            win32security.SDDL_REVISION_1,
            security_information,
        )

    before = read_security_descriptor()

    ensure_private_directory(tmp_path)

    assert read_security_descriptor() == before


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


def test_windows_workspace_opens_drive_and_existing_ancestors_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path("C:/Users/ring_/AppData/Local/banksia")
    next_handle = 10
    identities: dict[int, WindowsPathIdentity] = {}
    absolute_calls: list[tuple[Path, bool]] = []
    relative_mutation_requests: list[bool] = []

    def open_absolute_directory(
        selected: Path,
        *,
        should_allow_child_directory_creation: bool = False,
        should_allow_child_file_creation: bool = False,
    ) -> int:
        nonlocal next_handle
        absolute_calls.append((selected, should_allow_child_directory_creation))
        assert should_allow_child_file_creation is False
        next_handle += 1
        identities[next_handle] = WindowsPathIdentity(1, next_handle.to_bytes(16, "little"))
        return next_handle

    def open_relative_entry(
        parent_handle: int,
        name: str,
        **options: object,
    ) -> int:
        nonlocal next_handle
        del parent_handle, name
        relative_mutation_requests.append(bool(options.get("should_allow_mutation", False)))
        next_handle += 1
        identities[next_handle] = WindowsPathIdentity(1, next_handle.to_bytes(16, "little"))
        return next_handle

    monkeypatch.setattr(workspace_windows_module, "require_ntfs", lambda selected: None)
    monkeypatch.setattr(
        workspace_windows_module,
        "open_absolute_directory",
        open_absolute_directory,
    )
    monkeypatch.setattr(workspace_windows_module, "open_relative_entry", open_relative_entry)
    monkeypatch.setattr(
        workspace_windows_module,
        "read_handle_identity",
        lambda handle: identities[handle],
    )
    monkeypatch.setattr(workspace_windows_module, "close_handle", lambda handle: None)

    lease = WindowsWorkspaceFileOperations().open_workspace(path)
    lease.close()

    assert absolute_calls == [(Path("C:/"), False)]
    assert relative_mutation_requests == [False] * 5


def test_windows_child_creation_reopens_only_the_retained_parent_and_checks_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = WindowsPathIdentity(7, b"p" * 16)
    child_identity = WindowsPathIdentity(7, b"c" * 16)
    parent = WindowsDirectoryLease(100, identity)
    opened_paths: list[tuple[Path, bool]] = []
    relative_parents: list[int] = []

    monkeypatch.setattr(
        workspace_windows_module,
        "read_handle_path",
        lambda handle: Path("C:/Users/ring_/AppData/Local") if handle == 100 else Path("C:/"),
    )

    def open_absolute_directory(
        selected: Path,
        *,
        should_allow_child_directory_creation: bool = False,
        should_allow_child_file_creation: bool = False,
    ) -> int:
        assert should_allow_child_file_creation is False
        opened_paths.append((selected, should_allow_child_directory_creation))
        return 200

    def read_handle_identity(handle: int) -> WindowsPathIdentity:
        return identity if handle in {100, 200} else child_identity

    def open_relative_entry(parent_handle: int, name: str, **options: object) -> int:
        assert name == "banksia"
        assert options["should_create"] is True
        relative_parents.append(parent_handle)
        return 300

    monkeypatch.setattr(
        workspace_windows_module,
        "open_absolute_directory",
        open_absolute_directory,
    )
    monkeypatch.setattr(workspace_windows_module, "read_handle_identity", read_handle_identity)
    monkeypatch.setattr(workspace_windows_module, "open_relative_entry", open_relative_entry)
    monkeypatch.setattr(
        workspace_windows_module, "protect_private_handle", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(workspace_windows_module, "close_handle", lambda handle: None)

    child = WindowsWorkspaceFileOperations().create_child_directory(parent, "banksia")
    child.close()

    assert opened_paths == [(Path("C:/Users/ring_/AppData/Local"), True)]
    assert relative_parents == [200]


def test_windows_child_creation_rejects_a_substituted_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retained_identity = WindowsPathIdentity(7, b"p" * 16)
    replacement_identity = WindowsPathIdentity(7, b"r" * 16)
    parent = WindowsDirectoryLease(100, retained_identity)

    monkeypatch.setattr(
        workspace_windows_module,
        "read_handle_path",
        lambda handle: Path("C:/Users/ring_/AppData/Local"),
    )

    def open_replacement_parent(
        selected: Path,
        *,
        should_allow_child_directory_creation: bool = False,
        should_allow_child_file_creation: bool = False,
    ) -> int:
        del selected, should_allow_child_directory_creation, should_allow_child_file_creation
        return 200

    monkeypatch.setattr(
        workspace_windows_module,
        "open_absolute_directory",
        open_replacement_parent,
    )
    monkeypatch.setattr(
        workspace_windows_module,
        "read_handle_identity",
        lambda handle: retained_identity if handle == 100 else replacement_identity,
    )
    monkeypatch.setattr(workspace_windows_module, "close_handle", lambda handle: None)

    with pytest.raises(PrivatePathError, match="changed identity"):
        WindowsWorkspaceFileOperations().create_child_directory(parent, "banksia")


def test_windows_existing_task_directory_is_verified_without_acl_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = WindowsPathIdentity(7, b"p" * 16)
    parent = WindowsDirectoryLease(100, identity)
    verification_handles: list[int] = []

    def open_relative_entry(parent_handle: int, name: str, **options: object) -> int:
        assert (parent_handle, name) == (100, "banksia")
        assert options["should_allow_mutation"] is False
        assert options["should_allow_security_update"] is False
        return 200

    monkeypatch.setattr(workspace_windows_module, "open_relative_entry", open_relative_entry)
    monkeypatch.setattr(
        workspace_windows_module,
        "read_handle_identity",
        lambda handle: identity,
    )
    monkeypatch.setattr(
        workspace_windows_module,
        "verify_private_handle",
        lambda handle, is_directory: verification_handles.append(handle),
        raising=False,
    )
    monkeypatch.setattr(
        workspace_windows_module,
        "protect_private_handle",
        lambda *args, **kwargs: pytest.fail("existing directory ACL must not be rewritten"),
    )
    monkeypatch.setattr(workspace_windows_module, "close_handle", lambda handle: None)

    child = WindowsWorkspaceFileOperations().open_child_directory(
        parent,
        "banksia",
        should_require_private=True,
    )
    child.close()

    assert verification_handles == [200]
