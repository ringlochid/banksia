from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from autoclaw.config import CodexSettings, RuntimeSettings, Settings
from autoclaw.definitions.contracts.registry import PolicyDefinitionInput
from autoclaw.definitions.contracts.workflow import NodeKind, ProviderKind
from autoclaw.persistence.models import (
    CommandRunModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
    FlowWaitModel,
    PolicyRevisionModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.command_run.continuation import open_command_run_successor
from autoclaw.runtime.command_run.service import read_command_run
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.flow.service import pause_runtime_flow, runtime_flow_read
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    CommandRunTerminal,
    DispatchStartDue,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
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
        await _enable_target_policy(session_factory)
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
    trigger = _read_trigger(tmp_path / "task-command-continuation" / refs.input_logical_path)
    _assert_command_trigger(
        trigger,
        run_id=run_id,
        source_dispatch_id=ids.current_dispatch_id,
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
) -> None:
    result_payload = cast(dict[str, object], trigger["result"])
    assert trigger["kind"] == "command_result"
    assert trigger["run_id"] == run_id
    assert trigger["source_dispatch_id"] == source_dispatch_id
    assert trigger["request"] == {
        "command": {"kind": "argv", "argv": ["python", "-V"]},
        "cwd": None,
        "environment": [],
        "timeout_seconds": None,
        "summary": "Read the Python version.",
        "expected_outputs": [
            {
                "path": "outputs/python-version.txt",
                "description": "Captured Python version.",
            }
        ],
    }
    assert result_payload["state"] == "succeeded"
    assert result_payload["exit_code"] == 0
    assert result_payload["summary"] == "Python reported its version successfully."
    assert result_payload["started_at"] == result_payload["ended_at"]
    assert result_payload["stdout_log_ref"] == "tmp/transfers/localized/python-version.log"
    assert result_payload["terminal_event_source"] == "process_owner"
    assert trigger["refs"] == [
        {
            "kind": "transient",
            "logical_path": "tmp/transfers/localized/python-version.log",
            "purpose": "Read the bounded command log when the summary is insufficient.",
            "description": "Command standard-output log.",
            "slot": None,
            "version": None,
        },
        {
            "kind": "workspace",
            "logical_path": "outputs/python-version.txt",
            "purpose": "Inspect this expected command output before continuing.",
            "description": "Captured Python version.",
            "slot": None,
            "version": None,
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
                "expected_outputs": [
                    {
                        "path": "outputs/python-version.txt",
                        "description": "Captured Python version.",
                    }
                ],
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
        source.stdout_logical_path = "tmp/transfers/localized/python-version.log"
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


async def _enable_target_policy(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
        assert policy is not None
        policy.content_json = PolicyDefinitionInput(
            id="policy.target",
            description="Allow exact-source continuation in the integration fixture.",
            applies_to=[NodeKind.ROOT, NodeKind.WORKER],
        ).model_dump(mode="json")
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
