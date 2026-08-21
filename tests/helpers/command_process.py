from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.runtime.command_run import CommandProcessOwner
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from oh_my_subagents.runtime.post_commit import (
    CommandProcessExited,
    CommandRunCancellationRequested,
    CommandRunDue,
    CommandRunPending,
    CommandRunTerminal,
    RuntimeEffectSignal,
)
from tests.helpers.executor_harness import SessionFactory
from tests.helpers.lineage_seed import RuntimeIds


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 18, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class OwnerSignalDriver:
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


def command_process_owner(
    session_factory: SessionFactory,
    driver: OwnerSignalDriver,
    *,
    clock: MutableClock | None = None,
    terminate_grace_seconds: float = 0.5,
) -> CommandProcessOwner:
    return CommandProcessOwner(
        session_factory=cast(
            Callable[[], AbstractAsyncContextManager[AsyncSession]],
            session_factory,
        ),
        runtime_effect_publisher=driver,
        register_due=driver.register_due,
        clock=clock or MutableClock(),
        terminate_grace_seconds=terminate_grace_seconds,
        kill_wait_seconds=0.5,
        shutdown_seconds=2,
    )


async def launch_pending_command(
    owner: CommandProcessOwner,
    session_factory: SessionFactory,
    run_id: str,
) -> None:
    async with session_factory() as session:
        await owner.launch_pending_command(
            cast(AsyncSession, session),
            CommandRunPending(run_id),
        )


async def open_argv_command(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
    argv: list[str],
    *,
    cwd: str | None = None,
    timeout_seconds: int | None = None,
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
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "summary": "Run one focused command-owner fixture.",
            }
        },
    )
    run_id = cast(str, response.model_dump()["command_id"])
    assert re.fullmatch(r"c_[0-9a-hjkmnp-tv-z]{8}", run_id)
    return run_id


async def wait_for_command_output(path: Path, expected: bytes) -> None:
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        try:
            if expected in await asyncio.to_thread(path.read_bytes):
                return
        except FileNotFoundError:
            pass
        await asyncio.sleep(0.02)
    pytest.fail(f"command output did not contain {expected!r} before the test deadline")
