from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import banksia.runtime.task_start as task_start_module
import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    TaskModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import FileReference, TaskStartRequest
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.task_start import start_task
from banksia.runtime.workspace.admission import TASK_INITIALIZATION_MARKER
from sqlalchemy import func, select
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_task_start_request_bridge_preserves_long_prompt_and_file_values(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_path = "  brief.md  "
    file_description = "  Read this file without trimming its description.  "
    (workspace / file_path).write_text("source brief", encoding="utf-8")
    prompt = f"  {'x' * 8_193}\r\nKeep the trailing space.  "
    request = TaskStartRequest(
        workflow="reviewed-delivery",
        prompt=prompt,
        workspace=workspace,
        files=(FileReference(path=file_path, description=file_description),),
    )

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            response = await start_task(
                request,
                session=session,
                dependencies=_dependencies(workspace),
            )
            assignment = await session.scalar(
                select(AssignmentModel).where(AssignmentModel.task_id == response.task_id)
            )
            prompt_refs = await session.scalar(
                select(DispatchPromptRefsModel)
                .join(
                    DispatchTurnModel,
                    DispatchTurnModel.dispatch_id == DispatchPromptRefsModel.dispatch_id,
                )
                .where(DispatchTurnModel.task_id == response.task_id)
            )

    assert assignment is not None and assignment.prompt == request.prompt
    assert prompt_refs is not None
    input_path = workspace / ".banksia" / response.task_id / prompt_refs.input_logical_path
    rendered_assignment = _read_rendered_section(
        input_path.read_text(encoding="utf-8"),
        "Assignment",
    )
    assert rendered_assignment["prompt"] == request.prompt
    assert rendered_assignment["files"] == [
        {
            "path": file_path,
            "description": file_description,
        }
    ]


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


def _request(workspace: Path) -> TaskStartRequest:
    return TaskStartRequest(
        workflow="reviewed-delivery",
        prompt="Complete the requested work.",
        workspace=workspace,
    )


def _read_rendered_section(rendered: str, heading: str) -> dict[str, object]:
    match = re.search(
        rf"^# {re.escape(heading)}\n\n```json\n(?P<body>.*?)\n```$",
        rendered,
        flags=re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise AssertionError(f"missing rendered {heading} section")
    return dict(json.loads(match.group("body")))


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
