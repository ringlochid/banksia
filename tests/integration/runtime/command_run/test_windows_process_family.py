from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import CommandRunModel
from banksia.runtime.command_run import cancel_command_run
from tests.helpers.command_process import (
    OwnerSignalDriver,
    command_process_owner,
    launch_pending_command,
    open_argv_command,
    wait_for_command_output,
)
from tests.helpers.executor_harness import seeded_executor, seeded_task_root

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object proof")

_WIDE_WINDOWS_EXIT_CODE = 0xC000013A


async def test_command_run_preserves_unsigned_windows_exit_code(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="windows-command-exit") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        script = f"import ctypes; ctypes.windll.kernel32.ExitProcess({_WIDE_WINDOWS_EXIT_CODE})"
        run_id = await open_argv_command(executor, ids, [sys.executable, "-c", script])
        driver = OwnerSignalDriver(session_factory)
        owner = command_process_owner(session_factory, driver)
        driver.owner = owner
        async with owner:
            await launch_pending_command(owner, session_factory, run_id)
            await driver.wait_for_terminal()

        async with session_factory() as session:
            command = await session.get(CommandRunModel, run_id)
        assert command is not None
        assert command.state == "failed"
        assert command.terminal_exit_code == _WIDE_WINDOWS_EXIT_CODE


async def test_command_cancel_terminates_windows_job_descendant(tmp_path: Path) -> None:
    grandchild_pid: int | None = None
    try:
        async with seeded_executor(tmp_path, suffix="windows-command-family") as (
            executor,
            session_factory,
            ids,
            _,
        ):
            script = (
                "import os, subprocess, sys, time; "
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                "print(f'leader={os.getpid()} grandchild={child.pid}', flush=True); "
                "time.sleep(60)"
            )
            run_id = await open_argv_command(
                executor,
                ids,
                [sys.executable, "-c", script],
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
                output_path = (
                    seeded_task_root(tmp_path, "windows-command-family")
                    / "command-runs"
                    / run_id
                    / "output.log"
                )
                await wait_for_command_output(output_path, b"grandchild=")
                grandchild_pid = _read_grandchild_pid(output_path)
                async with session_factory() as session:
                    await cancel_command_run(
                        cast(AsyncSession, session),
                        task_id=ids.task_id,
                        run_id=run_id,
                        actor_ref="windows-test",
                        runtime_effect_publisher=driver,
                    )
                await driver.wait_for_terminal()

            assert grandchild_pid is not None
            assert not _windows_process_is_active(grandchild_pid)
    finally:
        if grandchild_pid is not None and _windows_process_is_active(grandchild_pid):
            cleanup = await asyncio.create_subprocess_exec(
                "taskkill.exe",
                "/PID",
                str(grandchild_pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await cleanup.wait()


def _read_grandchild_pid(output_path: Path) -> int:
    fields = dict(
        field.split("=", 1)
        for field in output_path.read_text(encoding="utf-8").strip().splitlines()[0].split()
    )
    return int(fields["grandchild"])


def _windows_process_is_active(pid: int) -> bool:
    import win32api
    import win32con
    import win32process

    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except OSError:
        return False
    try:
        return int(win32process.GetExitCodeProcess(handle)) == 259
    finally:
        import win32api

        win32api.CloseHandle(int(handle))
