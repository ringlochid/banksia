from __future__ import annotations

import ctypes
import errno
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import banksia.platform.private_paths as private_paths
import banksia.platform.workspace_files.posix as posix_private_files
from banksia.platform.private_paths import (
    protect_private_directory_descriptor,
    protect_private_file_descriptor,
)
from banksia.platform.workspace_files import (
    PrivateMutationTimeoutError,
    PrivatePathError,
    acquire_private_mutation_lock,
    ensure_private_directory,
    read_private_text,
    replace_private_text,
)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission proof")
def test_private_path_policy_repairs_and_verifies_owner_only_modes(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o777)
    private_file = directory / "secret"
    private_file.write_text("secret", encoding="utf-8")
    directory.chmod(0o777)
    private_file.chmod(0o666)

    directory_descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    file_descriptor = os.open(private_file, os.O_RDONLY)
    try:
        protect_private_directory_descriptor(directory_descriptor)
        protect_private_file_descriptor(file_descriptor)
    finally:
        os.close(file_descriptor)
        os.close(directory_descriptor)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(private_file.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission proof")
def test_private_path_policy_rejects_the_wrong_file_kind(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    directory.mkdir()
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(OSError, match="wrong file type"):
            protect_private_file_descriptor(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission proof")
def test_macos_private_path_accepts_absent_extended_acl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o777)
    directory.chmod(0o777)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    _install_fake_macos_acl_library(monkeypatch, acl_get_error=errno.ENOENT)

    try:
        protect_private_directory_descriptor(descriptor)
    finally:
        os.close(descriptor)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission proof")
def test_macos_private_path_rejects_unexpected_acl_read_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "private"
    directory.mkdir()
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    _install_fake_macos_acl_library(monkeypatch, acl_get_error=errno.EOPNOTSUPP)

    try:
        with pytest.raises(PrivatePathError, match="could not verify the macOS ACL") as captured:
            protect_private_directory_descriptor(descriptor)
    finally:
        os.close(descriptor)

    assert captured.value.errno == errno.EOPNOTSUPP


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow proof")
def test_private_text_read_rejects_a_final_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)

    with pytest.raises(OSError):
        read_private_text(link)


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow proof")
def test_private_text_rejects_an_intermediate_symlink_without_writing_through_it(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        replace_private_text(link / "config.toml", "value")

    assert not (outside / "config.toml").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission proof")
def test_private_directory_repairs_only_the_selected_directory(tmp_path: Path) -> None:
    parent = tmp_path / "existing-parent"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    selected = parent / "banksia"

    ensure_private_directory(selected)

    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(selected.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock proof")
def test_private_mutation_lock_times_out_and_releases(tmp_path: Path) -> None:
    lock_path = tmp_path / "private" / "settings.lock"

    with acquire_private_mutation_lock(lock_path, timeout_seconds=1):
        with pytest.raises(PrivateMutationTimeoutError):
            with acquire_private_mutation_lock(lock_path, timeout_seconds=0.01):
                pass

    with acquire_private_mutation_lock(lock_path, timeout_seconds=1):
        pass


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock proof")
def test_private_mutation_lock_retries_a_transient_create_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "private" / "settings.lock"
    real_open = posix_private_files.os.open
    lock_open_attempts = 0

    def open_with_one_transient_failure(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal lock_open_attempts
        if path == lock_path.name:
            lock_open_attempts += 1
            if lock_open_attempts == 1:
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(posix_private_files.os, "open", open_with_one_transient_failure)
    monkeypatch.setattr(
        posix_private_files.os,
        "supports_dir_fd",
        {*os.supports_dir_fd, open_with_one_transient_failure},
    )

    with acquire_private_mutation_lock(lock_path, timeout_seconds=1):
        pass

    assert lock_open_attempts == 2


def _install_fake_macos_acl_library(
    monkeypatch: pytest.MonkeyPatch,
    *,
    acl_get_error: int,
) -> None:
    def get_absent_acl(_descriptor: int, _acl_type: int) -> None:
        ctypes.set_errno(acl_get_error)
        return None

    library = SimpleNamespace(
        acl_init=Mock(return_value=1),
        acl_set_fd_np=Mock(return_value=0),
        acl_get_fd_np=Mock(side_effect=get_absent_acl),
        acl_get_entry=Mock(side_effect=AssertionError("no ACL should have no entries")),
        acl_free=Mock(return_value=0),
    )
    monkeypatch.setattr(private_paths.sys, "platform", "darwin")
    monkeypatch.setattr(private_paths.ctypes, "CDLL", lambda *_args, **_kwargs: library)
