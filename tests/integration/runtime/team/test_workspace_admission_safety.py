from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import banksia.runtime.workspace.admission as admission_module
from banksia.platform.workspace_files import DirectoryLease
from banksia.runtime.team import plan_initial_task_team
from banksia.runtime.workspace.admission import (
    TASK_INITIALIZATION_MARKER,
    accept_task_workspace,
    cleanup_marked_task_workspace,
    recover_task_workspace_admissions,
    stage_task_workspace,
)
from banksia.runtime.workspace.storage import replace_task_text
from banksia.workflows.catalog import read_current_published_workflow
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_task_workspace_has_private_target_layout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task_id = "t_01234567"

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            workflow = await read_current_published_workflow(
                session,
                workflow_id=GENERIC_WORKFLOW_ID,
            )
    admission = stage_task_workspace(
        workspace=workspace,
        task_id=task_id,
        workflow_revision=workflow,
        initial_team=plan_initial_task_team(workflow, task_id),
    )

    expected_directories = {
        workspace / ".banksia",
        admission.task_root,
        admission.task_root / "notes",
        admission.task_root / "artifacts",
        admission.task_root / "command-runs",
    }
    for directory in expected_directories:
        assert directory.is_dir()
        if os.name == "posix":
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for file in (admission.marker, admission.manifest, admission.workflow_note):
        assert file is not None and file.is_file()
        if os.name == "posix":
            assert stat.S_IMODE(file.stat().st_mode) == 0o600

    accept_task_workspace(admission)

    assert not admission.marker.exists()
    assert not (admission.task_root / "_runtime").exists()


@pytest.mark.parametrize("kind", ("symlink", "file"))
async def test_stage_rejects_unsafe_banksia_root_without_touching_target(
    tmp_path: Path,
    kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    banksia_root = workspace / ".banksia"
    if kind == "symlink":
        banksia_root.symlink_to(outside, target_is_directory=True)
    else:
        banksia_root.write_text("not a directory", encoding="utf-8")

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            workflow = await read_current_published_workflow(
                session,
                workflow_id=GENERIC_WORKFLOW_ID,
            )

    with pytest.raises(OSError):
        stage_task_workspace(
            workspace=workspace,
            task_id="t_01234567",
            workflow_revision=workflow,
            initial_team=plan_initial_task_team(workflow, "t_01234567"),
        )

    assert tuple(outside.iterdir()) == ()
    assert banksia_root.is_symlink() if kind == "symlink" else banksia_root.is_file()


async def test_recovery_never_follows_a_task_directory_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    banksia_root = workspace / ".banksia"
    banksia_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    task_id = "t_01234567"
    marker = outside / TASK_INITIALIZATION_MARKER
    marker.write_text(
        f"banksia-task-initialization-v1\n{task_id}\n",
        encoding="utf-8",
    )
    linked_task = banksia_root / task_id
    linked_task.symlink_to(outside, target_is_directory=True)

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            recovered = await recover_task_workspace_admissions(
                session,
                workspaces=(workspace,),
            )

    assert recovered == ()
    assert linked_task.is_symlink()
    assert marker.is_file()


async def test_recovery_never_follows_a_marker_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    task_id = "t_01234567"
    task_root = workspace / ".banksia" / task_id
    task_root.mkdir(parents=True)
    outside = tmp_path / "outside-marker"
    outside.write_text(
        f"banksia-task-initialization-v1\n{task_id}\n",
        encoding="utf-8",
    )
    (task_root / TASK_INITIALIZATION_MARKER).symlink_to(outside)

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            recovered = await recover_task_workspace_admissions(
                session,
                workspaces=(workspace,),
            )

    assert recovered == ()
    assert task_root.is_dir()
    assert outside.is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX retained-directory race proof")
async def test_cleanup_never_deletes_a_replacement_task_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task_id = "t_01234567"
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            workflow = await read_current_published_workflow(
                session,
                workflow_id=GENERIC_WORKFLOW_ID,
            )
    admission = stage_task_workspace(
        workspace=workspace,
        task_id=task_id,
        workflow_revision=workflow,
        initial_team=plan_initial_task_team(workflow, task_id),
    )
    original_remove = admission_module.remove_task_tree
    moved_root = admission.task_root.with_name(f"{task_id}-moved")

    def substitute_before_removal(
        banksia_root: DirectoryLease,
        selected_task_id: str,
        retained_task_root: DirectoryLease,
    ) -> bool:
        admission.task_root.rename(moved_root)
        admission.task_root.mkdir()
        (admission.task_root / "replacement.txt").write_text(
            "must remain",
            encoding="utf-8",
        )
        return original_remove(
            banksia_root,
            selected_task_id,
            retained_task_root,
        )

    monkeypatch.setattr(admission_module, "remove_task_tree", substitute_before_removal)

    assert cleanup_marked_task_workspace(admission) is False
    assert (admission.task_root / "replacement.txt").read_text(encoding="utf-8") == "must remain"
    assert moved_root.is_dir()
    assert tuple(moved_root.iterdir()) == ()


def test_projection_replace_rejects_a_manifest_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    task_id = "t_01234567"
    task_root = workspace / ".banksia" / task_id
    task_root.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("external", encoding="utf-8")
    manifest = task_root / "manifest.md"
    manifest.symlink_to(outside)

    with pytest.raises(OSError, match="non-regular filesystem entry"):
        replace_task_text(workspace, task_id, "manifest.md", "projected")

    assert manifest.is_symlink()
    assert outside.read_text(encoding="utf-8") == "external"
