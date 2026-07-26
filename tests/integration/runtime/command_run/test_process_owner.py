from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import banksia.runtime.command_run.process_owner as process_owner_module
from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    TaskEventModel,
    TaskModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.command_run import (
    cancel_command_run,
    list_command_runs,
    read_command_run,
    read_command_run_log,
)
from banksia.runtime.command_run.task_paths import (
    StableCommandWorkingDirectory,
)
from banksia.runtime.command_run.transitions import terminalize_command_run
from banksia.runtime.contracts import CommandRunState
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import (
    CommandProcessExited,
    CommandRunPending,
)
from banksia.runtime.post_commit.external_wait_startup import read_command_running_page
from banksia.runtime.task_control.service import cancel_runtime_task
from tests.helpers.command_process import (
    MutableClock as _MutableClock,
)
from tests.helpers.command_process import (
    OwnerSignalDriver as _OwnerSignalDriver,
)
from tests.helpers.command_process import (
    command_process_owner as _command_owner,
)
from tests.helpers.command_process import (
    launch_pending_command as _handle_pending,
)
from tests.helpers.command_process import (
    open_argv_command as _open_argv_command,
)
from tests.helpers.command_process import (
    wait_for_command_output as _wait_for_output,
)
from tests.helpers.executor_harness import SessionFactory, seeded_executor, seeded_task_root
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.postgres_runtime_race import (
    PostgresRuntimeHarness,
    observe_update_order,
    observe_update_started,
    postgres_runtime_harness,
    wait_for_thread_event,
)


async def test_process_owner_preserves_combined_stream_and_terminalizes_once(
    tmp_path: Path,
) -> None:
    records = [f"out-{index}\nerr-{index}\n".encode() for index in range(2_000)]
    expected_output = b"".join(records)
    script = (
        "import os; "
        "["
        "(os.write(1, f'out-{index}\\n'.encode()), "
        "os.write(2, f'err-{index}\\n'.encode())) "
        "for index in range(2000)"
        "]"
    )
    async with seeded_executor(tmp_path, suffix="command-process-output") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(executor, ids, [sys.executable, "-c", script])
        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(session_factory, driver)
        driver.owner = owner
        async with owner:
            await _handle_pending(owner, session_factory, run_id)
            await driver.wait_for_terminal()

            await _assert_combined_output_contract(
                tmp_path,
                session_factory,
                ids,
                run_id,
                expected_output,
            )

            exit_signal = next(
                signal for signal in driver.signals if isinstance(signal, CommandProcessExited)
            )
            async with session_factory() as session:
                await owner.record_command_process_exit(
                    cast(AsyncSession, session),
                    exit_signal,
                )
                terminal_event_count = await session.scalar(
                    select(func.count())
                    .select_from(TaskEventModel)
                    .where(TaskEventModel.event_type == "command_run_succeeded")
                )
            assert terminal_event_count == 1


async def _assert_combined_output_contract(
    tmp_path: Path,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    run_id: str,
    expected_output: bytes,
) -> None:
    async with session_factory() as session:
        source = await session.get(CommandRunModel, run_id)
        record = await read_command_run(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            run_id=run_id,
        )
        listed = await list_command_runs(
            cast(AsyncSession, session),
            task_id=ids.task_id,
        )
        log = await read_command_run_log(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            run_id=run_id,
        )
    assert source is not None
    assert source.state == "succeeded"
    assert source.process_metadata_json is None
    assert source.output_path == f".banksia/{ids.task_id}/command-runs/{run_id}/output.log"
    assert source.output_observed_bytes == len(expected_output)
    assert source.output_written_bytes == len(expected_output)
    assert source.output_complete is True
    assert record.state.value == "succeeded"
    assert record.output_path == source.output_path
    assert record.successor_dispatch_id is None
    assert record.terminal_result is not None
    assert record.terminal_result.state.value == "succeeded"
    assert record.terminal_result.started_at == record.started_at
    assert record.terminal_result.ended_at == record.ended_at
    assert record.terminal_result.output_path == source.output_path
    assert record.terminal_result.output_observed_bytes == len(expected_output)
    assert record.terminal_result.output_written_bytes == len(expected_output)
    assert record.terminal_result.output_complete is True
    assert record.terminal_result.terminal_event_source.value == "process_owner"
    assert listed.items[0].run_id == run_id
    assert listed.items[0].output_path == source.output_path
    assert log.output_path == source.output_path
    assert log.content.encode() == expected_output
    assert log.bytes_read == len(expected_output)
    assert log.next_offset is None
    assert log.file_size == len(expected_output)
    assert log.is_missing is False
    assert log.is_changed is False
    assert (
        seeded_task_root(tmp_path, "command-process-output")
        / "command-runs"
        / run_id
        / "output.log"
    ).read_bytes() == expected_output


async def test_process_owner_timeout_uses_launch_time_deadline(
    tmp_path: Path,
) -> None:
    clock = _MutableClock()
    async with seeded_executor(tmp_path, suffix="command-process-timeout") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(
            executor,
            ids,
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout_seconds=1,
        )
        async with session_factory() as session:
            pending = await session.get(CommandRunModel, run_id)
            assert pending is not None
            assert pending.started_at is None
            assert pending.due_at is None

        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(session_factory, driver, clock=clock)
        driver.owner = owner
        async with owner:
            await _handle_pending(owner, session_factory, run_id)
            await asyncio.wait_for(driver.deadline_registered.wait(), timeout=2)
            due = driver.deadlines[0]
            assert due.due_at == clock.now + timedelta(seconds=1)
            clock.now = due.due_at
            async with session_factory() as session:
                await owner.enforce_command_deadline(cast(AsyncSession, session), due)
            await driver.wait_for_terminal()

            async with session_factory() as session:
                source = await session.get(CommandRunModel, run_id)
            assert source is not None
            assert source.state == "timed_out"
            assert source.due_at is not None
            stored_due_at = (
                source.due_at.replace(tzinfo=UTC)
                if source.due_at.tzinfo is None
                else source.due_at.astimezone(UTC)
            )
            assert stored_due_at == due.due_at
            assert source.terminal_failure_code == "command_timed_out"
            assert source.process_metadata_json is None


async def test_process_owner_escalates_cancel_and_reaps_ignoring_child(
    tmp_path: Path,
) -> None:
    script = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGTERM, lambda *_: None); "
        "sys.stdout.write('ready\\n'); sys.stdout.flush(); "
        "time.sleep(60)"
    )
    async with seeded_executor(tmp_path, suffix="command-process-cancel") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(executor, ids, [sys.executable, "-c", script])
        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(
            session_factory,
            driver,
            terminate_grace_seconds=0.05,
        )
        driver.owner = owner
        async with owner:
            await _handle_pending(owner, session_factory, run_id)
            output_path = (
                seeded_task_root(tmp_path, "command-process-cancel")
                / "command-runs"
                / run_id
                / "output.log"
            )
            await _wait_for_output(output_path, b"ready")
            async with session_factory() as session:
                response = await cancel_command_run(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    run_id=run_id,
                    actor_ref="local-test",
                    runtime_effect_publisher=driver,
                )
            assert response.run.state.value == "cancellation_requested"
            await driver.wait_for_terminal()

            async with session_factory() as session:
                source = await session.get(CommandRunModel, run_id)
                attempt = await session.get(AttemptModel, ids.root_attempt_id)
                wait = await session.scalar(
                    select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
                )
            assert source is not None
            assert source.state == "cancelled"
            assert source.ended_at is not None
            assert source.process_metadata_json is None
            assert attempt is not None and attempt.current_wait_id is None
            assert wait is None


async def test_restart_marks_unprovable_command_ownership_abandoned(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="command-process-restart") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(executor, ids, [sys.executable, "-V"])
        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            assert source is not None
            source.ownership_revision = 1
            source.process_metadata_json = {"owner_ref": "lost-owner", "phase": "launching"}
            await session.commit()

        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(session_factory, driver)
        driver.owner = owner
        async with owner:
            await _handle_pending(owner, session_factory, run_id)
            await driver.wait_for_terminal()
            async with session_factory() as session:
                source = await session.get(CommandRunModel, run_id)
                attempt = await session.get(AttemptModel, ids.root_attempt_id)
                wait = await session.scalar(
                    select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
                )
            assert source is not None
            assert source.state == "abandoned"
            assert source.terminal_failure_code == "command_ownership_lost"
            assert source.process_metadata_json is None
            assert wait is None
            assert attempt is not None and attempt.current_wait_id is None


async def test_startup_running_command_routes_to_ownership_loss_recovery(
    tmp_path: Path,
) -> None:
    clock = _MutableClock()
    async with seeded_executor(tmp_path, suffix="command-running-startup") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(executor, ids, [sys.executable, "-V"])
        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            assert source is not None
            source.state = "running"
            source.ownership_revision = 1
            source.started_at = clock.now
            source.process_metadata_json = {"owner_ref": "lost-owner", "pid": 1234}
            await session.commit()

        page = await read_command_running_page(
            cast(
                Callable[[], AbstractAsyncContextManager[AsyncSession]],
                session_factory,
            ),
            None,
            200,
        )
        assert page.sources == (CommandRunPending(run_id),)

        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(session_factory, driver, clock=clock)
        driver.owner = owner
        async with owner:
            await _handle_pending(owner, session_factory, run_id)
            await driver.wait_for_terminal()

        async with session_factory() as session:
            recovered = await session.get(CommandRunModel, run_id)
        assert recovered is not None
        assert recovered.state == "abandoned"
        assert recovered.terminal_failure_code == "command_ownership_lost"


async def test_spawn_failure_keeps_referenced_incomplete_command_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_close = process_owner_module.close_command_working_directory
    closed_descriptors: list[int] = []

    def record_close(working_directory: StableCommandWorkingDirectory) -> None:
        closed_descriptors.append(working_directory.descriptor)
        original_close(working_directory)

    monkeypatch.setattr(
        process_owner_module,
        "close_command_working_directory",
        record_close,
    )
    async with seeded_executor(tmp_path, suffix="command-process-missing-executable") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(
            executor,
            ids,
            [str(tmp_path / "definitely-missing-command")],
        )
        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(session_factory, driver)
        driver.owner = owner
        async with owner:
            await _handle_pending(owner, session_factory, run_id)
            await driver.wait_for_terminal()

        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
        log_directory = (
            seeded_task_root(tmp_path, "command-process-missing-executable")
            / "command-runs"
            / run_id
        )
        assert source is not None
        assert source.state == "failed"
        assert source.started_at is None
        assert source.output_observed_bytes == 0
        assert source.output_written_bytes == 0
        assert source.output_complete is False
        assert (log_directory / "output.log").read_bytes() == b""
        assert len(closed_descriptors) == 1


async def test_process_owner_reaps_child_when_running_state_persistence_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_running_state(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("injected running-state persistence failure")

    monkeypatch.setattr(
        process_owner_module,
        "mark_command_run_running",
        fail_running_state,
    )
    async with seeded_executor(tmp_path, suffix="command-process-persistence-failure") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(
            executor,
            ids,
            [sys.executable, "-c", "import time; time.sleep(60)"],
        )
        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(session_factory, driver)
        driver.owner = owner
        async with owner:
            await _handle_pending(owner, session_factory, run_id)
            await driver.wait_for_terminal()

        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
        assert source is not None
        assert source.state == "failed"
        assert source.terminal_failure_code == "command_launch_state_failed"
        assert source.process_metadata_json is None


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
    run_id = await _open_argv_command(
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
