from __future__ import annotations

import os
from pathlib import Path

import pytest

from oh_my_subagents.runtime.contracts import FileReference
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.file_references import validate_file_references
from oh_my_subagents.runtime.workspace.regular_files import (
    UnsafeWorkspaceFileError,
    open_workspace_regular_file,
)


def test_physical_file_reference_validation_preserves_order_across_loose_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    paths = (
        "project.md",
        ".banksia/t_01234567/notes/basis.md",
        ".banksia/t_01234567/artifacts/report.md",
        ".banksia/t_01234567/command-runs/c_01234567/output.log",
    )
    for relative_path in paths:
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(relative_path, encoding="utf-8")

    files = tuple(
        FileReference(path=path, description=f"Open {index}.") for index, path in enumerate(paths)
    )

    assert validate_file_references(workspace, files) == files


@pytest.mark.parametrize("target_kind", ("missing", "directory", "fifo"))
def test_physical_file_reference_validation_rejects_non_regular_targets(
    tmp_path: Path,
    target_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "unsafe"
    if target_kind == "directory":
        target.mkdir()
    elif target_kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO files are not available on Windows")
        os.mkfifo(target)

    with pytest.raises(RuntimeOperationError, match=r"does not exist|not a regular file"):
        validate_file_references(
            workspace,
            (FileReference(path="unsafe"),),
        )


@pytest.mark.parametrize("link_position", ("final", "intermediate", "workspace"))
def test_physical_file_reference_validation_rejects_every_symlink_component(
    tmp_path: Path,
    link_position: str,
) -> None:
    real_workspace = tmp_path / "workspace"
    real_workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "brief.md").write_text("outside", encoding="utf-8")

    if link_position == "final":
        (real_workspace / "brief.md").symlink_to(outside / "brief.md")
        workspace = real_workspace
        relative_path = "brief.md"
    elif link_position == "intermediate":
        (real_workspace / "linked").symlink_to(outside, target_is_directory=True)
        workspace = real_workspace
        relative_path = "linked/brief.md"
    else:
        (real_workspace / "brief.md").write_text("inside", encoding="utf-8")
        workspace = tmp_path / "workspace-link"
        workspace.symlink_to(real_workspace, target_is_directory=True)
        relative_path = "brief.md"
    with pytest.raises(RuntimeOperationError, match=r"symbolic link|not a regular file"):
        validate_file_references(
            workspace,
            (FileReference(path=relative_path),),
        )


def test_physical_file_reference_validation_rejects_duplicate_normalized_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "brief.md").write_text("brief", encoding="utf-8")

    with pytest.raises(RuntimeOperationError, match="duplicate normalized path"):
        validate_file_references(
            workspace,
            (
                FileReference(path="./brief.md"),
                FileReference(path="brief.md"),
            ),
        )


def test_file_reference_is_navigation_not_a_content_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "brief.md"
    target.write_text("first", encoding="utf-8")
    files = (FileReference(path="brief.md"),)

    assert validate_file_references(workspace, files) == files
    target.write_text("changed", encoding="utf-8")
    assert validate_file_references(workspace, files) == files
    target.unlink()

    with pytest.raises(RuntimeOperationError, match="does not exist"):
        validate_file_references(workspace, files)


@pytest.mark.parametrize(
    "relative_path",
    (
        "/absolute.md",
        ".",
        "./brief.md",
        "notes/./brief.md",
        "..",
        "../brief.md",
        "notes/../brief.md",
        "notes//brief.md",
        "notes/",
        "notes\\brief.md",
        "notes/\x00brief.md",
    ),
)
def test_regular_file_primitive_rejects_non_normalized_paths_before_walk(
    tmp_path: Path,
    relative_path: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(
        UnsafeWorkspaceFileError,
        match="normalized and workspace-relative",
    ):
        with open_workspace_regular_file(workspace, relative_path):
            raise AssertionError("unsafe path unexpectedly opened")


__all__ = []
