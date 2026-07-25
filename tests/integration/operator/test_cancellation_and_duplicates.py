from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import banksia.operator.duplicate_wait as duplicate_wait_module
from banksia.operator import (
    OperatorConversationService,
    OperatorProviderAskUserResult,
    OperatorProviderMessageResult,
    OperatorTurnInProgressError,
    OperatorTurnOutcome,
)
from banksia.operator.contracts import (
    OperatorAssistantQuestionSetEntry,
    OperatorMessageRequest,
    OperatorQuestionAnswersRequest,
)
from banksia.operator.conversation_reads import OperatorSessionFactory
from banksia.persistence import (
    OperatorConversationEntryModel,
    OperatorConversationModel,
)
from tests.helpers.operator import (
    BlockingTurnRunner,
    RecordingTurnRunner,
    operator_service,
)


@pytest.mark.parametrize("turn_kind", ("message", "answer"))
async def test_cancellation_after_real_admission_commit_records_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    turn_kind: str,
) -> None:
    runner = RecordingTurnRunner((_ask_user_outcome(),) if turn_kind == "answer" else ())

    async with operator_service(tmp_path, runner=runner) as (service, session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        question_set: OperatorAssistantQuestionSetEntry | None = None
        if turn_kind == "answer":
            awaiting = await service.submit_message(
                created.id,
                OperatorMessageRequest(text="Ask me."),
                idempotency_key="message-1",
            )
            candidate = awaiting.entries[-1]
            assert isinstance(candidate, OperatorAssistantQuestionSetEntry)
            question_set = candidate

        committed = asyncio.Event()
        release_commit = asyncio.Event()
        _install_post_commit_barrier(
            monkeypatch,
            entry_kind=("user_question_answers" if question_set else "user_message"),
            committed=committed,
            release=release_commit,
        )
        submission = asyncio.create_task(
            _submit_test_turn(service, created.id, question_set),
        )
        await committed.wait()
        submission.cancel()
        release_commit.set()
        with pytest.raises(asyncio.CancelledError):
            await submission

        readback = await service.read_conversation(created.id)
        diagnostic = await _latest_diagnostic(session_factory, created.id)

    assert readback.state == "interrupted"
    assert readback.entries[-1].kind == "turn_interrupted"
    assert diagnostic == "admission_cancelled"
    assert len(runner.requests) == (1 if turn_kind == "answer" else 0)


async def test_completion_failure_retains_first_known_thread_for_next_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _two_message_runner()
    async with operator_service(tmp_path, runner=runner) as (service, session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        _install_first_assistant_commit_failure(monkeypatch)
        interrupted = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="First turn."),
            idempotency_key="message-1",
        )
        completed = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Second turn."),
            idempotency_key="message-2",
        )
        stored_thread = await _stored_thread_id(session_factory, created.id)

    assert interrupted.state == "interrupted"
    assert completed.state == "ready"
    assert stored_thread == "thread-known"
    assert runner.requests[1].provider_thread_id == "thread-known"


async def test_cancellation_after_outcome_retains_known_thread_for_next_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion_started = asyncio.Event()
    release_completion = asyncio.Event()

    runner = _two_message_runner()
    async with operator_service(tmp_path, runner=runner) as (service, session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        _install_first_assistant_pre_commit_barrier(
            monkeypatch,
            arrived=completion_started,
            release=release_completion,
        )
        submission = asyncio.create_task(
            service.submit_message(
                created.id,
                OperatorMessageRequest(text="First turn."),
                idempotency_key="message-1",
            )
        )
        await completion_started.wait()
        submission.cancel()
        with pytest.raises(asyncio.CancelledError):
            await submission
        release_completion.set()
        completed = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Second turn."),
            idempotency_key="message-2",
        )
        stored_thread = await _stored_thread_id(session_factory, created.id)

    assert completed.state == "ready"
    assert stored_thread == "thread-known"
    assert runner.requests[1].provider_thread_id == "thread-known"


async def test_active_duplicate_uses_bounded_backoff_then_returns_typed_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = BlockingTurnRunner(_message_outcome("One provider turn."))
    clock = [0.0]
    delays: list[float] = []

    async def advance_clock(delay: float) -> None:
        delays.append(delay)
        clock[0] += delay

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        primary = asyncio.create_task(
            service.submit_message(
                created.id,
                OperatorMessageRequest(text="Do this once."),
                idempotency_key="message-1",
            )
        )
        await runner.started.wait()
        monkeypatch.setattr(duplicate_wait_module, "_monotonic", lambda: clock[0])
        monkeypatch.setattr(duplicate_wait_module, "_sleep", advance_clock)
        with pytest.raises(OperatorTurnInProgressError):
            await service.submit_message(
                created.id,
                OperatorMessageRequest(text="Do this once."),
                idempotency_key="message-1",
            )
        runner.release.set()
        completed = await primary

    assert completed.state == "ready"
    assert delays[:3] == pytest.approx([0.05, 0.1, 0.2])
    assert max(delays) <= 0.25
    assert sum(delays) == pytest.approx(2.0)
    assert len(runner.requests) == 1


def _install_post_commit_barrier(
    monkeypatch: pytest.MonkeyPatch,
    *,
    entry_kind: str,
    committed: asyncio.Event,
    release: asyncio.Event,
) -> None:
    original_commit = AsyncSession.commit

    async def commit_then_wait(session: AsyncSession) -> None:
        should_wait = any(
            isinstance(record, OperatorConversationEntryModel) and record.kind == entry_kind
            for record in session.new
        )
        await original_commit(session)
        if should_wait:
            committed.set()
            await release.wait()

    monkeypatch.setattr(AsyncSession, "commit", commit_then_wait)


def _install_first_assistant_commit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    original_commit = AsyncSession.commit
    has_failed = False

    async def fail_first_assistant_commit(session: AsyncSession) -> None:
        nonlocal has_failed
        should_fail = not has_failed and any(
            isinstance(record, OperatorConversationEntryModel)
            and record.kind == "assistant_message"
            for record in session.new
        )
        if should_fail:
            has_failed = True
            raise RuntimeError("forced completion commit failure")
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", fail_first_assistant_commit)


def _install_first_assistant_pre_commit_barrier(
    monkeypatch: pytest.MonkeyPatch,
    *,
    arrived: asyncio.Event,
    release: asyncio.Event,
) -> None:
    original_commit = AsyncSession.commit
    has_waited = False

    async def wait_before_first_assistant_commit(session: AsyncSession) -> None:
        nonlocal has_waited
        should_wait = not has_waited and any(
            isinstance(record, OperatorConversationEntryModel)
            and record.kind == "assistant_message"
            for record in session.new
        )
        if should_wait:
            has_waited = True
            arrived.set()
            await release.wait()
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", wait_before_first_assistant_commit)


async def _submit_test_turn(
    service: OperatorConversationService,
    conversation_id: str,
    question_set: OperatorAssistantQuestionSetEntry | None,
) -> object:
    if question_set is None:
        return await service.submit_message(
            conversation_id,
            OperatorMessageRequest(text="Cancel after admission."),
            idempotency_key="message-cancel",
        )
    request = {
        "answers": [
            {
                "question_id": question_set.questions[0].id,
                "answer": {
                    "kind": "option",
                    "option_id": question_set.questions[0].options[0].id,
                },
            }
        ]
    }
    return await service.submit_question_answers(
        conversation_id,
        question_set.id,
        OperatorQuestionAnswersRequest.model_validate(request),
        idempotency_key="answer-cancel",
    )


async def _latest_diagnostic(
    session_factory: OperatorSessionFactory,
    conversation_id: str,
) -> object:
    async with session_factory() as session:
        entry = await session.scalar(
            select(OperatorConversationEntryModel)
            .where(OperatorConversationEntryModel.conversation_id == conversation_id)
            .order_by(OperatorConversationEntryModel.sequence.desc())
            .limit(1)
        )
    assert entry is not None
    return entry.body_json.get("diagnostic_category")


async def _stored_thread_id(
    session_factory: OperatorSessionFactory,
    conversation_id: str,
) -> str | None:
    async with session_factory() as session:
        return await session.scalar(
            select(OperatorConversationModel.provider_thread_id).where(
                OperatorConversationModel.conversation_id == conversation_id
            )
        )


def _ask_user_outcome() -> OperatorTurnOutcome:
    return OperatorTurnOutcome(
        provider_thread_id="thread-known",
        result=OperatorProviderAskUserResult.model_validate(
            {
                "kind": "ask_user",
                "questions": [
                    {
                        "header": "Choice",
                        "question": "Which choice?",
                        "options": [
                            {"label": "First", "description": "Use the first."},
                            {"label": "Second", "description": "Use the second."},
                        ],
                    }
                ],
            }
        ),
    )


def _message_outcome(text: str) -> OperatorTurnOutcome:
    return OperatorTurnOutcome(
        provider_thread_id="thread-known",
        result=OperatorProviderMessageResult(kind="message", text=text),
    )


def _two_message_runner() -> RecordingTurnRunner:
    return RecordingTurnRunner(
        (
            _message_outcome("First outcome."),
            _message_outcome("Second outcome."),
        )
    )
