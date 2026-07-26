from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    DispatchRequestModel,
    DispatchTurnModel,
    TaskModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.command_run.continuation import open_command_run_successor
from banksia.runtime.command_run.service import cancel_command_run, read_command_run
from banksia.runtime.command_run.transitions import terminalize_command_run
from banksia.runtime.contracts import CommandRunState
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    CommandRunTerminal,
    DispatchStartDue,
)
from banksia.runtime.prompt import parse_prompt_continuation
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_terminal_command_source_opens_one_same_attempt_successor(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="command-continuation") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_command_run(executor, ids)
        await _terminalize_command_run(session_factory, ids, run_id)
        publisher = CapturedRuntimeEffectPublisher()

        async with session_factory() as session:
            initial_task = await session.get(TaskModel, ids.task_id)
            assert initial_task is not None
            initial_control_revision = initial_task.control_revision
            first = await open_command_run_successor(
                cast(AsyncSession, session),
                signal=CommandRunTerminal(run_id),
                dependencies=_opening_dependencies(publisher),
            )
            duplicate = await open_command_run_successor(
                cast(AsyncSession, session),
                signal=CommandRunTerminal(run_id),
                dependencies=_opening_dependencies(publisher),
            )
            source = await session.get(CommandRunModel, run_id)
            detail = await read_command_run(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                run_id=run_id,
            )
            task = await session.get(TaskModel, ids.task_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            successor = await session.get(DispatchTurnModel, first.dispatch_id)
            dispatch_request = await session.get(DispatchRequestModel, first.dispatch_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert first.outcome == "opened"
    assert duplicate.outcome == "skipped"
    assert first.dispatch_id is not None
    assert source is not None and source.successor_dispatch_id == first.dispatch_id
    assert detail.successor_dispatch_id == first.dispatch_id
    assert attempt is not None
    assert attempt.current_dispatch_id == first.dispatch_id
    assert attempt.current_wait_id is None
    assert task is not None and task.control_revision == initial_control_revision
    assert successor is not None and successor.opened_reason == "command_result"
    assert successor.assignment_id == ids.root_assignment_id
    assert successor.attempt_id == ids.root_attempt_id
    assert dispatch_count == 4
    assert dispatch_request is not None
    trigger = _read_trigger(dispatch_request.input)
    _assert_command_trigger(
        trigger,
        run_id=run_id,
        source_dispatch_id=ids.current_dispatch_id,
        output_path=f".banksia/{ids.task_id}/command-runs/{run_id}/output.log",
    )
    assert len(publisher.signals) == 1
    signal = publisher.signals[0]
    assert isinstance(signal, DispatchStartDue)
    assert signal.dispatch_id == first.dispatch_id


def _assert_command_trigger(
    trigger: dict[str, object],
    *,
    run_id: str,
    source_dispatch_id: str,
    output_path: str,
) -> None:
    source_payload = cast(dict[str, object], trigger["source"])
    result_payload = cast(dict[str, object], trigger["result"])
    terminal_payload = cast(dict[str, object], result_payload["terminal"])
    assert trigger["kind"] == "command_result"
    assert source_payload["command_id"] == run_id
    assert source_payload["source_dispatch_id"] == source_dispatch_id
    assert result_payload["request"] == {
        "command": {"kind": "argv", "argv": ["python", "-V"]},
        "cwd": None,
        "timeout_seconds": None,
        "summary": "Read the Python version.",
    }
    assert terminal_payload["state"] == "succeeded"
    assert terminal_payload["exit_code"] == 0
    assert terminal_payload["summary"] == "Python reported its version successfully."
    assert terminal_payload["started_at"] == terminal_payload["ended_at"]
    assert terminal_payload["output_path"] == output_path
    assert terminal_payload["output_observed_bytes"] == 21
    assert terminal_payload["output_written_bytes"] == 21
    assert terminal_payload["output_complete"] is True
    assert terminal_payload["terminal_event_source"] == "process_owner"
    assert "files" not in result_payload


async def test_nonterminal_command_signal_is_a_harmless_noop(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="command-nonterminal") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_command_run(executor, ids)
        publisher = CapturedRuntimeEffectPublisher()
        async with session_factory() as session:
            result = await open_command_run_successor(
                cast(AsyncSession, session),
                signal=CommandRunTerminal(run_id),
                dependencies=_opening_dependencies(publisher),
            )
            source = await session.get(CommandRunModel, run_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
            )
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert result.outcome == "skipped"
    assert source is not None and source.state == "pending_start"
    assert source.successor_dispatch_id is None
    assert attempt is not None and wait is not None
    assert attempt.current_wait_id == wait.wait_id
    assert dispatch_count == 3
    assert publisher.signals == ()

    async with session_factory() as session:
        cancelled = await cancel_command_run(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            run_id=run_id,
        )
    async with session_factory() as session:
        attempt = await session.get(AttemptModel, ids.root_attempt_id)
        wait = await session.scalar(
            select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
        )
    assert cancelled.run.state == CommandRunState.CANCELLATION_REQUESTED
    assert attempt is not None and wait is not None
    assert attempt.current_wait_id == wait.wait_id


async def _open_command_run(executor: NodeOperationExecutor, ids: RuntimeIds) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id),
        operation_name="start_command_run",
        arguments={
            "request": {
                "command": {"kind": "argv", "argv": ["python", "-V"]},
                "summary": "Read the Python version.",
            }
        },
    )
    return cast(str, opened.model_dump()["command_id"])


async def _terminalize_command_run(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    run_id: str,
) -> None:
    now = utc_now()
    async with session_factory() as session:
        source = await session.get(CommandRunModel, run_id)
        assert source is not None
        source.state = "running"
        source.started_at = now
        await session.commit()
    async with session_factory() as session:
        won = await terminalize_command_run(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            run_id=run_id,
            expected_ownership_revision=0,
            expected_states=(CommandRunState.RUNNING,),
            terminal_state=CommandRunState.SUCCEEDED,
            summary="Python reported its version successfully.",
            ended_at=now,
            exit_code=0,
            output_observed_bytes=21,
            output_written_bytes=21,
            is_output_complete=True,
        )
    assert won is True


def _opening_dependencies(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
    )


def _read_trigger(input_text: str) -> dict[str, object]:
    continuation = parse_prompt_continuation(input_text)
    assert continuation is not None
    return continuation.trigger.model_dump(mode="json")


__all__ = []
