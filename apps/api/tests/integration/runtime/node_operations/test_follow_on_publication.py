from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import autoclaw.runtime.node_operations.executor as executor_module
import pytest
from autoclaw.persistence.models import AssignmentModel, CommandRunModel, HumanRequestModel
from autoclaw.runtime.checkpoint import CheckpointPreparation
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.node_operations import NodeOperationScope
from autoclaw.runtime.post_commit.publisher import CapturedRuntimeEffectPublisher
from autoclaw.runtime.post_commit.signals import (
    CommandRunPending,
    HumanRequestOpened,
    RuntimeEffectSignal,
)
from autoclaw.runtime.projection.signals import (
    ArtifactProjection,
    LatestCheckpointProjection,
    SupportProjectionSignal,
    TransientProjection,
)
from tests.helpers.executor_harness import seeded_executor


class _CapturedProjectionPublisher:
    def __init__(self) -> None:
        self.signals: list[SupportProjectionSignal] = []

    def publish(self, signal: SupportProjectionSignal) -> bool:
        self.signals.append(signal)
        return True


class _RaisingRuntimePublisher:
    def __init__(self) -> None:
        self.signals: list[RuntimeEffectSignal] = []

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        self.signals.append(signal)
        raise RuntimeError("publisher unavailable")


async def test_human_request_publishes_only_exact_open_signal_after_commit(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    due_at = utc_now() + timedelta(minutes=5)
    async with seeded_executor(
        tmp_path,
        suffix="human-follow-on",
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="open_human_request",
            arguments={
                "request": {
                    "kind": "direction",
                    "summary": "Choose one bounded direction.",
                    "items": [
                        {
                            "id": "direction",
                            "prompt": "Which direction?",
                            "options": [{"id": "a", "title": "A"}],
                        }
                    ],
                    "timeout": {"due_at": due_at},
                }
            },
        )
        request_id = response.model_dump()["request_id"]
        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)

    assert source is not None
    assert publisher.signals == (HumanRequestOpened(request_id),)


async def test_command_run_commit_survives_runtime_publication_exception(
    tmp_path: Path,
) -> None:
    publisher = _RaisingRuntimePublisher()
    async with seeded_executor(
        tmp_path,
        suffix="command-follow-on-failure",
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="start_command_run",
            arguments={
                "request": {
                    "command": {"kind": "argv", "argv": ["python", "-V"]},
                    "summary": "Read the Python version.",
                }
            },
        )
        run_id = response.model_dump()["run_id"]
        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)

    assert source is not None and source.state == "pending_start"
    assert publisher.signals == [CommandRunPending(run_id)]


async def test_checkpoint_publishes_exact_support_projection_signals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _CapturedProjectionPublisher()

    async def keep_prepared_bodies(
        preparation: CheckpointPreparation,
    ) -> CheckpointPreparation:
        return preparation

    monkeypatch.setattr(
        executor_module,
        "publish_checkpoint_bodies",
        keep_prepared_bodies,
    )
    async with seeded_executor(
        tmp_path,
        suffix="checkpoint-follow-on",
        support_projection_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        task_root = tmp_path / "task-checkpoint-follow-on"
        (task_root / "workspace" / "report.md").write_text("report\n", encoding="utf-8")
        (task_root / "workspace" / "run.log").write_text("log\n", encoding="utf-8")
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.produces_json = [{"slot": "report", "description": "Report."}]
            await session.commit()

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "progress",
                    "handoff": {"summary": "Recorded.", "next_step": "Continue."},
                    "produced_artifacts": [{"slot": "report", "path": "workspace/report.md"}],
                    "transient_surfaces": [
                        {"path": "workspace/run.log", "description": "Run log."}
                    ],
                }
            },
        )

    checkpoint_id = response.model_dump()["checkpoint_id"]
    assert publisher.signals[0] == LatestCheckpointProjection(
        attempt_id=ids.root_attempt_id,
        checkpoint_id=checkpoint_id,
    )
    assert isinstance(publisher.signals[1], ArtifactProjection)
    assert publisher.signals[1].version == 1
    assert isinstance(publisher.signals[2], TransientProjection)
