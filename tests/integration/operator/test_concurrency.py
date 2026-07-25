from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator import (
    OperatorConversationConflictError,
    OperatorConversationService,
    OperatorIdempotencyConflictError,
    OperatorProviderAskUserResult,
    OperatorProviderMessageResult,
    OperatorTurnOutcome,
    OperatorTurnRequest,
)
from banksia.operator.contracts import (
    OperatorAssistantQuestionSetEntry,
    OperatorMessageRequest,
    OperatorQuestionAnswersRequest,
)
from banksia.operator.conversation_reads import OperatorSessionFactory
from banksia.operator.persistence import (
    OperatorTurnClaim,
    claim_operator_message_turn,
    complete_operator_turn,
    interrupt_operator_turn,
    repair_stranded_operator_turns,
)
from banksia.persistence import (
    OperatorConversationEntryModel,
    OperatorConversationModel,
)
from tests.helpers.operator import RecordingTurnRunner
from tests.helpers.workflow_concurrency import (
    DatabaseBackend,
    TwoPartyBarrier,
    workflow_database,
)


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_concurrent_create_key_converges_on_one_conversation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    runner = RecordingTurnRunner(())

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        service = OperatorConversationService(session_factory=session_factory, runner=runner)
        _install_create_commit_barrier(monkeypatch)
        first, second = await asyncio.gather(
            service.create_conversation(idempotency_key="create-race"),
            service.create_conversation(idempotency_key="create-race"),
        )
        async with session_factory() as session:
            conversation_ids = tuple(
                await session.scalars(select(OperatorConversationModel.conversation_id))
            )

    assert first == second
    assert conversation_ids == (first.id,)
    assert runner.requests == []


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_readback_is_one_committed_snapshot_during_turn_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    runner = RecordingTurnRunner(())
    read_row_selected = asyncio.Event()
    release_read = asyncio.Event()
    admission_update_started = asyncio.Event()

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        service = OperatorConversationService(session_factory=session_factory, runner=runner)
        created = await service.create_conversation(idempotency_key="create-1")
        _install_read_admission_barrier(
            monkeypatch,
            read_row_selected=read_row_selected,
            release_read=release_read,
            admission_update_started=admission_update_started,
        )
        read_task = asyncio.create_task(service.read_conversation(created.id))
        await read_row_selected.wait()
        claim_task = asyncio.create_task(
            claim_operator_message_turn(
                session_factory,
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Admit while reading."),
                idempotency_key="message-1",
            )
        )
        await admission_update_started.wait()
        update_waited_for_read_lock = True
        if database_backend == "sqlite":
            await claim_task
        else:
            update_waited_for_read_lock = await _postgres_update_waits_for_read_lock(
                session_factory,
                claim_task=claim_task,
            )
        release_read.set()
        snapshot = await read_task
        claim = await claim_task
        admitted = await service.read_conversation(created.id)
        await interrupt_operator_turn(
            session_factory,
            claim=claim,
            is_thread_unavailable=False,
            diagnostic_category="turn_cancelled",
        )

    assert update_waited_for_read_lock
    assert (
        snapshot.state,
        tuple(entry.kind for entry in snapshot.entries),
        tuple(action.kind for action in snapshot.actions),
    ) == ("ready", (), ("send_message",))
    assert (
        admitted.state,
        tuple(entry.kind for entry in admitted.entries),
        tuple(action.kind for action in admitted.actions),
    ) == ("running", ("user_message",), ())


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_blocked_answer_rejects_competing_turns_without_provider_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    runner = RecordingTurnRunner((_ask_user_outcome(), _message_outcome()))
    answer_started = asyncio.Event()
    release_answer = asyncio.Event()
    original_execute = runner.execute_turn

    async def block_answer(request: OperatorTurnRequest) -> OperatorTurnOutcome:
        if request.input.kind == "question_answers":
            answer_started.set()
            await release_answer.wait()
        return await original_execute(request)

    monkeypatch.setattr(runner, "execute_turn", block_answer)
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        service = OperatorConversationService(session_factory=session_factory, runner=runner)
        created = await service.create_conversation(idempotency_key="create-1")
        awaiting = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Ask me."),
            idempotency_key="message-1",
        )
        question_set = awaiting.entries[-1]
        assert isinstance(question_set, OperatorAssistantQuestionSetEntry)
        request = _option_answers(question_set)
        answer_task = asyncio.create_task(
            service.submit_question_answers(
                created.id,
                question_set.id,
                request,
                idempotency_key="answer-1",
            )
        )
        await answer_started.wait()
        try:
            await _assert_competing_turns_reject(service, created.id, question_set, request)
        finally:
            release_answer.set()
        completed = await answer_task
        stored_entries = await _stored_entries(session_factory, created.id)

    assert completed.state == "ready"
    assert len(runner.requests) == 2
    _assert_strict_entries(
        stored_entries,
        (
            "user_message",
            "assistant_question_set",
            "user_question_answers",
            "assistant_message",
        ),
    )


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_correct_and_wrong_active_completion_have_one_exact_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    runner = RecordingTurnRunner(())

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        service = OperatorConversationService(session_factory=session_factory, runner=runner)
        created = await service.create_conversation(idempotency_key="create-1")
        claim = await claim_operator_message_turn(
            session_factory,
            conversation_id=created.id,
            request=OperatorMessageRequest(text="Complete exactly once."),
            idempotency_key="message-1",
        )
        wrong_claim = OperatorTurnClaim(
            conversation_id=claim.conversation_id,
            turn_id="operator-turn.wrong",
            request=claim.request,
        )
        _install_operator_update_barrier(monkeypatch)
        correct, wrong = await asyncio.gather(
            complete_operator_turn(session_factory, claim=claim, outcome=_message_outcome()),
            complete_operator_turn(session_factory, claim=wrong_claim, outcome=_message_outcome()),
        )
        readback = await service.read_conversation(created.id)
        stored_entries = await _stored_entries(session_factory, created.id)

    assert (correct, wrong) == (True, False)
    assert readback.state == "ready"
    _assert_strict_entries(stored_entries, ("user_message", "assistant_message"))


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_completion_and_startup_repair_have_one_durable_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    runner = RecordingTurnRunner(())

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        service = OperatorConversationService(session_factory=session_factory, runner=runner)
        created = await service.create_conversation(idempotency_key="create-1")
        claim = await claim_operator_message_turn(
            session_factory,
            conversation_id=created.id,
            request=OperatorMessageRequest(text="Race recovery."),
            idempotency_key="message-1",
        )
        _install_operator_update_barrier(monkeypatch)
        completed, repaired = await asyncio.gather(
            complete_operator_turn(session_factory, claim=claim, outcome=_message_outcome()),
            repair_stranded_operator_turns(session_factory),
        )
        readback = await service.read_conversation(created.id)
        stored_entries = await _stored_entries(session_factory, created.id)

    assert (completed, repaired) in {(True, 0), (False, 1)}
    if completed:
        assert readback.state == "ready"
        expected_kinds = ("user_message", "assistant_message")
    else:
        assert readback.state == "interrupted"
        expected_kinds = ("user_message", "turn_interrupted")
    _assert_strict_entries(stored_entries, expected_kinds)


async def _assert_competing_turns_reject(
    service: OperatorConversationService,
    conversation_id: str,
    question_set: OperatorAssistantQuestionSetEntry,
    request: OperatorQuestionAnswersRequest,
) -> None:
    with pytest.raises(OperatorConversationConflictError):
        await service.submit_message(
            conversation_id,
            OperatorMessageRequest(text="Competing message."),
            idempotency_key="message-competing",
        )
    changed = OperatorQuestionAnswersRequest.model_validate(
        {
            "answers": [
                {
                    "question_id": request.answers[0].question_id,
                    "answer": {"kind": "custom", "text": "Different."},
                }
            ]
        }
    )
    with pytest.raises(OperatorIdempotencyConflictError):
        await service.submit_question_answers(
            conversation_id,
            question_set.id,
            changed,
            idempotency_key="answer-1",
        )


def _install_create_commit_barrier(monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = TwoPartyBarrier()
    original_commit = AsyncSession.commit

    async def commit_together(session: AsyncSession) -> None:
        if any(isinstance(record, OperatorConversationModel) for record in session.new):
            await barrier.wait()
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", commit_together)


def _install_operator_update_barrier(monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = TwoPartyBarrier()
    arrivals = 0
    original_scalar = AsyncSession.scalar
    original_scalars = AsyncSession.scalars

    async def wait_for_pair(statement: Any) -> None:
        nonlocal arrivals
        if arrivals < 2 and "UPDATE operator_conversations" in str(statement):
            arrivals += 1
            await barrier.wait()

    async def scalar_together(
        session: AsyncSession,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        await wait_for_pair(statement)
        return await original_scalar(session, statement, *args, **kwargs)

    async def scalars_together(
        session: AsyncSession,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        await wait_for_pair(statement)
        return await original_scalars(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", scalar_together)
    monkeypatch.setattr(AsyncSession, "scalars", scalars_together)


def _install_read_admission_barrier(
    monkeypatch: pytest.MonkeyPatch,
    *,
    read_row_selected: asyncio.Event,
    release_read: asyncio.Event,
    admission_update_started: asyncio.Event,
) -> None:
    original_execute = AsyncSession.execute
    original_scalar = AsyncSession.scalar
    has_paused_read = False

    async def track_admission_update(
        session: AsyncSession,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if "UPDATE operator_conversations" in str(statement):
            admission_update_started.set()
        return await original_execute(session, statement, *args, **kwargs)

    async def pause_after_conversation_read(
        session: AsyncSession,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        nonlocal has_paused_read
        result = await original_scalar(session, statement, *args, **kwargs)
        rendered = str(statement)
        if (
            not has_paused_read
            and "FROM operator_conversations" in rendered
            and "FOR UPDATE" in rendered
        ):
            has_paused_read = True
            read_row_selected.set()
            await release_read.wait()
        return result

    monkeypatch.setattr(AsyncSession, "execute", track_admission_update)
    monkeypatch.setattr(AsyncSession, "scalar", pause_after_conversation_read)


async def _postgres_update_waits_for_read_lock(
    session_factory: OperatorSessionFactory,
    *,
    claim_task: asyncio.Task[OperatorTurnClaim],
) -> bool:
    query = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_stat_activity
            WHERE pid <> pg_backend_pid()
              AND datname = current_database()
              AND state = 'active'
              AND wait_event_type = 'Lock'
              AND query ILIKE '%UPDATE%operator_conversations%'
        )
        """
    )
    async with session_factory() as session:
        for _attempt in range(200):
            if claim_task.done():
                return False
            if await session.scalar(query):
                return True
    return False


async def _stored_entries(
    session_factory: OperatorSessionFactory,
    conversation_id: str,
) -> list[OperatorConversationEntryModel]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(OperatorConversationEntryModel)
                    .where(OperatorConversationEntryModel.conversation_id == conversation_id)
                    .order_by(OperatorConversationEntryModel.sequence)
                )
            ).all()
        )


def _assert_strict_entries(
    entries: list[OperatorConversationEntryModel],
    expected_kinds: tuple[str, ...],
) -> None:
    assert tuple(entry.sequence for entry in entries) == tuple(range(1, len(entries) + 1))
    assert tuple(entry.kind for entry in entries) == expected_kinds


def _option_answers(
    question_set: OperatorAssistantQuestionSetEntry,
) -> OperatorQuestionAnswersRequest:
    return OperatorQuestionAnswersRequest.model_validate(
        {
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
    )


def _ask_user_outcome() -> OperatorTurnOutcome:
    return OperatorTurnOutcome(
        provider_thread_id="thread-cross-dialect",
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


def _message_outcome() -> OperatorTurnOutcome:
    return OperatorTurnOutcome(
        provider_thread_id="thread-cross-dialect",
        result=OperatorProviderMessageResult(kind="message", text="Completed."),
    )
