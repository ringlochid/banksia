from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from banksia.platform.workspace_files import (
    DirectoryLease,
    PathIdentity,
    select_workspace_file_operations,
)

_MARKER_READ_LIMIT = 4_096

type WorkspaceIdentity = PathIdentity


def capture_workspace_identity(workspace: Path) -> WorkspaceIdentity:
    """Capture one all-component no-follow workspace identity."""

    operations = select_workspace_file_operations()
    workspace_lease = operations.open_workspace(workspace)
    try:
        return workspace_lease.identity
    finally:
        workspace_lease.close()


def replace_task_text(
    workspace: Path,
    task_id: str,
    name: str,
    text: str,
) -> None:
    """Replace one controller projection in an existing physical Task root."""

    with open_banksia_root(workspace, should_create=False) as banksia_root:
        if banksia_root is None:
            raise FileNotFoundError(workspace / ".banksia")
        with open_task_root(banksia_root, task_id) as task_root:
            replace_text(task_root, name, text)


@contextmanager
def reserve_task_root(
    workspace: Path,
    task_id: str,
    *,
    expected_workspace_identity: WorkspaceIdentity | None = None,
) -> Iterator[tuple[DirectoryLease, DirectoryLease]]:
    """Exclusively create and retain one private Task root."""

    operations = select_workspace_file_operations()
    with open_banksia_root(
        workspace,
        should_create=True,
        expected_workspace_identity=expected_workspace_identity,
    ) as banksia_root:
        assert banksia_root is not None
        task_root = operations.create_child_directory(banksia_root, task_id)
        try:
            yield banksia_root, task_root
        finally:
            task_root.close()


@contextmanager
def open_banksia_root(
    workspace: Path,
    *,
    should_create: bool,
    expected_workspace_identity: WorkspaceIdentity | None = None,
) -> Iterator[DirectoryLease | None]:
    """Retain the workspace and its shared `.banksia` child without following links."""

    operations = select_workspace_file_operations()
    workspace_root = operations.open_workspace(workspace)
    banksia_root: DirectoryLease | None = None
    try:
        if (
            expected_workspace_identity is not None
            and workspace_root.identity != expected_workspace_identity
        ):
            raise RuntimeError("Task workspace changed identity during admission")
        if should_create:
            operations.ensure_child_directory(
                workspace_root,
                ".banksia",
                should_require_private=False,
            )
        try:
            banksia_root = operations.open_child_directory(
                workspace_root,
                ".banksia",
                should_require_private=False,
            )
        except FileNotFoundError:
            if should_create:
                raise
            yield None
            return
        yield banksia_root
    finally:
        if banksia_root is not None:
            banksia_root.close()
        workspace_root.close()


@contextmanager
def open_task_root(
    banksia_root: DirectoryLease,
    task_id: str,
) -> Iterator[DirectoryLease]:
    """Retain one existing private Task directory without following a link."""

    with open_child_directory(banksia_root, task_id) as task_root:
        yield task_root


@contextmanager
def open_child_directory(
    parent: DirectoryLease,
    name: str,
) -> Iterator[DirectoryLease]:
    """Retain one existing private child directory."""

    child = select_workspace_file_operations().open_child_directory(
        parent,
        name,
        should_require_private=True,
    )
    try:
        yield child
    finally:
        child.close()


def ensure_directory(parent: DirectoryLease, name: str) -> None:
    """Create or verify one private real child directory."""

    select_workspace_file_operations().ensure_child_directory(
        parent,
        name,
        should_require_private=True,
    )


def replace_text(parent: DirectoryLease, name: str, text: str) -> None:
    """Atomically replace one private Task projection."""

    select_workspace_file_operations().replace_text(parent, name, text)


def write_new_text(parent: DirectoryLease, name: str, text: str) -> None:
    """Exclusively create and flush one private UTF-8 file."""

    select_workspace_file_operations().write_new_text(parent, name, text)


def read_small_text(parent: DirectoryLease, name: str) -> str | None:
    """Read one bounded private regular UTF-8 file without following links."""

    return select_workspace_file_operations().read_small_text(
        parent,
        name,
        byte_limit=_MARKER_READ_LIMIT,
    )


def remove_task_tree(
    banksia_root: DirectoryLease,
    task_id: str,
    task_root: DirectoryLease,
) -> bool:
    """Remove the same retained Task tree whose controller marker was proved."""

    return select_workspace_file_operations().remove_retained_tree(
        banksia_root,
        task_id,
        task_root,
    )


def unlink_entry(parent: DirectoryLease, name: str) -> None:
    select_workspace_file_operations().unlink_entry(parent, name)


def task_root_names(banksia_root: DirectoryLease) -> tuple[str, ...]:
    return select_workspace_file_operations().list_directory_names(banksia_root)


def is_real_directory(parent: DirectoryLease, name: str) -> bool:
    return select_workspace_file_operations().is_real_child_directory(parent, name)


__all__ = [
    "WorkspaceIdentity",
    "capture_workspace_identity",
    "ensure_directory",
    "is_real_directory",
    "open_banksia_root",
    "open_child_directory",
    "open_task_root",
    "read_small_text",
    "remove_task_tree",
    "replace_task_text",
    "replace_text",
    "reserve_task_root",
    "task_root_names",
    "unlink_entry",
    "write_new_text",
]
