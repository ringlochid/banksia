from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import oh_my_subagents.runtime.command_run.process_owner as process_owner_module
from oh_my_subagents.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    TaskEventModel,
)
from oh_my_subagents.runtime.command_run import (
    cancel_command_run,
    list_command_runs,
    read_command_run,
    read_command_run_log,
)
from oh_my_subagents.runtime.command_run.task_paths import (
    StableCommandWorkingDirectory,
)
from oh_my_subagents.runtime.post_commit import (
    CommandProcessExited,
    CommandRunPending,
)
from oh_my_subagents.runtime.post_commit.external_wait_startup import read_command_running_page
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
    assert source.output_path == f".oms/{ids.task_id}/command-runs/{run_id}/output.log"
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group proof")
async def test_process_owner_cancel_terminates_command_grandchild(
    tmp_path: Path,
) -> None:
    grandchild_script = (
        "import signal, time; signal.signal(signal.SIGTERM, lambda *_: None); time.sleep(60)"
    )
    script = (
        "import os, subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', {grandchild_script!r}]); "
        "print(f'leader={os.getpid()} grandchild={child.pid}', flush=True); "
        "time.sleep(60)"
    )
    grandchild_pid: int | None = None
    try:
        async with seeded_executor(tmp_path, suffix="command-process-family-cancel") as (
            executor,
            session_factory,
            ids,
            _,
        ):
            run_id = await _open_argv_command(
                executor,
                ids,
                [sys.executable, "-c", script],
            )
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
                    seeded_task_root(tmp_path, "command-process-family-cancel")
                    / "command-runs"
                    / run_id
                    / "output.log"
                )
                await _wait_for_output(output_path, b"grandchild=")
                grandchild_pid = _read_grandchild_pid(output_path)
                async with session_factory() as session:
                    await cancel_command_run(
                        cast(AsyncSession, session),
                        task_id=ids.task_id,
                        run_id=run_id,
                        actor_ref="local-test",
                        runtime_effect_publisher=driver,
                    )
                await driver.wait_for_terminal()

            assert grandchild_pid is not None
            await _assert_process_exited(grandchild_pid)
    finally:
        if grandchild_pid is not None and _process_exists(grandchild_pid):
            os.kill(grandchild_pid, signal.SIGKILL)


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
    close_count = 0

    def record_close(working_directory: StableCommandWorkingDirectory) -> None:
        nonlocal close_count
        close_count += 1
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
        assert close_count == 1


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


def _read_grandchild_pid(output_path: Path) -> int:
    record = output_path.read_text(encoding="utf-8").strip().splitlines()[0]
    fields = dict(field.split("=", 1) for field in record.split())
    return int(fields["grandchild"])


async def _assert_process_exited(pid: int) -> None:
    for _ in range(100):
        if not _process_exists(pid):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"owned command descendant {pid} survived termination")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


__all__ = []
