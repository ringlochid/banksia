from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import pytest
from autoclaw.persistence.models import (
    CommandRunModel,
    DispatchTurnModel,
    FlowModel,
    FlowWaitModel,
    HumanRequestModel,
    TaskEventModel,
)
from autoclaw.runtime.contracts import (
    CommandRunStartRequest,
    HumanRequestOpenRequest,
    HumanRequestResolveRequest,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.human_request.service import resolve_human_request
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    HumanRequestTerminal,
    RuntimeEffectSignal,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import seeded_executor
from tests.helpers.lineage_seed import RuntimeIds


class _CommittedHumanTerminalPublisher:
    def __init__(
        self,
        *,
        database_path: Path,
        request_id: str,
        should_accept: bool,
        should_raise: bool,
    ) -> None:
        self._database_path = database_path
        self._request_id = request_id
        self._should_accept = should_accept
        self._should_raise = should_raise
        self.signals: list[RuntimeEffectSignal] = []

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        with sqlite3.connect(self._database_path) as connection:
            status = connection.execute(
                "SELECT status FROM human_requests WHERE request_id = ?",
                (self._request_id,),
            ).fetchone()
        assert status == ("resolved",)
        self.signals.append(signal)
        if self._should_raise:
            raise RuntimeError("human terminal publication unavailable")
        return self._should_accept


async def _open_direction_human_request(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose one bounded direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Which direction?",
                        "options": [
                            {"id": "a", "title": "A"},
                            {"id": "b", "title": "B"},
                        ],
                    }
                ],
            }
        },
    )
    return cast(str, opened.model_dump()["request_id"])


def test_external_wait_contracts_reject_legacy_request_fields() -> None:
    with pytest.raises(ValidationError):
        HumanRequestOpenRequest.model_validate(
            {
                "kind": "direction",
                "title": "Legacy title",
                "summary": "Choose one direction.",
                "items": [
                    {
                        "item_id": "direction",
                        "prompt": "Which direction?",
                        "options": [{"id": "a", "title": "A"}],
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        CommandRunStartRequest.model_validate(
            {"command": "echo legacy", "description": "Legacy shell coercion"}
        )
    with pytest.raises(ValidationError):
        HumanRequestOpenRequest.model_validate(
            {
                "kind": "input",
                "summary": "Ambiguous response contract.",
                "items": [
                    {
                        "id": "value",
                        "prompt": "Provide a value.",
                        "response_schema": {"type": "string"},
                        "options": [{"id": "a", "title": "A"}],
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        HumanRequestResolveRequest.model_validate(
            {"item_responses": [{"item_id": "legacy", "freeform_answer": "x"}]}
        )


async def test_human_request_open_persists_typed_source_and_exact_wait(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        result = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="open_human_request",
            arguments={
                "request": {
                    "kind": "direction",
                    "summary": "Choose one bounded direction.",
                    "items": [
                        {
                            "id": "direction",
                            "prompt": "Which direction?",
                            "options": [
                                {"id": "a", "title": "A"},
                                {"id": "b", "title": "B"},
                            ],
                        }
                    ],
                    "context_refs": [
                        {
                            "path": "workspace/brief.md",
                            "description": "Decision brief.",
                        }
                    ],
                    "suggested_human_instruction": "Select one option.",
                }
            },
        )
        request_id = result.model_dump()["request_id"]
        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            flow = await session.get(FlowModel, ids.flow_id)
        assert source is not None
        assert source.request_items_json[0]["id"] == "direction"
        assert source.context_refs_json == [
            {"path": "workspace/brief.md", "description": "Decision brief."}
        ]
        assert dispatch is not None and dispatch.status == "closed"
        assert dispatch.closed_reason == "human_request_wait"
        assert flow is not None and flow.current_dispatch_id is None
        assert flow.waiting_cause == "human_request"
        assert flow.waiting_source_id == request_id
        assert [signal.activity_revision for signal in signals] == [1]


async def test_human_request_answer_persists_typed_map_and_clears_exact_wait(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-answer") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        request_id = await _open_direction_human_request(executor, ids)
        async with session_factory() as session:
            response = await resolve_human_request(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                request_id=request_id,
                request=HumanRequestResolveRequest.model_validate(
                    {"item_responses": {"direction": "a"}}
                ),
                actor_ref="operator.test",
            )
        assert response.resolution.item_responses == {"direction": "a"}

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            flow = await session.get(FlowModel, ids.flow_id)
            wait = await session.get(FlowWaitModel, ids.flow_id)
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.task_id == ids.task_id,
                    TaskEventModel.event_type == "human_request_resolved",
                )
            )
        assert source is not None and source.item_responses_json == {"direction": "a"}
        assert flow is not None and flow.waiting_cause == "none"
        assert flow.waiting_source_id is None
        assert wait is None
        assert event is not None and event.dispatch_id == ids.current_dispatch_id


@pytest.mark.parametrize(
    ("should_accept", "should_raise"),
    ((False, False), (True, True)),
)
async def test_human_request_answer_is_independent_from_terminal_publication(
    tmp_path: Path,
    *,
    should_accept: bool,
    should_raise: bool,
) -> None:
    suffix = f"human-terminal-publish-{should_accept}-{should_raise}"
    async with seeded_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        request_id = await _open_direction_human_request(executor, ids)
        publisher = _CommittedHumanTerminalPublisher(
            database_path=tmp_path / f"{suffix}.sqlite",
            request_id=request_id,
            should_accept=should_accept,
            should_raise=should_raise,
        )
        async with session_factory() as session:
            response = await resolve_human_request(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                request_id=request_id,
                request=HumanRequestResolveRequest.model_validate(
                    {"item_responses": {"direction": "a"}}
                ),
                runtime_effect_publisher=publisher,
            )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)

    assert response.resolution.item_responses == {"direction": "a"}
    assert source is not None and source.status == "resolved"
    assert publisher.signals == [HumanRequestTerminal(request_id)]


async def test_human_request_answer_uses_exact_wait_when_pointer_is_stale_none(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-stale-none") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        request_id = await _open_direction_human_request(executor, ids)
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            control_revision = flow.control_revision
            flow.waiting_cause = "none"
            flow.waiting_source_id = None
            await session.commit()

        async with session_factory() as session:
            await resolve_human_request(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                request_id=request_id,
                request=HumanRequestResolveRequest.model_validate(
                    {"item_responses": {"direction": "a"}}
                ),
            )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            flow = await session.get(FlowModel, ids.flow_id)
            wait = await session.get(FlowWaitModel, ids.flow_id)
        assert source is not None and source.status == "resolved"
        assert wait is None
        assert flow is not None and flow.waiting_cause == "none"
        assert flow.waiting_source_id is None
        assert flow.control_revision == control_revision


async def test_human_request_answer_preserves_competing_wait_pointer(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-competing-pointer") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        request_id = await _open_direction_human_request(executor, ids)
        competing_source_id = "command-run.competing"
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            control_revision = flow.control_revision
            flow.waiting_cause = "command_run"
            flow.waiting_source_id = competing_source_id
            await session.commit()

        async with session_factory() as session:
            await resolve_human_request(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                request_id=request_id,
                request=HumanRequestResolveRequest.model_validate(
                    {"item_responses": {"direction": "a"}}
                ),
            )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            flow = await session.get(FlowModel, ids.flow_id)
            wait = await session.get(FlowWaitModel, ids.flow_id)
        assert source is not None and source.status == "resolved"
        assert wait is None
        assert flow is not None and flow.waiting_cause == "command_run"
        assert flow.waiting_source_id == competing_source_id
        assert flow.control_revision == control_revision


async def test_human_request_answer_rolls_back_when_exact_wait_is_missing(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-missing-wait") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        request_id = await _open_direction_human_request(executor, ids)
        async with session_factory() as session:
            wait = await session.get(FlowWaitModel, ids.flow_id)
            assert wait is not None
            await session.delete(wait)
            await session.commit()

        async with session_factory() as session:
            publisher = CapturedRuntimeEffectPublisher()
            with pytest.raises(RuntimeOperationError) as error:
                await resolve_human_request(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    request_id=request_id,
                    request=HumanRequestResolveRequest.model_validate(
                        {"item_responses": {"direction": "a"}}
                    ),
                    runtime_effect_publisher=publisher,
                )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            flow = await session.get(FlowModel, ids.flow_id)
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.task_id == ids.task_id,
                    TaskEventModel.event_type == "human_request_resolved",
                )
            )
        assert error.value.code == OperationFailureCode.CONFLICT
        assert source is not None and source.status == "open"
        assert flow is not None and flow.waiting_source_id == request_id
        assert event is None
        assert publisher.signals == ()


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
                    "cwd": "workspace/tools",
                    "environment": ["python.safe"],
                    "timeout_seconds": 30,
                    "summary": "Read the Python version.",
                    "expected_outputs": [
                        {
                            "path": "outputs/python-version.txt",
                            "description": "Captured version.",
                        }
                    ],
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
        assert source.cwd_policy_json == {"logical_path": "workspace/tools"}
        assert source.environment_refs_json == ["python.safe"]
        assert source.expected_outputs_json == [
            {
                "path": "outputs/python-version.txt",
                "description": "Captured version.",
            }
        ]
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
                        "cwd": "outputs",
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


@pytest.mark.parametrize(
    ("operation_name", "arguments"),
    (
        (
            "open_human_request",
            {
                "request": {
                    "kind": "direction",
                    "summary": "Choose one bounded direction.",
                    "items": [
                        {
                            "id": "direction",
                            "prompt": "Which direction?",
                            "options": [{"id": "a", "title": "A"}],
                        }
                    ],
                }
            },
        ),
        (
            "start_command_run",
            {
                "request": {
                    "command": {"kind": "argv", "argv": ["python", "-V"]},
                    "summary": "Read the Python version.",
                }
            },
        ),
    ),
)
async def test_terminal_checkpoint_rejects_external_wait_after_admission(
    tmp_path: Path,
    operation_name: str,
    arguments: dict[str, object],
) -> None:
    async with seeded_executor(tmp_path, suffix=f"terminal-{operation_name}") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        await executor.execute(
            scope=scope,
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "terminal",
                    "outcome": "blocked",
                    "handoff": {
                        "summary": "The current assignment is blocked.",
                        "next_step": "Return the matching boundary.",
                    },
                }
            },
        )

        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=scope,
                operation_name=operation_name,
                arguments=arguments,
            )

        async with session_factory() as session:
            human_request = await session.scalar(
                select(HumanRequestModel).where(HumanRequestModel.task_id == ids.task_id)
            )
            command_run = await session.scalar(
                select(CommandRunModel).where(CommandRunModel.task_id == ids.task_id)
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert error.value.code == OperationFailureCode.ILLEGAL_STATE
        assert error.value.is_retryable is False
        assert human_request is None
        assert command_run is None
        assert dispatch is not None and dispatch.status == "open"
        assert dispatch.node_activity_revision == 2
        assert [signal.activity_revision for signal in signals] == [1, 2]
