from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    CommandRunModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
    FlowWaitModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.command_run.continuation import open_command_run_successor
from banksia.runtime.command_run.service import read_command_run
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.flow.service import pause_runtime_flow, runtime_flow_read
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    CommandRunTerminal,
    DispatchStartDue,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
    seeded_task_root,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_terminal_command_source_opens_one_same_attempt_successor(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="command-continuation") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_command_run(executor, ids)
        await _terminalize_command_run(session_factory, ids, run_id)
        publisher = CapturedRuntimeEffectPublisher()

        async with session_factory() as session:
            pre_open = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            first = await open_command_run_successor(
                cast(AsyncSession, session),
                signal=CommandRunTerminal(run_id),
                dependencies=_opening_dependencies(publisher),
            )
            duplicate = await open_command_run_successor(
                cast(AsyncSession, session),
                signal=CommandRunTerminal(run_id),
                dependencies=_opening_dependencies(publisher),
            )
            source = await session.get(CommandRunModel, run_id)
            detail = await read_command_run(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                run_id=run_id,
            )
            flow = await session.get(FlowModel, ids.flow_id)
            successor = await session.get(DispatchTurnModel, first.dispatch_id)
            refs = await session.get(DispatchPromptRefsModel, first.dispatch_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert first.outcome == "opened"
    assert pre_open.current_command_run is not None
    assert pre_open.current_command_run.run_id == run_id
    assert pre_open.current_command_run.state.value == "succeeded"
    assert pre_open.current_dispatch is None
    assert duplicate.outcome == "skipped"
    assert first.dispatch_id is not None
    assert source is not None and source.successor_dispatch_id == first.dispatch_id
    assert detail.successor_dispatch_id == first.dispatch_id
    assert flow is not None and flow.current_dispatch_id == first.dispatch_id
    assert successor is not None and successor.opened_reason == "command_result"
    assert successor.assignment_id == ids.root_assignment_id
    assert successor.attempt_id == ids.root_attempt_id
    assert dispatch_count == 4
    assert refs is not None
    trigger = _read_trigger(
        seeded_task_root(tmp_path, "command-continuation") / refs.input_logical_path
    )
    _assert_command_trigger(
        trigger,
        run_id=run_id,
        source_dispatch_id=ids.current_dispatch_id,
        output_path=f".banksia/{ids.task_id}/command-runs/{run_id}/output.log",
    )
    assert len(publisher.signals) == 1
    signal = publisher.signals[0]
    assert isinstance(signal, DispatchStartDue)
    assert signal.dispatch_id == first.dispatch_id


def _assert_command_trigger(
    trigger: dict[str, object],
    *,
    run_id: str,
    source_dispatch_id: str,
    output_path: str,
) -> None:
    result_payload = cast(dict[str, object], trigger["result"])
    assert trigger["kind"] == "command_result"
    assert trigger["run_id"] == run_id
    assert trigger["source_dispatch_id"] == source_dispatch_id
    assert trigger["request"] == {
        "command": {"kind": "argv", "argv": ["python", "-V"]},
        "cwd": None,
        "timeout_seconds": None,
        "summary": "Read the Python version.",
    }
    assert result_payload["state"] == "succeeded"
    assert result_payload["exit_code"] == 0
    assert result_payload["summary"] == "Python reported its version successfully."
    assert result_payload["started_at"] == result_payload["ended_at"]
    assert result_payload["output_path"] == output_path
    assert result_payload["output_observed_bytes"] == 21
    assert result_payload["output_written_bytes"] == 21
    assert result_payload["output_complete"] is True
    assert result_payload["output_encoding"] == "raw_bytes"
    assert result_payload["terminal_event_source"] == "process_owner"
    assert trigger["files"] == [
        {
            "path": output_path,
            "description": "Current combined command output.",
        },
    ]


async def test_nonterminal_command_signal_is_a_harmless_noop(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="command-nonterminal") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_command_run(executor, ids)
        publisher = CapturedRuntimeEffectPublisher()
        async with session_factory() as session:
            result = await open_command_run_successor(
                cast(AsyncSession, session),
                signal=CommandRunTerminal(run_id),
                dependencies=_opening_dependencies(publisher),
            )
            source = await session.get(CommandRunModel, run_id)
            flow = await session.get(FlowModel, ids.flow_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert result.outcome == "skipped"
    assert source is not None and source.state == "pending_start"
    assert source.successor_dispatch_id is None
    assert flow is not None and flow.waiting_source_id == run_id
    assert dispatch_count == 3
    assert publisher.signals == ()


async def test_terminal_command_source_remains_current_while_flow_is_paused(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="command-paused-readback") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_command_run(executor, ids)
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            await pause_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
            )
        await _terminalize_command_run(session_factory, ids, run_id)

        async with session_factory() as session:
            readback = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)

    assert readback.status.value == "paused"
    assert readback.current_dispatch is None
    assert readback.current_command_run is not None
    assert readback.current_command_run.run_id == run_id
    assert readback.current_command_run.state.value == "succeeded"


async def _open_command_run(executor: NodeOperationExecutor, ids: RuntimeIds) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id),
        operation_name="start_command_run",
        arguments={
            "request": {
                "command": {"kind": "argv", "argv": ["python", "-V"]},
                "summary": "Read the Python version.",
            }
        },
    )
    return cast(str, opened.model_dump()["run_id"])


async def _terminalize_command_run(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    run_id: str,
) -> None:
    now = utc_now()
    async with session_factory() as session:
        source = await session.get(CommandRunModel, run_id)
        flow = await session.get(FlowModel, ids.flow_id)
        assert source is not None
        assert flow is not None
        source.state = "succeeded"
        source.started_at = now
        source.ended_at = now
        source.terminal_summary = "Python reported its version successfully."
        source.terminal_exit_code = 0
        source.terminal_event_source = "process_owner"
        source.output_observed_bytes = 21
        source.output_written_bytes = 21
        source.output_complete = True
        await session.execute(
            delete(FlowWaitModel).where(
                FlowWaitModel.flow_id == ids.flow_id,
                FlowWaitModel.command_run_id == run_id,
            )
        )
        flow.waiting_cause = "none"
        flow.waiting_source_id = None
        flow.control_revision += 1
        await session.commit()


def _opening_dependencies(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
    )


def _read_trigger(path: Path) -> dict[str, object]:
    input_text = path.read_text(encoding="utf-8")
    payload = input_text.split("# Trigger\n\n```json\n", maxsplit=1)[1].split("\n```", maxsplit=1)[
        0
    ]
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


__all__ = []
