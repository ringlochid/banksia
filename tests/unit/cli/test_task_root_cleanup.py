from __future__ import annotations

from pathlib import Path

import pytest

from oh_my_subagents.interfaces.cli.bootstrap.task_root_cleanup import (
    UnsafeTaskRootError,
    delete_controller_task_roots,
)


def test_cleanup_removes_child_symlink_without_traversing_it(tmp_path: Path) -> None:
    data_boundary = tmp_path / "oms-data"
    task_root = data_boundary / "tasks" / "task.alpha"
    external_workspace = tmp_path / "external-workspace"
    task_root.mkdir(parents=True)
    external_workspace.mkdir()
    external_file = external_workspace / "keep.txt"
    external_file.write_text("user owned", encoding="utf-8")
    (task_root / "workspace").symlink_to(external_workspace, target_is_directory=True)
    (task_root / "_runtime").mkdir()

    deleted_roots = delete_controller_task_roots(
        [str(task_root)],
        data_boundary=data_boundary,
    )

    assert deleted_roots == (task_root,)
    assert not task_root.exists()
    assert external_file.read_text(encoding="utf-8") == "user owned"


def test_cleanup_rejects_path_outside_data_boundary(tmp_path: Path) -> None:
    data_boundary = tmp_path / "oms-data"
    data_boundary.mkdir()
    external_root = tmp_path / "external-task-root"
    external_root.mkdir()

    with pytest.raises(UnsafeTaskRootError, match="escapes the configured"):
        delete_controller_task_roots(
            [str(external_root)],
            data_boundary=data_boundary,
        )

    assert external_root.is_dir()


def test_cleanup_validates_every_root_before_deleting_any(tmp_path: Path) -> None:
    data_boundary = tmp_path / "oms-data"
    safe_root = data_boundary / "tasks" / "task.safe"
    unsafe_root = tmp_path / "external-task-root"
    safe_root.mkdir(parents=True)
    unsafe_root.mkdir()

    with pytest.raises(UnsafeTaskRootError, match="escapes the configured"):
        delete_controller_task_roots(
            [str(safe_root), str(unsafe_root)],
            data_boundary=data_boundary,
        )

    assert safe_root.is_dir()
    assert unsafe_root.is_dir()


def test_cleanup_rejects_symlinked_deletion_root(tmp_path: Path) -> None:
    data_boundary = tmp_path / "oms-data"
    data_boundary.mkdir()
    external_root = tmp_path / "external-task-root"
    external_root.mkdir()
    linked_root = data_boundary / "task-link"
    linked_root.symlink_to(external_root, target_is_directory=True)

    with pytest.raises(UnsafeTaskRootError, match="linked or replaced controller task root"):
        delete_controller_task_roots(
            [str(linked_root)],
            data_boundary=data_boundary,
        )

    assert linked_root.is_symlink()
    assert external_root.is_dir()


def test_cleanup_rejects_symlinked_task_root_ancestor(tmp_path: Path) -> None:
    data_boundary = tmp_path / "oms-data"
    real_task_parent = data_boundary / "real-tasks"
    real_task_root = real_task_parent / "task.alpha"
    real_task_root.mkdir(parents=True)
    linked_task_parent = data_boundary / "tasks"
    linked_task_parent.symlink_to(real_task_parent, target_is_directory=True)

    with pytest.raises(
        UnsafeTaskRootError,
        match="linked or replaced controller task-root ancestor",
    ):
        delete_controller_task_roots(
            [str(linked_task_parent / "task.alpha")],
            data_boundary=data_boundary,
        )

    assert linked_task_parent.is_symlink()
    assert real_task_root.is_dir()


def test_cleanup_validates_all_filesystem_roots_before_deleting_any(tmp_path: Path) -> None:
    data_boundary = tmp_path / "oms-data"
    safe_root = data_boundary / "tasks" / "task.safe"
    safe_root.mkdir(parents=True)
    real_task_parent = data_boundary / "real-tasks"
    unsafe_root = real_task_parent / "task.unsafe"
    unsafe_root.mkdir(parents=True)
    linked_task_parent = data_boundary / "linked-tasks"
    linked_task_parent.symlink_to(real_task_parent, target_is_directory=True)

    with pytest.raises(
        UnsafeTaskRootError,
        match="linked or replaced controller task-root ancestor",
    ):
        delete_controller_task_roots(
            [str(safe_root), str(linked_task_parent / "task.unsafe")],
            data_boundary=data_boundary,
        )

    assert safe_root.is_dir()
    assert unsafe_root.is_dir()
