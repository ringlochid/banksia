from __future__ import annotations

from pathlib import Path
from typing import Any

import banksia.runtime.task_start as task_start_module
import pytest
from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    FlowModel,
    FlowRevisionModel,
    FlowStartSourceModel,
    TaskEventModel,
    TaskModel,
    TeamRevisionModel,
)
from banksia.runtime.contracts import TaskStartRequest
from banksia.runtime.post_commit import FlowStartCommitted, RuntimeEffectSignal
from banksia.runtime.projection.signals import SupportProjectionSignal
from banksia.runtime.task_start import start_task
from banksia.workflows.authoring import create_workflow_draft, publish_workflow_draft
from banksia.workflows.catalog import read_current_published_workflow
from sqlalchemy import func, select
from tests.helpers.workflow_runtime import initialized_workflow_database


class _CommittedRuntimePublisher:
    def __init__(self, session: Any, *, should_raise: bool = False) -> None:
        self._session = session
        self._should_raise = should_raise
        self.signals: list[RuntimeEffectSignal] = []

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        assert not self._session.in_transaction()
        self.signals.append(signal)
        if self._should_raise:
            raise RuntimeError("runtime publication unavailable")
        return True


class _CommittedSupportPublisher:
    def __init__(self, session: Any, *, should_raise: bool = False) -> None:
        self._session = session
        self._should_raise = should_raise
        self.signals: list[SupportProjectionSignal] = []

    def publish(self, signal: SupportProjectionSignal) -> bool:
        assert not self._session.in_transaction()
        self.signals.append(signal)
        if self._should_raise:
            raise RuntimeError("support publication unavailable")
        return True


async def test_task_start_commits_one_exact_workflow_launch_before_disposable_hints(
    tmp_path: Path,
) -> None:
    request = _request("committed-workflow-bridge")
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            runtime_publisher = _CommittedRuntimePublisher(session, should_raise=True)
            support_publisher = _CommittedSupportPublisher(session, should_raise=True)
            response = await start_task(
                request,
                data_dir=tmp_path / "task-data",
                session=session,
                runtime_effect_publisher=runtime_publisher,
                support_projection_publisher=support_publisher,
            )

            task = await session.get(TaskModel, response.task_id)
            team_revision_count = await _task_row_count(
                session,
                TeamRevisionModel,
                response.task_id,
            )
            assignment_count = await _task_row_count(
                session,
                AssignmentModel,
                response.task_id,
            )
            attempt_count = await _task_row_count(session, AttemptModel, response.task_id)
            flow_count = await _task_row_count(session, FlowModel, response.task_id)
            flow_revision_count = await session.scalar(
                select(func.count())
                .select_from(FlowRevisionModel)
                .join(FlowModel, FlowModel.flow_id == FlowRevisionModel.flow_id)
                .where(FlowModel.task_id == response.task_id)
            )
            start_source_count = await _task_row_count(
                session,
                FlowStartSourceModel,
                response.task_id,
            )
            event_count = await _task_row_count(session, TaskEventModel, response.task_id)

            current = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
            draft = await create_workflow_draft(
                session,
                workflow=current.workflow.model_copy(
                    update={"description": "A later published Workflow revision."}
                ),
            )
            later = await publish_workflow_draft(
                session,
                draft_id=draft.draft_id,
                expected_etag=draft.etag,
            )
            await session.commit()
            pinned_task = await session.get(TaskModel, response.task_id)

    assert task is not None and task.workflow_revision_no == 1
    assert task.current_team_revision_id is not None
    assert (
        team_revision_count,
        assignment_count,
        attempt_count,
        flow_count,
        flow_revision_count,
        start_source_count,
        event_count,
    ) == (1, 1, 1, 1, 1, 1, 1)
    assert later.revision_no == 2
    assert pinned_task is not None and pinned_task.workflow_revision_no == 1
    assert runtime_publisher.signals == [FlowStartCommitted(f"flow.{response.task_id}")]
    assert support_publisher.signals


async def test_task_start_rolls_back_unknown_workflow_and_partial_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            runtime_publisher = _CommittedRuntimePublisher(session)
            support_publisher = _CommittedSupportPublisher(session)
            with pytest.raises(FileNotFoundError, match="missing-workflow"):
                await start_task(
                    _request("unknown-workflow", workflow_id="missing-workflow"),
                    data_dir=tmp_path / "task-data",
                    session=session,
                    runtime_effect_publisher=runtime_publisher,
                    support_projection_publisher=support_publisher,
                )
            assert await _task_count(session) == 0
            assert runtime_publisher.signals == []
            assert support_publisher.signals == []

            real_launch = task_start_module.launch_task_runtime

            async def fail_after_partial_staging(
                target_session: Any,
                launch_input: Any,
            ) -> Any:
                workflow = await read_current_published_workflow(
                    target_session,
                    workflow_id=launch_input.task_compose.workflow.key,
                )
                target_session.add(
                    TaskModel(
                        task_id=launch_input.task_id,
                        task_key=launch_input.task_compose.task.key,
                        title=launch_input.task_compose.task.title,
                        summary=launch_input.task_compose.task.summary,
                        instruction=launch_input.task_compose.task.instruction,
                        workflow_key=workflow.workflow_id,
                        workflow_revision_no=workflow.revision_no,
                        workflow_content_hash=workflow.content_hash,
                        current_team_revision_id=None,
                        task_root_path=str(launch_input.task_root),
                    )
                )
                await target_session.flush()
                raise RuntimeError("partial staging failed")

            monkeypatch.setattr(
                task_start_module,
                "launch_task_runtime",
                fail_after_partial_staging,
            )
            with pytest.raises(RuntimeError, match="partial staging failed"):
                await start_task(
                    _request("partial-staging"),
                    data_dir=tmp_path / "task-data",
                    session=session,
                    runtime_effect_publisher=runtime_publisher,
                    support_projection_publisher=support_publisher,
                )
            assert await _task_count(session) == 0
            assert runtime_publisher.signals == []
            assert support_publisher.signals == []
            monkeypatch.setattr(task_start_module, "launch_task_runtime", real_launch)


async def _task_count(session: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(TaskModel)) or 0)


async def _task_row_count(session: Any, model: Any, task_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(model).where(model.task_id == task_id)
        )
        or 0
    )


def _request(
    task_key: str,
    *,
    workflow_id: str = "reviewed-delivery",
) -> TaskStartRequest:
    return TaskStartRequest.model_validate(
        {
            "task": {
                "key": task_key,
                "title": "Workflow-only start bridge",
                "summary": "Commit exact Workflow truth without generic Definition lookup.",
            },
            "workflow": {"key": workflow_id},
        }
    )
