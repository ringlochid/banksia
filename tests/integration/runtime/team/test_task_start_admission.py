from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest
from sqlalchemy import func, select

import banksia.runtime.task_start as task_start_module
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    DispatchRequestModel,
    DispatchTurnModel,
    TaskModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import FileReference, TaskStartRequest
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher, DispatchStartDue
from banksia.runtime.task_start import start_task
from banksia.runtime.workspace.admission import (
    TASK_INITIALIZATION_MARKER,
    recover_task_workspace_admissions,
)
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_task_start_preserves_long_prompt_and_file_values(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_path = "  brief.md  "
    file_description = "  Read this file without trimming its description.  "
    (workspace / file_path).write_text("source brief", encoding="utf-8")
    prompt = f"  {'x' * 8_193}\r\nKeep the trailing space.  "
    request = TaskStartRequest(
        workflow=GENERIC_WORKFLOW_ID,
        prompt=prompt,
        workspace=workspace,
        files=(FileReference(path=file_path, description=file_description),),
    )

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            response = await start_task(
                request,
                session=session,
                dependencies=_dependencies(workspace),
            )
            assignment = await session.scalar(
                select(AssignmentModel).where(AssignmentModel.task_id == response.task_id)
            )
            dispatch_request = await session.scalar(
                select(DispatchRequestModel)
                .join(
                    DispatchTurnModel,
                    DispatchTurnModel.dispatch_id == DispatchRequestModel.dispatch_id,
                )
                .where(DispatchTurnModel.task_id == response.task_id)
            )

    assert assignment is not None and assignment.prompt == request.prompt
    assert dispatch_request is not None
    rendered_assignment = ElementTree.fromstring(dispatch_request.input).find("assignment")
    assert rendered_assignment is not None
    assert rendered_assignment.findtext("prompt") == request.prompt
    rendered_files = rendered_assignment.findall("./files/file")
    assert [
        {
            "path": rendered.findtext("path"),
            "description": rendered.findtext("description"),
        }
        for rendered in rendered_files
    ] == [{"path": file_path, "description": file_description}]


async def test_concurrent_task_starts_share_one_workspace_admission_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first_launch_entered = asyncio.Event()
    second_launch_entered = asyncio.Event()
    release_first_launch = asyncio.Event()
    real_launch = task_start_module.launch_task_runtime
    launch_count = 0

    async def observed_launch(*args: Any, **kwargs: Any) -> Any:
        nonlocal launch_count
        launch_count += 1
        if launch_count == 1:
            first_launch_entered.set()
            await release_first_launch.wait()
        else:
            second_launch_entered.set()
        return await real_launch(*args, **kwargs)

    monkeypatch.setattr(task_start_module, "launch_task_runtime", observed_launch)
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as first_session, session_factory() as second_session:
            dependencies = _dependencies(workspace)
            first_start = asyncio.create_task(
                start_task(
                    _request(workspace),
                    session=first_session,
                    dependencies=dependencies,
                )
            )
            await asyncio.wait_for(first_launch_entered.wait(), timeout=1)
            second_start = asyncio.create_task(
                start_task(
                    _request(workspace),
                    session=second_session,
                    dependencies=dependencies,
                )
            )
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(second_launch_entered.wait(), timeout=0.05)
            finally:
                release_first_launch.set()
            first_response, second_response = await asyncio.gather(first_start, second_start)

        async with session_factory() as read_session:
            task_count = int(
                await read_session.scalar(select(func.count()).select_from(TaskModel)) or 0
            )

    assert launch_count == 2
    assert task_count == 2
    for response in (first_response, second_response):
        task_root = workspace / ".banksia" / response.task_id
        assert task_root.is_dir()
        assert not (task_root / TASK_INITIALIZATION_MARKER).exists()


async def test_task_start_commit_acknowledgement_failure_retains_marked_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    publisher = CapturedRuntimeEffectPublisher()

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            real_commit = session.commit

            async def commit_then_lose_acknowledgement() -> None:
                await real_commit()
                raise RuntimeError("commit acknowledgement lost")

            monkeypatch.setattr(session, "commit", commit_then_lose_acknowledgement)
            with pytest.raises(RuntimeError, match="commit acknowledgement lost"):
                await start_task(
                    _request(workspace),
                    session=session,
                    dependencies=_dependencies(workspace, publisher=publisher),
                )

        async with session_factory() as read_session:
            task_count = int(
                await read_session.scalar(select(func.count()).select_from(TaskModel)) or 0
            )

    task_roots = tuple((workspace / ".banksia").glob("t_*"))
    assert task_count == 1
    assert len(task_roots) == 1
    assert (task_roots[0] / TASK_INITIALIZATION_MARKER).is_file()
    assert publisher.signals == ()


async def test_task_start_rejections_and_exclusive_collision_leave_clean_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            publisher = CapturedRuntimeEffectPublisher()
            with pytest.raises(
                RuntimeOperationError,
                match=r"referenced file does not exist: missing\.md",
            ) as missing_file:
                await start_task(
                    TaskStartRequest(
                        workflow=GENERIC_WORKFLOW_ID,
                        prompt="Read the missing input.",
                        workspace=workspace,
                        files=(FileReference(path="missing.md"),),
                    ),
                    session=session,
                    dependencies=_dependencies(workspace, publisher=publisher),
                )
            assert missing_file.value.status_code_override == 422
            assert await _task_count(session) == 0
            assert publisher.signals == ()
            _assert_no_task_directory(workspace)

            async def fail_after_runtime_staging(
                *args: object,
                **kwargs: object,
            ) -> object:
                del args, kwargs
                raise RuntimeError("dispatch staging failed")

            with monkeypatch.context() as scoped:
                scoped.setattr(
                    task_start_module,
                    "stage_initial_root_dispatch",
                    fail_after_runtime_staging,
                )
                with pytest.raises(RuntimeError, match="dispatch staging failed"):
                    await start_task(
                        _request(workspace),
                        session=session,
                        dependencies=_dependencies(workspace, publisher=publisher),
                    )
            assert await _task_count(session) == 0
            assert publisher.signals == ()
            _assert_no_task_directory(workspace)

            allocated_ids = iter(("t_01234567", "t_89abcdef"))

            async def allocate(*args: object, **kwargs: object) -> str:
                del args, kwargs
                return next(allocated_ids)

            real_stage = task_start_module.stage_task_workspace
            staged_ids: list[str] = []

            def collide_once(**kwargs: Any) -> Any:
                staged_ids.append(str(kwargs["task_id"]))
                if len(staged_ids) == 1:
                    raise FileExistsError("simulated exclusive-create race")
                return real_stage(**kwargs)

            with monkeypatch.context() as scoped:
                scoped.setattr(task_start_module, "allocate_task_id", allocate)
                scoped.setattr(task_start_module, "stage_task_workspace", collide_once)
                accepted = await start_task(
                    _request(workspace),
                    session=session,
                    dependencies=_dependencies(workspace, publisher=publisher),
                )

    assert staged_ids == ["t_01234567", "t_89abcdef"]
    assert accepted.task_id == "t_89abcdef"
    assert (workspace / ".banksia" / accepted.task_id / "manifest.md").is_file()
    assert len(publisher.signals) == 1
    assert isinstance(publisher.signals[0], DispatchStartDue)


async def test_task_start_recovery_repairs_committed_marker_and_removes_stale_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    publisher = CapturedRuntimeEffectPublisher()

    def fail_marker_acceptance(admission: object) -> None:
        del admission
        raise OSError("marker unlink unavailable")

    monkeypatch.setattr(
        task_start_module,
        "accept_task_workspace",
        fail_marker_acceptance,
    )
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with session_factory() as session:
            response = await start_task(
                _request(workspace),
                session=session,
                dependencies=_dependencies(workspace, publisher=publisher),
            )
            committed_root = workspace / ".banksia" / response.task_id
            committed_marker = committed_root / TASK_INITIALIZATION_MARKER
            assert committed_marker.is_file()
            assert publisher.signals == ()

            orphan_id = "t_abcdefgh"
            orphan_root = workspace / ".banksia" / orphan_id
            orphan_root.mkdir()
            (orphan_root / TASK_INITIALIZATION_MARKER).write_text(
                f"banksia-task-initialization-v1\n{orphan_id}\n",
                encoding="utf-8",
            )

            first_recovery = await recover_task_workspace_admissions(
                session,
                workspaces=(workspace,),
                publish_recovered_provider_start=publisher.publish,
            )
            second_recovery = await recover_task_workspace_admissions(
                session,
                workspaces=(workspace,),
                publish_recovered_provider_start=publisher.publish,
            )

    assert set(first_recovery) == {committed_root, orphan_root}
    assert second_recovery == ()
    assert committed_root.is_dir()
    assert not committed_marker.exists()
    assert not orphan_root.exists()
    assert len(publisher.signals) == 1
    assert isinstance(publisher.signals[0], DispatchStartDue)


def _request(workspace: Path) -> TaskStartRequest:
    return TaskStartRequest(
        workflow=GENERIC_WORKFLOW_ID,
        prompt="Complete the requested work.",
        workspace=workspace,
    )


async def _task_count(session: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(TaskModel)) or 0)


def _assert_no_task_directory(workspace: Path) -> None:
    banksia_root = workspace / ".banksia"
    assert not banksia_root.exists() or not tuple(banksia_root.glob("t_*"))


def _dependencies(
    workspace: Path,
    *,
    publisher: CapturedRuntimeEffectPublisher | None = None,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            controller_workspace=workspace,
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher or CapturedRuntimeEffectPublisher(),
    )
