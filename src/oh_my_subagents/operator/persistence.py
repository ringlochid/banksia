from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.operator.contracts import (
    OperatorAssistantQuestionSetEntry,
    OperatorMessageRequest,
    OperatorQuestionAnswersRequest,
)
from oh_my_subagents.operator.conversation_reads import OperatorSessionFactory, map_entry
from oh_my_subagents.operator.errors import (
    OperatorAnswerValidationError,
    OperatorConversationConflictError,
    OperatorConversationNotFoundError,
    OperatorIdempotencyConflictError,
    OperatorQuestionSetNotFoundError,
)
from oh_my_subagents.operator.provider import (
    OperatorAcceptedAnswer,
    OperatorAcceptedCustomAnswer,
    OperatorAcceptedOptionAnswer,
    OperatorAcceptedSkipAnswer,
    OperatorAnsweredQuestion,
    OperatorMessageTurnInput,
    OperatorQuestionAnswersTurnInput,
    OperatorTurnOutcome,
    OperatorTurnRequest,
)
from oh_my_subagents.operator.turn_entries import (
    build_assistant_entry,
    build_interruption_entry,
)
from oh_my_subagents.persistence.models import (
    OperatorConversationEntryModel,
    OperatorConversationModel,
)
from oh_my_subagents.runtime.clock import utc_now


@dataclass(frozen=True, slots=True)
class OperatorTurnClaim:
    conversation_id: str
    turn_id: str | None
    request: OperatorTurnRequest | None
    active_duplicate_sequence: int | None = None

    @property
    def is_duplicate(self) -> bool:
        return self.turn_id is None


async def claim_operator_message_turn(
    session_factory: OperatorSessionFactory,
    *,
    conversation_id: str,
    request: OperatorMessageRequest,
    idempotency_key: str,
) -> OperatorTurnClaim:
    request_digest = _digest_request(
        {
            "kind": "message",
            "text": request.text,
        }
    )
    turn_id = f"operator-turn.{uuid4().hex}"
    now = utc_now()

    async with session_factory() as session:
        try:
            row = await _claim_conversation(
                session,
                conversation_id=conversation_id,
                idempotency_key=idempotency_key,
                allowed_states=("ready", "interrupted"),
                turn_id=turn_id,
                now=now,
            )
            if row is None:
                return await _return_duplicate_or_raise_conflict(
                    session,
                    conversation_id=conversation_id,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                )

            sequence = await _next_entry_sequence(session, conversation_id)
            session.add(
                OperatorConversationEntryModel(
                    entry_id=f"operator-entry.{uuid4().hex}",
                    conversation_id=conversation_id,
                    sequence=sequence,
                    kind="user_message",
                    body_json={"text": request.text},
                    request_idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    created_at=now,
                )
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise

    return OperatorTurnClaim(
        conversation_id=conversation_id,
        turn_id=turn_id,
        request=OperatorTurnRequest(
            provider=row.provider,
            model=row.model,
            effort=row.effort,
            provider_thread_id=row.provider_thread_id,
            input=OperatorMessageTurnInput(text=request.text),
        ),
    )


async def claim_operator_answer_turn(
    session_factory: OperatorSessionFactory,
    *,
    conversation_id: str,
    question_set_id: str,
    request: OperatorQuestionAnswersRequest,
    idempotency_key: str,
) -> OperatorTurnClaim:
    request_digest = _digest_request(
        {
            "kind": "question_answers",
            "question_set_id": question_set_id,
            "answers": request.model_dump(mode="json")["answers"],
        }
    )
    turn_id = f"operator-turn.{uuid4().hex}"
    now = utc_now()

    async with session_factory() as session:
        try:
            row = await _claim_conversation(
                session,
                conversation_id=conversation_id,
                idempotency_key=idempotency_key,
                allowed_states=("awaiting_answer",),
                turn_id=turn_id,
                now=now,
            )
            if row is None:
                return await _return_duplicate_or_raise_conflict(
                    session,
                    conversation_id=conversation_id,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                )

            question_set = await _read_question_set_for_answer(
                session,
                conversation_id=conversation_id,
                question_set_id=question_set_id,
            )
            resolved_answers = _validate_and_resolve_answers(question_set, request)
            sequence = await _next_entry_sequence(session, conversation_id)
            session.add(
                OperatorConversationEntryModel(
                    entry_id=f"operator-entry.{uuid4().hex}",
                    conversation_id=conversation_id,
                    sequence=sequence,
                    kind="user_question_answers",
                    body_json={
                        "question_set_id": question_set_id,
                        "answers": request.model_dump(mode="json")["answers"],
                    },
                    request_idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    created_at=now,
                )
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise

    return OperatorTurnClaim(
        conversation_id=conversation_id,
        turn_id=turn_id,
        request=OperatorTurnRequest(
            provider=row.provider,
            model=row.model,
            effort=row.effort,
            provider_thread_id=row.provider_thread_id,
            input=OperatorQuestionAnswersTurnInput(
                answers=resolved_answers,
            ),
        ),
    )


async def complete_operator_turn(
    session_factory: OperatorSessionFactory,
    *,
    claim: OperatorTurnClaim,
    outcome: OperatorTurnOutcome,
) -> bool:
    if claim.turn_id is None:
        return False
    now = utc_now()
    target_state = "ready" if outcome.result.kind == "message" else "awaiting_answer"

    async with session_factory() as session:
        try:
            matched_id = await session.scalar(
                update(OperatorConversationModel)
                .where(
                    OperatorConversationModel.conversation_id == claim.conversation_id,
                    OperatorConversationModel.state == "running",
                    OperatorConversationModel.active_turn_id == claim.turn_id,
                )
                .values(
                    provider_thread_id=outcome.provider_thread_id,
                    state=target_state,
                    active_turn_id=None,
                    updated_at=now,
                )
                .returning(OperatorConversationModel.conversation_id)
                .execution_options(synchronize_session=False)
            )
            if matched_id is None:
                await session.rollback()
                return False

            sequence = await _next_entry_sequence(session, claim.conversation_id)
            session.add(
                build_assistant_entry(
                    conversation_id=claim.conversation_id,
                    sequence=sequence,
                    outcome=outcome,
                    created_at=now,
                )
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
    return True


async def interrupt_operator_turn(
    session_factory: OperatorSessionFactory,
    *,
    claim: OperatorTurnClaim,
    is_thread_unavailable: bool,
    diagnostic_category: str,
    provider_thread_id: str | None = None,
) -> bool:
    if claim.turn_id is None:
        return False
    return await _interrupt_matching_turn(
        session_factory,
        conversation_id=claim.conversation_id,
        turn_id=claim.turn_id,
        is_thread_unavailable=is_thread_unavailable,
        diagnostic_category=diagnostic_category,
        provider_thread_id=provider_thread_id,
    )


async def repair_stranded_operator_turns(
    session_factory: OperatorSessionFactory,
) -> int:
    now = utc_now()
    async with session_factory() as session:
        try:
            stranded_ids = list(
                (
                    await session.scalars(
                        update(OperatorConversationModel)
                        .where(
                            OperatorConversationModel.state == "running",
                            OperatorConversationModel.active_turn_id.is_not(None),
                        )
                        .values(
                            state="interrupted",
                            active_turn_id=None,
                            updated_at=now,
                        )
                        .returning(OperatorConversationModel.conversation_id)
                        .execution_options(synchronize_session=False)
                    )
                ).all()
            )
            for conversation_id in stranded_ids:
                sequence = await _next_entry_sequence(session, conversation_id)
                session.add(
                    build_interruption_entry(
                        conversation_id=conversation_id,
                        sequence=sequence,
                        is_thread_unavailable=False,
                        diagnostic_category="startup_repair",
                        created_at=now,
                    )
                )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
    return len(stranded_ids)


def _validate_and_resolve_answers(
    question_set: OperatorAssistantQuestionSetEntry,
    request: OperatorQuestionAnswersRequest,
) -> tuple[OperatorAnsweredQuestion, ...]:
    expected_ids = tuple(question.id for question in question_set.questions)
    submitted_ids = tuple(answer.question_id for answer in request.answers)
    if submitted_ids != expected_ids:
        raise OperatorAnswerValidationError(
            "answers must contain each current question exactly once in question order"
        )

    resolved: list[OperatorAnsweredQuestion] = []
    for question, submitted in zip(question_set.questions, request.answers, strict=True):
        answer = submitted.answer
        accepted: OperatorAcceptedAnswer
        if answer.kind == "option":
            option = next(
                (candidate for candidate in question.options if candidate.id == answer.option_id),
                None,
            )
            if option is None:
                raise OperatorAnswerValidationError(
                    "an option answer must name one current controller-issued option"
                )
            accepted = OperatorAcceptedOptionAnswer(
                label=option.label,
            )
        elif answer.kind == "custom":
            accepted = OperatorAcceptedCustomAnswer(text=answer.text)
        else:
            if not question.allow_skip:
                raise OperatorAnswerValidationError(
                    "Skip is legal only when the current question allows it"
                )
            accepted = OperatorAcceptedSkipAnswer()
        resolved.append(
            OperatorAnsweredQuestion(
                question=question.question,
                answer=accepted,
            )
        )
    return tuple(resolved)


def _digest_request(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


async def _claim_conversation(
    session: AsyncSession,
    *,
    conversation_id: str,
    idempotency_key: str,
    allowed_states: tuple[str, ...],
    turn_id: str,
    now: datetime,
) -> Any | None:
    duplicate_exists = exists(
        select(OperatorConversationEntryModel.entry_id).where(
            OperatorConversationEntryModel.conversation_id == conversation_id,
            OperatorConversationEntryModel.request_idempotency_key == idempotency_key,
        )
    )
    result = await session.execute(
        update(OperatorConversationModel)
        .where(
            OperatorConversationModel.conversation_id == conversation_id,
            OperatorConversationModel.active_turn_id.is_(None),
            OperatorConversationModel.state.in_(allowed_states),
            ~duplicate_exists,
        )
        .values(
            state="running",
            active_turn_id=turn_id,
            updated_at=now,
        )
        .returning(
            OperatorConversationModel.provider,
            OperatorConversationModel.model,
            OperatorConversationModel.effort,
            OperatorConversationModel.provider_thread_id,
        )
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none()


async def _return_duplicate_or_raise_conflict(
    session: AsyncSession,
    *,
    conversation_id: str,
    idempotency_key: str,
    request_digest: str,
) -> OperatorTurnClaim:
    existing_entry = await session.scalar(
        select(OperatorConversationEntryModel).where(
            OperatorConversationEntryModel.conversation_id == conversation_id,
            OperatorConversationEntryModel.request_idempotency_key == idempotency_key,
        )
    )
    if existing_entry is not None:
        if existing_entry.request_digest != request_digest:
            raise OperatorIdempotencyConflictError(
                "the idempotency key already belongs to another normalized request"
            )
        existing_sequence = existing_entry.sequence
        conversation_state = await session.scalar(
            select(OperatorConversationModel.state).where(
                OperatorConversationModel.conversation_id == conversation_id
            )
        )
        latest_sequence = await session.scalar(
            select(func.max(OperatorConversationEntryModel.sequence)).where(
                OperatorConversationEntryModel.conversation_id == conversation_id
            )
        )
        await session.rollback()
        return OperatorTurnClaim(
            conversation_id=conversation_id,
            turn_id=None,
            request=None,
            active_duplicate_sequence=(
                existing_sequence
                if conversation_state == "running" and latest_sequence == existing_sequence
                else None
            ),
        )

    conversation_state = await session.scalar(
        select(OperatorConversationModel.state).where(
            OperatorConversationModel.conversation_id == conversation_id
        )
    )
    if conversation_state is None:
        raise OperatorConversationNotFoundError(conversation_id)
    raise OperatorConversationConflictError(
        f"conversation state {conversation_state!r} does not accept this turn"
    )


async def _read_question_set_for_answer(
    session: AsyncSession,
    *,
    conversation_id: str,
    question_set_id: str,
) -> OperatorAssistantQuestionSetEntry:
    entry = await session.scalar(
        select(OperatorConversationEntryModel)
        .where(
            OperatorConversationEntryModel.conversation_id == conversation_id,
            OperatorConversationEntryModel.kind == "assistant_question_set",
        )
        .order_by(OperatorConversationEntryModel.sequence.desc())
        .limit(1)
    )
    if entry is None or entry.entry_id != question_set_id:
        raise OperatorQuestionSetNotFoundError(question_set_id)
    mapped = map_entry(entry)
    if not isinstance(mapped, OperatorAssistantQuestionSetEntry):
        raise RuntimeError("stored Operator question set has an invalid kind")
    return mapped


async def _interrupt_matching_turn(
    session_factory: OperatorSessionFactory,
    *,
    conversation_id: str,
    turn_id: str,
    is_thread_unavailable: bool,
    diagnostic_category: str,
    provider_thread_id: str | None,
) -> bool:
    now = utc_now()
    target_state = "closed" if is_thread_unavailable else "interrupted"
    update_values: dict[str, object] = {
        "state": target_state,
        "active_turn_id": None,
        "updated_at": now,
    }
    if provider_thread_id is not None:
        update_values["provider_thread_id"] = provider_thread_id
    async with session_factory() as session:
        try:
            matched_id = await session.scalar(
                update(OperatorConversationModel)
                .where(
                    OperatorConversationModel.conversation_id == conversation_id,
                    OperatorConversationModel.state == "running",
                    OperatorConversationModel.active_turn_id == turn_id,
                )
                .values(**update_values)
                .returning(OperatorConversationModel.conversation_id)
                .execution_options(synchronize_session=False)
            )
            if matched_id is None:
                await session.rollback()
                return False
            sequence = await _next_entry_sequence(session, conversation_id)
            session.add(
                build_interruption_entry(
                    conversation_id=conversation_id,
                    sequence=sequence,
                    is_thread_unavailable=is_thread_unavailable,
                    diagnostic_category=diagnostic_category,
                    created_at=now,
                )
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
    return True


async def _next_entry_sequence(
    session: AsyncSession,
    conversation_id: str,
) -> int:
    latest = await session.scalar(
        select(func.max(OperatorConversationEntryModel.sequence)).where(
            OperatorConversationEntryModel.conversation_id == conversation_id
        )
    )
    return int(latest or 0) + 1


__all__ = [
    "OperatorTurnClaim",
    "claim_operator_answer_turn",
    "claim_operator_message_turn",
    "complete_operator_turn",
    "interrupt_operator_turn",
    "repair_stranded_operator_turns",
]
