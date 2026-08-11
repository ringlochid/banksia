from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import banksia.runtime.command_run.process_owner as process_owner_module
import banksia.runtime.command_run.process_resources as process_resources_module
from banksia.persistence.models import CommandRunModel
from banksia.runtime.command_run import read_command_run_log
from banksia.runtime.command_run.owned_process import ManagedCommandProcess
from banksia.runtime.command_run.task_paths import StableCommandWorkingDirectory
from banksia.runtime.command_run.transitions import CommandRunLaunchClaim
from tests.helpers.command_process import (
    OwnerSignalDriver,
    command_process_owner,
    launch_pending_command,
    open_argv_command,
)
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
    seeded_task_root,
    seeded_task_workspace,
)
from tests.helpers.lineage_seed import RuntimeIds


@pytest.mark.skipif(os.name != "posix", reason="POSIX retained-cwd substitution proof")
async def test_process_owner_launches_in_admitted_directory_after_path_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = "command-process-cwd-substitution"
    workspace = seeded_task_workspace(tmp_path, suffix)
    admitted = workspace / "admitted"
    admitted.mkdir(parents=True)
    (admitted / "identity.txt").write_text("admitted", encoding="utf-8")
    outside = tmp_path / "outside-command-cwd"
    outside.mkdir()
    (outside / "identity.txt").write_text("outside", encoding="utf-8")

    original_spawn = process_owner_module.spawn_command_process
    original_close = process_owner_module.close_command_working_directory
    closed_descriptors: list[int] = []

    async def substitute_before_spawn(
        claim: CommandRunLaunchClaim,
        *,
        working_directory: StableCommandWorkingDirectory,
        environment: dict[str, str],
    ) -> ManagedCommandProcess:
        moved = workspace / "admitted-after-check"
        admitted.rename(moved)
        admitted.symlink_to(outside, target_is_directory=True)
        return await original_spawn(
            claim,
            working_directory=working_directory,
            environment=environment,
        )

    def record_close(working_directory: StableCommandWorkingDirectory) -> None:
        closed_descriptors.append(working_directory.descriptor)
        original_close(working_directory)

    monkeypatch.setattr(
        process_owner_module,
        "spawn_command_process",
        substitute_before_spawn,
    )
    monkeypatch.setattr(
        process_owner_module,
        "close_command_working_directory",
        record_close,
    )
    script = "from pathlib import Path; print(Path('identity.txt').read_text())"
    async with seeded_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await open_argv_command(
            executor,
            ids,
            [sys.executable, "-c", script],
            cwd="admitted",
        )
        driver = OwnerSignalDriver(session_factory)
        owner = command_process_owner(session_factory, driver)
        driver.owner = owner
        async with owner:
            await launch_pending_command(owner, session_factory, run_id)
            await driver.wait_for_terminal()

        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            output = await read_command_run_log(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                run_id=run_id,
            )

    assert source is not None
    assert source.state == "succeeded"
    assert output.content == "admitted\n"
    assert len(closed_descriptors) == 1


async def test_large_output_is_fully_written_while_reads_remain_bounded(
    tmp_path: Path,
) -> None:
    output_size = 1_200_000
    script = f"import sys; sys.stdout.buffer.write(b'x' * {output_size})"
    async with seeded_executor(tmp_path, suffix="command-process-large-output") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await open_argv_command(executor, ids, [sys.executable, "-c", script])
        driver = OwnerSignalDriver(session_factory)
        owner = command_process_owner(session_factory, driver)
        driver.owner = owner
        async with owner:
            await launch_pending_command(owner, session_factory, run_id)
            await driver.wait_for_terminal()

        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            first = await read_command_run_log(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                run_id=run_id,
                byte_limit=4_096,
            )
            second = await read_command_run_log(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                run_id=run_id,
                offset=4_096,
                byte_limit=4_096,
            )

        assert source is not None
        assert source.output_observed_bytes == output_size
        assert source.output_written_bytes == output_size
        assert source.output_complete is True
        output_path = (
            seeded_task_root(tmp_path, "command-process-large-output")
            / "command-runs"
            / run_id
            / "output.log"
        )
        assert output_path.stat().st_size == output_size
        assert first.content == "x" * 4_096
        assert first.bytes_read == 4_096
        assert first.next_offset == 4_096
        assert first.file_size == output_size
        assert second.offset == 4_096
        assert second.next_offset == 8_192

        await _assert_changed_unsafe_and_missing_output(
            tmp_path,
            output_path,
            session_factory,
            ids,
            run_id,
        )


async def _assert_changed_unsafe_and_missing_output(
    tmp_path: Path,
    output_path: Path,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    run_id: str,
) -> None:
    await asyncio.to_thread(_append_output, output_path, b"changed")
    async with session_factory() as session:
        changed = await read_command_run_log(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            run_id=run_id,
            byte_limit=1,
        )
    assert changed.is_changed is True
    assert changed.is_missing is False

    await asyncio.to_thread(output_path.unlink)
    outside = tmp_path / "outside-command-output.log"
    await asyncio.to_thread(outside.write_text, "must not be read", encoding="utf-8")
    await asyncio.to_thread(output_path.symlink_to, outside)
    async with session_factory() as session:
        unsafe = await read_command_run_log(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            run_id=run_id,
            byte_limit=1,
        )
    assert unsafe.is_missing is False
    assert unsafe.is_changed is True
    assert unsafe.content == ""

    await asyncio.to_thread(output_path.unlink)
    async with session_factory() as session:
        missing = await read_command_run_log(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            run_id=run_id,
            byte_limit=1,
        )
    assert missing.is_missing is True
    assert missing.content == ""


def _append_output(output_path: Path, payload: bytes) -> None:
    with output_path.open("ab") as output:
        output.write(payload)


async def test_output_write_failure_still_drains_to_eof_and_records_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_size = 300_000

    def fail_output_write(
        descriptor: int,
        payload: bytes,
    ) -> process_resources_module.CommandOutputWrite:
        del descriptor, payload
        raise OSError("injected output write failure")

    monkeypatch.setattr(
        process_resources_module,
        "write_command_output_chunk",
        fail_output_write,
    )
    script = f"import sys; sys.stderr.buffer.write(b'e' * {output_size})"
    async with seeded_executor(tmp_path, suffix="command-process-write-failure") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await open_argv_command(executor, ids, [sys.executable, "-c", script])
        driver = OwnerSignalDriver(session_factory)
        owner = command_process_owner(session_factory, driver)
        driver.owner = owner
        async with owner:
            await launch_pending_command(owner, session_factory, run_id)
            await driver.wait_for_terminal()

        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            current = await read_command_run_log(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                run_id=run_id,
            )

        assert source is not None
        assert source.state == "succeeded"
        assert source.output_observed_bytes == output_size
        assert source.output_written_bytes == 0
        assert source.output_complete is False
        assert current.output_complete is False
        assert current.content == ""
        assert current.is_changed is False
