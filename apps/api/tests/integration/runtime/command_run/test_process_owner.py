from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import autoclaw.runtime.command_run.process_owner as process_owner_module
import pytest
from autoclaw.persistence.models import CommandRunModel, FlowModel, FlowWaitModel, TaskEventModel
from autoclaw.runtime.command_run import (
    CommandProcessOwner,
    cancel_command_run,
    list_command_runs,
    read_command_run,
    read_command_run_log,
)
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    CommandProcessExited,
    CommandRunCancellationRequested,
    CommandRunDue,
    CommandRunPending,
    CommandRunTerminal,
    RuntimeEffectSignal,
)
from autoclaw.runtime.post_commit.bootstrap import read_command_running_page
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


class _MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 18, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class _OwnerSignalDriver:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self.owner: CommandProcessOwner | None = None
        self.signals: list[RuntimeEffectSignal] = []
        self.deadlines: list[CommandRunDue] = []
        self.terminal = asyncio.Event()
        self.deadline_registered = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        self.signals.append(signal)
        if isinstance(signal, CommandProcessExited):
            self._track(self._dispatch_exit(signal))
        elif isinstance(signal, CommandRunCancellationRequested):
            self._track(self._dispatch_cancellation(signal))
        elif isinstance(signal, CommandRunTerminal):
            self.terminal.set()
        return True

    def register_due(self, signal: CommandRunDue) -> None:
        self.deadlines.append(signal)
        self.deadline_registered.set()

    async def wait_for_terminal(self) -> None:
        await asyncio.wait_for(self.terminal.wait(), timeout=5)
        while self._tasks:
            tasks = tuple(self._tasks)
            await asyncio.gather(*tasks)
            self._tasks.difference_update(task for task in tasks if task.done())

    async def _dispatch_exit(self, signal: CommandProcessExited) -> None:
        assert self.owner is not None
        async with self._session_factory() as session:
            await self.owner.record_command_process_exit(cast(AsyncSession, session), signal)

    async def _dispatch_cancellation(
        self,
        signal: CommandRunCancellationRequested,
    ) -> None:
        assert self.owner is not None
        async with self._session_factory() as session:
            await self.owner.terminate_cancelled_command(cast(AsyncSession, session), signal)

    def _track(self, coroutine: object) -> None:
        assert asyncio.iscoroutine(coroutine)
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def test_process_owner_drains_both_pipes_and_terminalizes_once(
    tmp_path: Path,
) -> None:
    script = (
        "import sys; "
        "sys.stdout.write('o' * 200000); sys.stdout.flush(); "
        "sys.stderr.write('e' * 200000); sys.stderr.flush()"
    )
    async with seeded_executor(tmp_path, suffix="command-process-output") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(executor, ids, [sys.executable, "-c", script])
        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(session_factory, driver, log_byte_limit=4096)
        driver.owner = owner
        async with owner:
            await _handle_pending(owner, session_factory, run_id)
            await driver.wait_for_terminal()

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
            assert source.stdout_logical_path == (f"_runtime/command-runs/{run_id}/stdout.log")
            assert source.stderr_logical_path == (f"_runtime/command-runs/{run_id}/stderr.log")
            assert record.state.value == "succeeded"
            assert record.stdout_log_ref == source.stdout_logical_path
            assert record.stderr_log_ref == source.stderr_logical_path
            assert record.successor_dispatch_id is None
            assert record.terminal_result is not None
            assert record.terminal_result.state.value == "succeeded"
            assert record.terminal_result.started_at == record.started_at
            assert record.terminal_result.ended_at == record.ended_at
            assert record.terminal_result.stdout_log_ref == source.stdout_logical_path
            assert record.terminal_result.stderr_log_ref == source.stderr_logical_path
            assert record.terminal_result.terminal_event_source.value == "process_owner"
            assert listed.items[0].run_id == run_id
            assert log.log_ref == source.stdout_logical_path
            assert log.content == "o" * 4096
            assert (
                tmp_path / "task-command-process-output" / cast(str, source.stderr_logical_path)
            ).read_text(encoding="utf-8") == "e" * 4096

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
            stdout_path = (
                tmp_path
                / "task-command-process-cancel"
                / "_runtime"
                / "command-runs"
                / run_id
                / "stdout.log"
            )
            await asyncio.sleep(0.1)
            assert stdout_path.exists()
            assert "ready" in stdout_path.read_text(encoding="utf-8")
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
            assert source is not None
            assert source.state == "cancelled"
            assert source.ended_at is not None
            assert source.process_metadata_json is None


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
                wait = await session.get(FlowWaitModel, ids.flow_id)
                flow = await session.get(FlowModel, ids.flow_id)
            assert source is not None
            assert source.state == "abandoned"
            assert source.terminal_failure_code == "command_ownership_lost"
            assert source.process_metadata_json is None
            assert wait is None
            assert flow is not None and flow.waiting_cause == "none"


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


async def test_unresolved_environment_ref_fails_without_process_launch(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="command-process-environment") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(
            executor,
            ids,
            [sys.executable, "-V"],
            environment=["approved.secret.ref"],
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
            assert source.started_at is None
            assert source.terminal_failure_code == ("command_environment_resolution_unavailable")


async def test_spawn_failure_removes_unreferenced_command_log_pair(
    tmp_path: Path,
) -> None:
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
            tmp_path
            / "task-command-process-missing-executable"
            / "_runtime"
            / "command-runs"
            / run_id
        )
        assert source is not None
        assert source.state == "failed"
        assert source.started_at is None
        assert source.stdout_logical_path is None
        assert source.stderr_logical_path is None
        assert not log_directory.exists()


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


async def test_shutdown_owner_ignores_late_deadline_without_rewriting_runtime_truth(
    tmp_path: Path,
) -> None:
    clock = _MutableClock()
    async with seeded_executor(tmp_path, suffix="command-process-shutdown") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_argv_command(
            executor,
            ids,
            [sys.executable, "-V"],
            timeout_seconds=1,
        )
        driver = _OwnerSignalDriver(session_factory)
        owner = _command_owner(session_factory, driver, clock=clock)
        driver.owner = owner
        async with owner:
            pass

        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            assert source is not None
            source.state = "running"
            source.ownership_revision = 1
            source.started_at = clock.now
            source.due_at = clock.now
            source.process_metadata_json = {"owner_ref": "durable-owner", "pid": 1234}
            await session.commit()

        async with session_factory() as session:
            await owner.enforce_command_deadline(
                cast(AsyncSession, session),
                CommandRunDue(run_id=run_id, due_at=clock.now),
            )
            source = await session.get(CommandRunModel, run_id)

        assert source is not None
        assert source.state == "running"
        assert source.terminal_failure_code is None
        assert not driver.terminal.is_set()


def _command_owner(
    session_factory: SessionFactory,
    driver: _OwnerSignalDriver,
    *,
    clock: _MutableClock | None = None,
    log_byte_limit: int = 1_048_576,
    terminate_grace_seconds: float = 0.5,
) -> CommandProcessOwner:
    return CommandProcessOwner(
        session_factory=cast(
            Callable[[], AbstractAsyncContextManager[AsyncSession]],
            session_factory,
        ),
        runtime_effect_publisher=driver,
        register_due=driver.register_due,
        clock=clock or _MutableClock(),
        log_byte_limit=log_byte_limit,
        terminate_grace_seconds=terminate_grace_seconds,
        kill_wait_seconds=0.5,
        shutdown_seconds=2,
    )


async def _handle_pending(
    owner: CommandProcessOwner,
    session_factory: SessionFactory,
    run_id: str,
) -> None:
    async with session_factory() as session:
        await owner.launch_pending_command(
            cast(AsyncSession, session),
            CommandRunPending(run_id),
        )


async def _open_argv_command(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
    argv: list[str],
    *,
    timeout_seconds: int | None = None,
    environment: list[str] | None = None,
) -> str:
    response = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="start_command_run",
        arguments={
            "request": {
                "command": {"kind": "argv", "argv": argv},
                "environment": environment or [],
                "timeout_seconds": timeout_seconds,
                "summary": "Run one focused command-owner fixture.",
            }
        },
    )
    return cast(str, response.model_dump()["run_id"])


__all__ = []
