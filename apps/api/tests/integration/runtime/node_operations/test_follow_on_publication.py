from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from banksia.persistence.models import CommandRunModel, HumanRequestModel
from banksia.runtime.clock import utc_now
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.post_commit.publisher import CapturedRuntimeEffectPublisher
from banksia.runtime.post_commit.signals import (
    BoundaryAccepted,
    CommandRunPending,
    HumanRequestOpened,
    RuntimeEffectSignal,
)
from banksia.runtime.projection.signals import SupportProjectionSignal
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
                            "options": [
                                {"id": "a", "title": "A"},
                                {"id": "b", "title": "B"},
                            ],
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
        run_id = response.model_dump()["command_id"]
        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)

    assert source is not None and source.state == "pending_start"
    assert publisher.signals == [CommandRunPending(run_id)]


async def test_terminal_checkpoint_publishes_boundary_only_after_commit(
    tmp_path: Path,
) -> None:
    runtime_publisher = CapturedRuntimeEffectPublisher()
    projection_publisher = _CapturedProjectionPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="checkpoint-follow-on",
        runtime_effect_publisher=runtime_publisher,
        support_projection_publisher=projection_publisher,
    ) as (executor, _session_factory, ids, _activity_signals):
        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "The exact blocker is recorded.",
                "outcome": "blocked",
            },
        )

    assert response.model_dump()["terminal"] is True
    assert runtime_publisher.signals == (BoundaryAccepted(ids.current_dispatch_id),)
    assert projection_publisher.signals == []
