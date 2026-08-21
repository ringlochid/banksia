from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from oh_my_subagents.persistence.models import CommandRunModel, HumanRequestModel
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.node_operations import NodeOperationScope
from oh_my_subagents.runtime.post_commit.publisher import CapturedRuntimeEffectPublisher
from oh_my_subagents.runtime.post_commit.signals import (
    CommandRunPending,
    HumanRequestOpened,
    RuntimeEffectSignal,
)
from tests.helpers.executor_harness import seeded_executor


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
