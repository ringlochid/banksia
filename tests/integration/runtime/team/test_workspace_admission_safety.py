from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import oh_my_subagents.runtime.task_start as task_start_module
import oh_my_subagents.runtime.workspace.admission as admission_module
from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    TaskEventModel,
    TaskModel,
)
from oh_my_subagents.platform.workspace_files import DirectoryLease, ensure_private_directory
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.contracts import TaskStartRequest
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.post_commit import CapturedRuntimeEffectPublisher
from oh_my_subagents.runtime.product.tasks import read_product_task
from oh_my_subagents.runtime.task_control.control import continue_task, pause_task
from oh_my_subagents.runtime.task_control.reads import read_runtime_task
from oh_my_subagents.runtime.task_start import start_task
from oh_my_subagents.runtime.team import plan_initial_task_team
from oh_my_subagents.runtime.workspace.admission import (
    TASK_INITIALIZATION_MARKER,
    accept_task_workspace,
    cleanup_marked_task_workspace,
    recover_task_workspace_admissions,
    stage_task_workspace,
)
from oh_my_subagents.runtime.workspace.storage import WorkspaceIdentity, replace_task_text
from oh_my_subagents.workflows.catalog import read_current_published_workflow
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
        workspace / ".oms",
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


async def test_task_start_preserves_existing_banksia_content_and_permissions(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task_container = workspace / ".oms"
    task_container.mkdir(mode=0o755)
    task_container.chmod(0o755)
    project_file = task_container / ".tickets" / "README.md"
    project_file.parent.mkdir()
    project_file.write_text("project-owned\n", encoding="utf-8")

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            response = await start_task(
                TaskStartRequest(
                    workflow=GENERIC_WORKFLOW_ID,
                    prompt="Work without changing project-owned Oh My Subagents content.",
                    workspace=workspace,
                ),
                session=session,
                dependencies=DispatchOpeningDependencies.create(
                    settings=Settings(
                        controller_workspace=workspace,
                        runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
                        codex=CodexSettings(enabled=True),
                    ),
                    available_adapter_kinds={ProviderKind.CODEX},
                    post_commit_publisher=CapturedRuntimeEffectPublisher(),
                ),
            )

    assert project_file.read_text(encoding="utf-8") == "project-owned\n"
    if os.name == "posix":
        assert stat.S_IMODE(task_container.stat().st_mode) == 0o755
        assert stat.S_IMODE((task_container / response.task_id).stat().st_mode) == 0o700
    assert (task_container / response.task_id / "manifest.md").is_file()


async def test_task_start_rejects_workspace_identity_substitution_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original_workspace = tmp_path / "workspace-before-swap"
    real_capture = task_start_module.capture_workspace_identity

    def substitute_during_capture(selected_workspace: Path) -> WorkspaceIdentity:
        identity = real_capture(selected_workspace)
        selected_workspace.rename(original_workspace)
        selected_workspace.mkdir()
        return identity

    monkeypatch.setattr(
        task_start_module,
        "capture_workspace_identity",
        substitute_during_capture,
    )

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            with pytest.raises(RuntimeError, match="changed identity"):
                await start_task(
                    TaskStartRequest(
                        workflow=GENERIC_WORKFLOW_ID,
                        prompt="Reject a substituted workspace.",
                        workspace=workspace,
                    ),
                    session=session,
                    dependencies=DispatchOpeningDependencies.create(
                        settings=Settings(
                            controller_workspace=workspace,
                            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
                            codex=CodexSettings(enabled=True),
                        ),
                        available_adapter_kinds={ProviderKind.CODEX},
                        post_commit_publisher=CapturedRuntimeEffectPublisher(),
                    ),
                )

    assert not (workspace / ".oms").exists()
    assert not (original_workspace / ".oms").exists()


@pytest.mark.parametrize("kind", ("symlink", "file"))
async def test_stage_rejects_unsafe_task_container_without_touching_target(
    tmp_path: Path,
    kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    task_container = workspace / ".oms"
    if kind == "symlink":
        task_container.symlink_to(outside, target_is_directory=True)
    else:
        task_container.write_text("not a directory", encoding="utf-8")

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
    assert task_container.is_symlink() if kind == "symlink" else task_container.is_file()


async def test_recovery_never_follows_a_task_directory_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    task_container = workspace / ".oms"
    task_container.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    task_id = "t_01234567"
    marker = outside / TASK_INITIALIZATION_MARKER
    marker.write_text(
        f"oms-task-initialization-v1\n{task_id}\n",
        encoding="utf-8",
    )
    linked_task = task_container / task_id
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
    task_root = workspace / ".oms" / task_id
    ensure_private_directory(task_root)
    outside = tmp_path / "outside-marker"
    outside.write_text(
        f"oms-task-initialization-v1\n{task_id}\n",
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


async def test_missing_workspace_pauses_only_its_running_task_and_waits_for_manual_resume(
    tmp_path: Path,
) -> None:
    missing_workspace = tmp_path / "missing-workspace"
    healthy_workspace = tmp_path / "healthy-workspace"
    missing_workspace.mkdir()
    healthy_workspace.mkdir()
    detached_workspace = tmp_path / "detached-workspace"

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            affected = await start_task(
                _task_request(missing_workspace, "Investigate the unavailable workspace."),
                session=session,
                dependencies=_task_dependencies(missing_workspace),
            )
            unaffected = await start_task(
                _task_request(healthy_workspace, "Continue work in the available workspace."),
                session=session,
                dependencies=_task_dependencies(healthy_workspace),
            )
            affected_before = await session.get(TaskModel, affected.task_id)
            assert affected_before is not None
            original_control_revision = affected_before.control_revision

            missing_workspace.rename(detached_workspace)
            recovered = await recover_task_workspace_admissions(session)
            assert recovered == ()
            affected_task = await _assert_task_scoped_workspace_pause(
                session,
                affected_task_id=affected.task_id,
                unaffected_task_id=unaffected.task_id,
                original_control_revision=original_control_revision,
            )
            assert affected_task.current_team_revision_id is not None
            assert not missing_workspace.exists()

            with pytest.raises(RuntimeOperationError, match="workspace is unavailable"):
                await continue_task(
                    session,
                    affected.task_id,
                    expected_team_revision_id=affected_task.current_team_revision_id,
                    expected_control_revision=affected_task.control_revision,
                    dependencies=_task_dependencies(healthy_workspace),
                )

            await recover_task_workspace_admissions(session)
            repeated_event_count = await session.scalar(
                select(func.count())
                .select_from(TaskEventModel)
                .where(
                    TaskEventModel.task_id == affected.task_id,
                    TaskEventModel.event_type == "task_paused",
                )
            )
            assert repeated_event_count == 1

            detached_workspace.rename(missing_workspace)
            await recover_task_workspace_admissions(session)
            returned_task = await session.get(TaskModel, affected.task_id)
            returned_view = await read_product_task(session, affected.task_id)

            assert returned_task is not None and returned_task.status == "paused"
            assert returned_task.pause_reason == "workspace_unavailable"
            assert tuple(action.kind for action in returned_view.actions) == ("resume", "cancel")
            assert "available again" in returned_view.attention[0].summary.casefold()


async def test_missing_workspace_preserves_an_existing_pause_reason(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    detached_workspace = tmp_path / "detached-workspace"

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            started = await start_task(
                _task_request(workspace, "Keep the operator pause intact."),
                session=session,
                dependencies=_task_dependencies(workspace),
            )
            running = await read_runtime_task(session, started.task_id)
            paused = await pause_task(
                session,
                started.task_id,
                expected_team_revision_id=running.current_team_revision_id,
                expected_control_revision=running.control_revision,
            )
            paused_revision = paused.task.control_revision

            workspace.rename(detached_workspace)
            await recover_task_workspace_admissions(session)

            task = await session.get(TaskModel, started.task_id)
            pause_event_count = await session.scalar(
                select(func.count())
                .select_from(TaskEventModel)
                .where(
                    TaskEventModel.task_id == started.task_id,
                    TaskEventModel.event_type == "task_paused",
                )
            )
            view = await read_product_task(session, started.task_id)

    assert task is not None
    assert task.pause_reason == "paused_by_operator"
    assert task.control_revision == paused_revision
    assert pause_event_count == 1
    assert tuple(action.kind for action in view.actions) == ("cancel",)
    assert tuple(attention.kind for attention in view.attention) == ("workspace_unavailable",)


async def test_inaccessible_committed_task_root_is_task_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            started = await start_task(
                _task_request(workspace, "Pause only this inaccessible Task."),
                session=session,
                dependencies=_task_dependencies(workspace),
            )
            real_open_task_root = admission_module.open_task_root

            @contextmanager
            def refuse_task_root(
                task_container: DirectoryLease,
                task_id: str,
            ) -> Iterator[DirectoryLease]:
                if task_id == started.task_id:
                    raise PermissionError("Task root cannot be traversed")
                with real_open_task_root(task_container, task_id) as task_root:
                    yield task_root

            monkeypatch.setattr(admission_module, "open_task_root", refuse_task_root)

            assert await recover_task_workspace_admissions(session) == ()
            task = await session.get(TaskModel, started.task_id)

    assert task is not None
    assert (task.status, task.pause_reason) == ("paused", "workspace_unavailable")


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
        task_container: DirectoryLease,
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
            task_container,
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
    task_root = workspace / ".oms" / task_id
    ensure_private_directory(task_root)
    outside = tmp_path / "outside.md"
    outside.write_text("external", encoding="utf-8")
    manifest = task_root / "manifest.md"
    manifest.symlink_to(outside)

    with pytest.raises(OSError, match="non-regular filesystem entry"):
        replace_task_text(workspace, task_id, "manifest.md", "projected")

    assert manifest.is_symlink()
    assert outside.read_text(encoding="utf-8") == "external"


def _task_request(workspace: Path, prompt: str) -> TaskStartRequest:
    return TaskStartRequest(
        workflow=GENERIC_WORKFLOW_ID,
        prompt=prompt,
        workspace=workspace,
    )


def _task_dependencies(workspace: Path) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            controller_workspace=workspace,
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )


async def _assert_task_scoped_workspace_pause(
    session: AsyncSession,
    *,
    affected_task_id: str,
    unaffected_task_id: str,
    original_control_revision: int,
) -> TaskModel:
    affected_task = await session.get(TaskModel, affected_task_id)
    unaffected_task = await session.get(TaskModel, unaffected_task_id)
    affected_attempt = await session.scalar(
        select(AttemptModel).where(AttemptModel.task_id == affected_task_id)
    )
    affected_dispatch = await session.scalar(
        select(DispatchTurnModel).where(DispatchTurnModel.task_id == affected_task_id)
    )
    pause_event_count = await session.scalar(
        select(func.count())
        .select_from(TaskEventModel)
        .where(
            TaskEventModel.task_id == affected_task_id,
            TaskEventModel.event_type == "task_paused",
        )
    )
    unavailable_view = await read_product_task(session, affected_task_id)

    assert affected_task is not None
    assert affected_task.status == "paused"
    assert affected_task.pause_reason == "workspace_unavailable"
    assert affected_task.current_team_revision_id is not None
    assert affected_task.control_revision == original_control_revision + 1
    assert affected_attempt is not None and affected_attempt.current_dispatch_id is None
    assert affected_dispatch is not None
    assert (affected_dispatch.status, affected_dispatch.closed_reason) == ("closed", "paused")
    assert pause_event_count == 1
    assert unaffected_task is not None and unaffected_task.status == "running"
    assert tuple(action.kind for action in unavailable_view.actions) == ("cancel",)
    assert tuple(attention.kind for attention in unavailable_view.attention) == (
        "workspace_unavailable",
    )
    assert "unavailable" in unavailable_view.attention[0].summary.casefold()
    return affected_task
