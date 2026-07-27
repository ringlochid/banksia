from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.command_process import (
    MutableClock,
    OwnerSignalDriver,
    command_process_owner,
    launch_pending_command,
    open_argv_command,
    wait_for_command_output,
)
from tests.helpers.executor_harness import seeded_executor, seeded_task_root

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process-group proof")


async def test_command_timeout_terminates_owned_grandchild(tmp_path: Path) -> None:
    grandchild_pid: int | None = None
    clock = MutableClock()
    try:
        async with seeded_executor(tmp_path, suffix="command-family-timeout") as (
            executor,
            session_factory,
            ids,
            _,
        ):
            run_id = await open_argv_command(
                executor,
                ids,
                [sys.executable, "-c", _process_family_script()],
                timeout_seconds=1,
            )
            driver = OwnerSignalDriver(session_factory)
            owner = command_process_owner(
                session_factory,
                driver,
                clock=clock,
                terminate_grace_seconds=0.05,
            )
            driver.owner = owner
            async with owner:
                await launch_pending_command(owner, session_factory, run_id)
                output_path = _command_output_path(
                    tmp_path,
                    suffix="command-family-timeout",
                    run_id=run_id,
                )
                await wait_for_command_output(output_path, b"grandchild=")
                grandchild_pid = _read_grandchild_pid(output_path)
                await asyncio.wait_for(driver.deadline_registered.wait(), timeout=2)
                due = driver.deadlines[0]
                clock.now = due.due_at
                async with session_factory() as session:
                    await owner.enforce_command_deadline(
                        cast(AsyncSession, session),
                        due,
                    )
                await driver.wait_for_terminal()

            assert grandchild_pid is not None
            await _assert_process_exited(grandchild_pid)
    finally:
        _kill_surviving_process(grandchild_pid)


async def test_command_owner_shutdown_terminates_owned_grandchild(tmp_path: Path) -> None:
    grandchild_pid: int | None = None
    try:
        async with seeded_executor(tmp_path, suffix="command-family-shutdown") as (
            executor,
            session_factory,
            ids,
            _,
        ):
            run_id = await open_argv_command(
                executor,
                ids,
                [sys.executable, "-c", _process_family_script()],
            )
            driver = OwnerSignalDriver(session_factory)
            owner = command_process_owner(
                session_factory,
                driver,
                terminate_grace_seconds=0.05,
            )
            driver.owner = owner
            async with owner:
                await launch_pending_command(owner, session_factory, run_id)
                output_path = _command_output_path(
                    tmp_path,
                    suffix="command-family-shutdown",
                    run_id=run_id,
                )
                await wait_for_command_output(output_path, b"grandchild=")
                grandchild_pid = _read_grandchild_pid(output_path)

            assert grandchild_pid is not None
            await _assert_process_exited(grandchild_pid)
    finally:
        _kill_surviving_process(grandchild_pid)


def _process_family_script() -> str:
    grandchild_script = (
        "import signal, time; signal.signal(signal.SIGTERM, lambda *_: None); time.sleep(60)"
    )
    return (
        "import os, subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', {grandchild_script!r}]); "
        "print(f'leader={os.getpid()} grandchild={child.pid}', flush=True); "
        "time.sleep(60)"
    )


def _command_output_path(tmp_path: Path, *, suffix: str, run_id: str) -> Path:
    return seeded_task_root(tmp_path, suffix) / "command-runs" / run_id / "output.log"


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


def _kill_surviving_process(pid: int | None) -> None:
    if pid is not None and _process_exists(pid):
        os.kill(pid, signal.SIGKILL)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
