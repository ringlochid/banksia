from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    TaskModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.command_run import cancel_command_run
from banksia.runtime.command_run.transitions import terminalize_command_run
from banksia.runtime.contracts import CommandRunState
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.task_control.service import cancel_runtime_task
from tests.helpers.command_process import open_argv_command
from tests.helpers.postgres_runtime_race import (
    PostgresRuntimeHarness,
    observe_update_order,
    observe_update_started,
    postgres_runtime_harness,
    wait_for_thread_event,
)


async def test_command_exit_rechecks_cancelled_owner_after_wait_race() -> None:
    await _assert_task_cancellation_wins_command_exit_race()
    await _assert_command_exit_wins_task_cancellation_race()


async def _assert_task_cancellation_wins_command_exit_race() -> None:
    async with postgres_runtime_harness(suffix="command-exit-cancel") as harness:
        (
            run_id,
            ownership_revision,
            current_team_revision_id,
            control_revision,
        ) = await _prepare_cancellation_requested_command(harness)

        async with harness.session_factory() as blocker:
            locked_run_id = await blocker.scalar(
                select(CommandRunModel.run_id)
                .where(CommandRunModel.run_id == run_id)
                .with_for_update()
            )
            assert locked_run_id == run_id
            with observe_update_started(
                harness.engine,
                table_name="command_runs",
            ) as terminal_update_started:
                terminal_task = asyncio.create_task(
                    _terminalize_cancelled_command(
                        harness,
                        run_id=run_id,
                        ownership_revision=ownership_revision,
                    )
                )
                await wait_for_thread_event(terminal_update_started)
                async with harness.session_factory() as session:
                    cancelled = await cancel_runtime_task(
                        session,
                        harness.ids.task_id,
                        expected_team_revision_id=current_team_revision_id,
                        expected_control_revision=control_revision,
                    )
                await blocker.rollback()
                terminal_won = await asyncio.wait_for(terminal_task, timeout=20)

        async with harness.session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            attempt = await session.get(AttemptModel, harness.ids.root_attempt_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
            )

    assert cancelled.status.value == "cancelled"
    assert terminal_won
    assert source is not None and source.state == CommandRunState.CANCELLED.value
    assert source.successor_dispatch_id is None
    assert attempt is not None and attempt.status == "cancelled"
    assert attempt.current_dispatch_id is None and attempt.current_wait_id is None
    assert wait is None


async def _assert_command_exit_wins_task_cancellation_race() -> None:
    async with postgres_runtime_harness(suffix="command-exit-terminal") as harness:
        (
            run_id,
            ownership_revision,
            current_team_revision_id,
            control_revision,
        ) = await _prepare_cancellation_requested_command(harness)

        async with harness.session_factory() as blocker:
            locked_attempt_id = await blocker.scalar(
                select(AttemptModel.attempt_id)
                .where(AttemptModel.attempt_id == harness.ids.root_attempt_id)
                .with_for_update()
            )
            assert locked_attempt_id == harness.ids.root_attempt_id
            with observe_update_order(
                harness.engine,
                table_name="attempts",
            ) as attempt_updates:
                terminal_task = asyncio.create_task(
                    _terminalize_cancelled_command(
                        harness,
                        run_id=run_id,
                        ownership_revision=ownership_revision,
                    )
                )
                await wait_for_thread_event(attempt_updates.first_update_started)
                cancellation_task = asyncio.create_task(
                    _cancel_task(
                        harness,
                        current_team_revision_id=current_team_revision_id,
                        control_revision=control_revision,
                    )
                )
                await wait_for_thread_event(attempt_updates.second_update_started)
                await blocker.rollback()
                terminal_result, cancellation_result = await asyncio.wait_for(
                    asyncio.gather(
                        terminal_task,
                        cancellation_task,
                        return_exceptions=True,
                    ),
                    timeout=20,
                )

        async with harness.session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            task = await session.get(TaskModel, harness.ids.task_id)
            attempt = await session.get(AttemptModel, harness.ids.root_attempt_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
            )

    assert terminal_result is True
    assert isinstance(cancellation_result, RuntimeOperationError)
    assert cancellation_result.code == OperationFailureCode.CONFLICT
    assert source is not None and source.state == CommandRunState.CANCELLED.value
    assert source.successor_dispatch_id is None
    assert task is not None and task.status == "running"
    assert task.control_revision == control_revision
    assert attempt is not None and attempt.status == "running"
    assert attempt.current_dispatch_id is None and attempt.current_wait_id is None
    assert wait is None


async def _prepare_cancellation_requested_command(
    harness: PostgresRuntimeHarness,
) -> tuple[str, int, str, int]:
    run_id = await open_argv_command(
        harness.executor,
        harness.ids,
        [sys.executable, "-V"],
    )
    async with harness.session_factory() as session:
        await cancel_command_run(
            session,
            task_id=harness.ids.task_id,
            run_id=run_id,
        )
        source = await session.get(CommandRunModel, run_id)
        task = await session.get(TaskModel, harness.ids.task_id)
        assert source is not None and task is not None
        assert source.state == CommandRunState.CANCELLATION_REQUESTED.value
        assert task.current_team_revision_id is not None
        return (
            run_id,
            source.ownership_revision,
            task.current_team_revision_id,
            task.control_revision,
        )


async def _cancel_task(
    harness: PostgresRuntimeHarness,
    *,
    current_team_revision_id: str,
    control_revision: int,
) -> object:
    async with harness.session_factory() as session:
        return await cancel_runtime_task(
            session,
            harness.ids.task_id,
            expected_team_revision_id=current_team_revision_id,
            expected_control_revision=control_revision,
        )


async def _terminalize_cancelled_command(
    harness: PostgresRuntimeHarness,
    *,
    run_id: str,
    ownership_revision: int,
) -> bool:
    async with harness.session_factory() as session:
        return await terminalize_command_run(
            session,
            task_id=harness.ids.task_id,
            run_id=run_id,
            expected_ownership_revision=ownership_revision,
            expected_states=(CommandRunState.CANCELLATION_REQUESTED,),
            terminal_state=CommandRunState.CANCELLED,
            summary="The cancelled Task's command process stopped.",
            ended_at=utc_now(),
        )


__all__ = []
