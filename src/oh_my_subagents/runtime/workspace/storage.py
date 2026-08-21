from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from oh_my_subagents.platform.workspace_files import (
    DirectoryLease,
    PathIdentity,
    select_workspace_file_operations,
)
from oh_my_subagents.product_identity import LEGACY_BANKSIA_IDENTITY, OMS_IDENTITY

_MARKER_READ_LIMIT = 4_096
TASK_CONTAINER_NAME = OMS_IDENTITY.task_container_name
LEGACY_TASK_CONTAINER_NAME = LEGACY_BANKSIA_IDENTITY.task_container_name
TASK_CONTAINER_NAMES = (TASK_CONTAINER_NAME, LEGACY_TASK_CONTAINER_NAME)

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

    with open_existing_task_container(workspace, task_id) as task_container:
        with open_task_root(task_container, task_id) as task_root:
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
    with open_task_container(
        workspace,
        container_name=TASK_CONTAINER_NAME,
        should_create=True,
        expected_workspace_identity=expected_workspace_identity,
    ) as task_container:
        assert task_container is not None
        task_root = operations.create_child_directory(task_container, task_id)
        try:
            yield task_container, task_root
        finally:
            task_root.close()


@contextmanager
def open_task_container(
    workspace: Path,
    *,
    container_name: str,
    should_create: bool,
    expected_workspace_identity: WorkspaceIdentity | None = None,
) -> Iterator[DirectoryLease | None]:
    """Retain one named Task container without following links."""

    if container_name not in TASK_CONTAINER_NAMES:
        raise ValueError(f"unsupported Task container: {container_name!r}")

    operations = select_workspace_file_operations()
    workspace_root = operations.open_workspace(workspace)
    task_container: DirectoryLease | None = None
    try:
        if (
            expected_workspace_identity is not None
            and workspace_root.identity != expected_workspace_identity
        ):
            raise RuntimeError("Task workspace changed identity during admission")
        if should_create:
            operations.ensure_child_directory(
                workspace_root,
                container_name,
                should_require_private=False,
            )
        try:
            task_container = operations.open_child_directory(
                workspace_root,
                container_name,
                should_require_private=False,
            )
        except FileNotFoundError:
            if should_create:
                raise
            yield None
            return
        yield task_container
    finally:
        if task_container is not None:
            task_container.close()
        workspace_root.close()


@contextmanager
def open_existing_task_container(
    workspace: Path,
    task_id: str,
) -> Iterator[DirectoryLease]:
    """Open the sole canonical or legacy container that owns an existing Task."""

    stack = ExitStack()
    matches: list[DirectoryLease] = []
    try:
        for container_name in TASK_CONTAINER_NAMES:
            container = stack.enter_context(
                open_task_container(
                    workspace,
                    container_name=container_name,
                    should_create=False,
                )
            )
            if container is not None and is_real_directory(container, task_id):
                matches.append(container)
        if not matches:
            raise FileNotFoundError(workspace / TASK_CONTAINER_NAME / task_id)
        if len(matches) != 1:
            raise RuntimeError(f"Task {task_id!r} exists in both OMS and Banksia containers")
        yield matches[0]
    finally:
        stack.close()


@contextmanager
def open_task_root(
    task_container: DirectoryLease,
    task_id: str,
) -> Iterator[DirectoryLease]:
    """Retain one existing private Task directory without following a link."""

    with open_child_directory(task_container, task_id) as task_root:
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
    task_container: DirectoryLease,
    task_id: str,
    task_root: DirectoryLease,
) -> bool:
    """Remove the same retained Task tree whose controller marker was proved."""

    return select_workspace_file_operations().remove_retained_tree(
        task_container,
        task_id,
        task_root,
    )


def unlink_entry(parent: DirectoryLease, name: str) -> None:
    select_workspace_file_operations().unlink_entry(parent, name)


def task_root_names(task_container: DirectoryLease) -> tuple[str, ...]:
    return select_workspace_file_operations().list_directory_names(task_container)


def is_real_directory(parent: DirectoryLease, name: str) -> bool:
    return select_workspace_file_operations().is_real_child_directory(parent, name)


__all__ = [
    "LEGACY_TASK_CONTAINER_NAME",
    "TASK_CONTAINER_NAME",
    "TASK_CONTAINER_NAMES",
    "WorkspaceIdentity",
    "capture_workspace_identity",
    "ensure_directory",
    "is_real_directory",
    "open_child_directory",
    "open_existing_task_container",
    "open_task_container",
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
