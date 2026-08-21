from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from oh_my_subagents.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    DispatchTurnModel,
    TaskModel,
)
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.node_operations import NodeOperationScope
from tests.helpers.executor_harness import seeded_executor


async def test_command_run_start_persists_discriminated_request_without_launching(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="command") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            initial_task = await session.get(TaskModel, ids.task_id)
        assert initial_task is not None
        initial_control_revision = initial_task.control_revision
        result = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="start_command_run",
            arguments={
                "request": {
                    "command": {"kind": "argv", "argv": ["python", "-V"]},
                    "cwd": "tools",
                    "timeout_seconds": 30,
                    "summary": "Read the Python version.",
                }
            },
        )
        response = result.model_dump(mode="json")
        run_id = response["command_id"]
        assert response == {
            "command_id": run_id,
            "status": "pending_start",
            "output_path": response["output_path"],
            "must_stop": True,
        }
        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
            )
            task = await session.get(TaskModel, ids.task_id)
        assert source is not None and source.state == "pending_start"
        assert source.command_spec_json == {"kind": "argv", "argv": ["python", "-V"]}
        assert source.cwd == "tools"
        assert dispatch is not None and dispatch.status == "closed"
        assert attempt is not None and wait is not None
        assert attempt.current_dispatch_id is None
        assert attempt.current_wait_id == wait.wait_id
        assert wait.source_dispatch_id == ids.current_dispatch_id
        assert task is not None and task.control_revision == initial_control_revision


async def test_invalid_command_cwd_creates_no_source_or_wait(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="command-path") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="start_command_run",
                arguments={
                    "request": {
                        "command": {"kind": "shell", "command": "pwd"},
                        "cwd": "../outputs",
                        "summary": "Reject non-workspace cwd.",
                    }
                },
            )
        async with session_factory() as session:
            source = await session.scalar(
                select(CommandRunModel).where(CommandRunModel.task_id == ids.task_id)
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
        assert source is None
        assert dispatch is not None and dispatch.status == "open"
        assert attempt is not None
        assert attempt.current_dispatch_id == ids.current_dispatch_id
        assert attempt.current_wait_id is None
