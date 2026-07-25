from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.providers import ProviderKind
from banksia.runtime.contracts import TaskStartRequest
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.task_start import start_task
from banksia.runtime.workspace.admission import (
    TASK_INITIALIZATION_MARKER,
    recover_task_workspace_admissions,
)
from banksia.workflows.authoring import import_workflow_draft, publish_workflow_draft
from banksia.workflows.catalog import read_current_published_workflow
from tests.helpers.workflow_runtime import initialized_workflow_database


@pytest.mark.parametrize("note_state", ("missing", "tampered", "symlink", "fifo"))
async def test_workflow_note_recovery_restores_pinned_projection(
    tmp_path: Path,
    note_state: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-note.md"
    outside.write_text("outside", encoding="utf-8")

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            response = await start_task(
                _request(workspace),
                session=session,
                dependencies=_dependencies(workspace),
            )
            workflow = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
            expected_note = workflow.workflow.note
            assert expected_note is not None
            task_root = workspace / ".banksia" / response.task_id
            note_path = task_root / "workflow-note.md"
            note_path.unlink()
            if note_state == "tampered":
                note_path.write_text("tampered", encoding="utf-8")
            elif note_state == "symlink":
                note_path.symlink_to(outside)
            elif note_state == "fifo":
                os.mkfifo(note_path)
            _write_initialization_marker(task_root, response.task_id)

            recovered = await recover_task_workspace_admissions(
                session,
                workspaces=(workspace,),
            )

    assert recovered == (task_root,)
    assert note_path.is_file()
    assert not note_path.is_symlink()
    assert note_path.read_text(encoding="utf-8") == expected_note
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not (task_root / TASK_INITIALIZATION_MARKER).exists()


@pytest.mark.parametrize("extra_state", ("regular", "symlink", "fifo"))
async def test_recovery_removes_unconfigured_workflow_note(
    tmp_path: Path,
    extra_state: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-note.md"
    outside.write_text("outside", encoding="utf-8")

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            await _publish_workflow_without_note(session)
            response = await start_task(
                _request(workspace, workflow="workflow-without-note"),
                session=session,
                dependencies=_dependencies(workspace),
            )
            task_root = workspace / ".banksia" / response.task_id
            note_path = task_root / "workflow-note.md"
            assert not note_path.exists()
            if extra_state == "regular":
                note_path.write_text("unexpected", encoding="utf-8")
            elif extra_state == "symlink":
                note_path.symlink_to(outside)
            else:
                os.mkfifo(note_path)
            _write_initialization_marker(task_root, response.task_id)

            recovered = await recover_task_workspace_admissions(
                session,
                workspaces=(workspace,),
            )

    assert recovered == (task_root,)
    assert not note_path.exists()
    assert not note_path.is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not (task_root / TASK_INITIALIZATION_MARKER).exists()


async def test_recovery_rejects_reserved_workflow_note_directory(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            await _publish_workflow_without_note(session)
            response = await start_task(
                _request(workspace, workflow="workflow-without-note"),
                session=session,
                dependencies=_dependencies(workspace),
            )
            task_root = workspace / ".banksia" / response.task_id
            note_path = task_root / "workflow-note.md"
            note_path.mkdir()
            _write_initialization_marker(task_root, response.task_id)

            with pytest.raises(OSError):
                await recover_task_workspace_admissions(
                    session,
                    workspaces=(workspace,),
                )

    assert note_path.is_dir()
    assert (task_root / TASK_INITIALIZATION_MARKER).is_file()


async def _publish_workflow_without_note(session: AsyncSession) -> None:
    current = await read_current_published_workflow(
        session,
        workflow_id="reviewed-delivery",
    )
    draft = (
        await import_workflow_draft(
            session,
            workflow=current.workflow.model_copy(
                update={"id": "workflow-without-note", "note": None}
            ),
        )
    ).draft
    await publish_workflow_draft(
        session,
        draft_id=draft.draft_id,
        expected_etag=draft.etag,
    )
    await session.commit()


def _write_initialization_marker(task_root: Path, task_id: str) -> None:
    (task_root / TASK_INITIALIZATION_MARKER).write_text(
        f"banksia-task-initialization-v1\n{task_id}\n",
        encoding="utf-8",
    )


def _request(
    workspace: Path,
    *,
    workflow: str = "reviewed-delivery",
) -> TaskStartRequest:
    return TaskStartRequest(
        workflow=workflow,
        prompt="Complete the requested work.",
        workspace=workspace,
    )


def _dependencies(workspace: Path) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            controller_workspace=workspace,
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
