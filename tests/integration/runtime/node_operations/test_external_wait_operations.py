from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    DispatchTurnModel,
    HumanRequestFileReferenceModel,
    HumanRequestModel,
    TaskEventModel,
    TaskModel,
)
from banksia.runtime.contracts import (
    CommandRunStartRequest,
    HumanRequestOpenRequest,
    HumanRequestResolveRequest,
)
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.human_request.service import resolve_human_request
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    HumanRequestTerminal,
    RuntimeEffectSignal,
)
from tests.helpers.executor_harness import seeded_executor
from tests.helpers.lineage_seed import RuntimeIds

_DIRECTION_A_ANSWER = {
    "direction": {
        "kind": "option",
        "option_id": "a",
    }
}


def _human_request_payload(
    *,
    summary: str = "Choose one direction.",
    prompt: str = "Which direction?",
    option_title: str = "A",
    option_description: str | None = None,
) -> dict[str, object]:
    first_option: dict[str, object] = {"id": "a", "title": option_title}
    if option_description is not None:
        first_option["description"] = option_description
    return {
        "kind": "direction",
        "summary": summary,
        "items": [
            {
                "id": "direction",
                "prompt": prompt,
                "options": [
                    first_option,
                    {"id": "b", "title": "B"},
                ],
            }
        ],
    }


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
    with pytest.raises(ValidationError):
        HumanRequestResolveRequest.model_validate({"item_responses": {"direction": "a"}})


def test_human_request_contract_enforces_exact_text_and_structured_value_bounds() -> None:
    accepted = HumanRequestOpenRequest.model_validate(
        _human_request_payload(
            summary=f"  {'s' * 2_045}\r\n",
            prompt=f"  {'p' * 4_093}\r\n",
            option_title=f"  {'a' * 251}  ",
            option_description=f"  {'d' * 1_020}  ",
        )
    )
    assert accepted.summary.startswith("  ") and accepted.summary.endswith("\n")
    assert accepted.items[0].prompt.startswith("  ") and accepted.items[0].prompt.endswith("\n")
    assert accepted.items[0].options is not None
    assert accepted.items[0].options[0].title.startswith("  ")
    assert accepted.items[0].options[0].description is not None
    assert accepted.items[0].options[0].description.endswith("  ")

    oversized_cases = (
        _human_request_payload(summary="s" * 2_049),
        _human_request_payload(prompt="p" * 4_097),
        _human_request_payload(option_title="a" * 256),
        _human_request_payload(option_description="d" * 1_025),
    )
    for payload in oversized_cases:
        with pytest.raises(ValidationError, match="controller text limit"):
            HumanRequestOpenRequest.model_validate(payload)

    deeply_nested: object = "answer"
    for _ in range(16):
        deeply_nested = [deeply_nested]
    submitted_response_cases = (
        {"direction": {"kind": "value", "value": "x" * (64 * 1_024)}},
        {"direction": {"kind": "value", "value": deeply_nested}},
        {
            "direction": {
                "kind": "value",
                "value": [[] for _ in range(1_024)],
            }
        },
    )
    for item_responses in submitted_response_cases:
        with pytest.raises(
            ValidationError,
            match=r"controller (byte|depth|collection) limit",
        ):
            HumanRequestResolveRequest.model_validate({"item_responses": item_responses})


async def test_human_request_open_persists_typed_source_and_exact_wait(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        workspace = tmp_path / "task-human" / "workspace"
        (workspace / "brief.md").write_text("Decision brief.", encoding="utf-8")
        async with session_factory() as session:
            initial_task = await session.get(TaskModel, ids.task_id)
        assert initial_task is not None
        initial_control_revision = initial_task.control_revision
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
                    "files": [
                        {
                            "path": "brief.md",
                            "description": "Decision brief.",
                        }
                    ],
                }
            },
        )
        request_id = result.model_dump()["request_id"]
        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            file_references = tuple(
                await session.scalars(
                    select(HumanRequestFileReferenceModel)
                    .where(HumanRequestFileReferenceModel.request_id == request_id)
                    .order_by(HumanRequestFileReferenceModel.order_index)
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.human_request_id == request_id)
            )
            task = await session.get(TaskModel, ids.task_id)
        assert source is not None
        assert source.request_items_json[0]["id"] == "direction"
        assert [(row.path, row.description) for row in file_references] == [
            ("brief.md", "Decision brief.")
        ]
        assert dispatch is not None and dispatch.status == "closed"
        assert dispatch.closed_reason == "human_request_wait"
        assert attempt is not None and wait is not None
        assert attempt.current_dispatch_id is None
        assert attempt.current_wait_id == wait.wait_id
        assert wait.source_dispatch_id == ids.current_dispatch_id
        assert task is not None and task.control_revision == initial_control_revision
        assert [signal.activity_revision for signal in signals] == [1]


async def test_human_request_rejects_invalid_file_without_opening_wait(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-invalid-file") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        with pytest.raises(RuntimeOperationError, match="referenced file does not exist"):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="open_human_request",
                arguments={
                    "request": {
                        "kind": "direction",
                        "summary": "This request must roll back.",
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
                        "files": [{"path": "missing.md"}],
                    }
                },
            )

        async with session_factory() as session:
            source = await session.scalar(
                select(HumanRequestModel).where(HumanRequestModel.task_id == ids.task_id)
            )
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.task_id == ids.task_id)
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)

        assert source is None
        assert wait is None
        assert dispatch is not None and dispatch.status == "open"
        assert attempt is not None
        assert attempt.current_dispatch_id == ids.current_dispatch_id
        assert attempt.current_wait_id is None


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
            initial_task = await session.get(TaskModel, ids.task_id)
        assert initial_task is not None
        initial_control_revision = initial_task.control_revision
        async with session_factory() as session:
            response = await resolve_human_request(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                request_id=request_id,
                request=HumanRequestResolveRequest.model_validate(
                    {"item_responses": _DIRECTION_A_ANSWER}
                ),
                actor_ref="operator.test",
            )
        assert response.resolution.model_dump(mode="json")["item_responses"] == (
            _DIRECTION_A_ANSWER
        )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            task = await session.get(TaskModel, ids.task_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.human_request_id == request_id)
            )
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.task_id == ids.task_id,
                    TaskEventModel.event_type == "human_request_resolved",
                )
            )
        assert source is not None and source.item_responses_json == _DIRECTION_A_ANSWER
        assert attempt is not None
        assert attempt.current_dispatch_id is None
        assert attempt.current_wait_id is None
        assert task is not None and task.control_revision == initial_control_revision
        assert wait is None
        assert event is not None and event.dispatch_id == ids.current_dispatch_id


async def test_human_request_answer_tags_are_checked_against_original_items(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-answer-tags") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        opened = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="open_human_request",
            arguments=_tagged_human_request_arguments(),
        )
        request_id = cast(str, opened.model_dump()["request_id"])
        rejected_answers = (
            {
                "direction": {"kind": "option", "option_id": "unknown"},
                "detail": {"kind": "other", "text": "Use the product wording."},
                "optional": {"kind": "skipped"},
            },
            {
                "direction": {"kind": "other", "text": "Not allowed here."},
                "detail": {"kind": "other", "text": "Use the product wording."},
                "optional": {"kind": "skipped"},
            },
            {
                "direction": {"kind": "option", "option_id": "a"},
                "detail": {"kind": "other", "text": "Use the product wording."},
                "optional": {"kind": "value", "value": 42},
            },
        )
        for item_responses in rejected_answers:
            async with session_factory() as session:
                with pytest.raises(RuntimeOperationError):
                    await resolve_human_request(
                        cast(AsyncSession, session),
                        task_id=ids.task_id,
                        request_id=request_id,
                        request=HumanRequestResolveRequest.model_validate(
                            {"item_responses": item_responses}
                        ),
                    )

        accepted_answers = {
            "direction": {"kind": "option", "option_id": "a"},
            "detail": {"kind": "other", "text": "  Use the product wording.  "},
            "optional": {"kind": "skipped"},
        }
        async with session_factory() as session:
            response = await resolve_human_request(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                request_id=request_id,
                request=HumanRequestResolveRequest.model_validate(
                    {"item_responses": accepted_answers}
                ),
            )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)

    assert response.resolution.model_dump(mode="json")["item_responses"] == accepted_answers
    assert source is not None and source.item_responses_json == accepted_answers


def _tagged_human_request_arguments() -> dict[str, object]:
    return {
        "request": {
            "kind": "direction",
            "summary": "Choose the bounded responses.",
            "items": [
                {
                    "id": "direction",
                    "prompt": "Which direction?",
                    "options": [
                        {"id": "a", "title": "A"},
                        {"id": "b", "title": "B"},
                    ],
                },
                {
                    "id": "detail",
                    "prompt": "Choose or explain another detail.",
                    "options": [
                        {"id": "brief", "title": "Brief"},
                        {"id": "full", "title": "Full"},
                    ],
                    "allow_other": True,
                },
                {
                    "id": "optional",
                    "prompt": "Optionally provide context.",
                    "response_schema": {"type": "string"},
                    "allow_skip": True,
                },
            ],
        }
    }


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
                    {"item_responses": _DIRECTION_A_ANSWER}
                ),
                runtime_effect_publisher=publisher,
            )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)

    assert response.resolution.model_dump(mode="json")["item_responses"] == (_DIRECTION_A_ANSWER)
    assert source is not None and source.status == "resolved"
    assert publisher.signals == [HumanRequestTerminal(request_id)]
