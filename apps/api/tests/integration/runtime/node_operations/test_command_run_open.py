from __future__ import annotations

from pathlib import Path

import pytest
from banksia.persistence.models import CommandRunModel, DispatchTurnModel, FlowModel
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from sqlalchemy import select
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
        run_id = result.model_dump()["run_id"]
        async with session_factory() as session:
            source = await session.get(CommandRunModel, run_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            flow = await session.get(FlowModel, ids.flow_id)
        assert source is not None and source.state == "pending_start"
        assert source.command_spec_json == {"kind": "argv", "argv": ["python", "-V"]}
        assert source.cwd_policy_json == {"logical_path": "tools"}
        assert dispatch is not None and dispatch.status == "closed"
        assert flow is not None and flow.waiting_source_id == run_id
        assert flow.waiting_cause == "command_run"


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
            flow = await session.get(FlowModel, ids.flow_id)
        assert source is None
        assert dispatch is not None and dispatch.status == "open"
        assert flow is not None and flow.current_dispatch_id == ids.current_dispatch_id
        assert flow.waiting_cause == "none"
