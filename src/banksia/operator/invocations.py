from __future__ import annotations

import asyncio

from sqlalchemy import exists, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.contention import (
    OPERATOR_PERSISTENCE_ATTEMPTS,
    OperatorPersistenceContentionError,
    is_recognized_persistence_contention,
)
from banksia.operator.contracts import (
    OperatorProviderAskUserResult,
    OperatorProviderMessageResult,
)
from banksia.operator.effects import OperatorEffectService
from banksia.operator.failure_entries import build_provider_failure_body
from banksia.operator.provider import (
    OperatorProviderError,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.storage import (
    OperatorSessionFactory,
    allocate_operator_id,
    create_operator_entry,
    create_operator_entry_at_sequence,
)
from banksia.operator.thread_loss import finalize_operator_thread_loss
from banksia.persistence.models import (
    OperatorConversationModel,
    OperatorEffectModel,
    OperatorInvocationModel,
)
from banksia.runtime.clock import utc_now

_CROSSED_EFFECT_STATES = ("executing", "succeeded", "failed", "indeterminate")


class OperatorInvocationService:
    def __init__(
        self,
        *,
        session_factory: OperatorSessionFactory,
        effects: OperatorEffectService,
    ) -> None:
        self._session_factory = session_factory
        self._effects = effects

    async def claim_provider_invocation(
        self,
        invocation_id: str,
    ) -> OperatorProviderInvocation | None:
        for attempt in range(OPERATOR_PERSISTENCE_ATTEMPTS):
            try:
                return await self._claim_provider_invocation(invocation_id)
            except OperationalError as exc:
                if not is_recognized_persistence_contention(exc):
                    raise
                if attempt + 1 == OPERATOR_PERSISTENCE_ATTEMPTS:
                    raise OperatorPersistenceContentionError from None
                await asyncio.sleep(0)
        raise AssertionError("Operator persistence retry loop did not return")

    async def _claim_provider_invocation(
        self,
        invocation_id: str,
    ) -> OperatorProviderInvocation | None:
        now = utc_now()
        current_conversation = exists(
            select(OperatorConversationModel.conversation_id).where(
                OperatorConversationModel.conversation_id
                == OperatorInvocationModel.conversation_id,
                OperatorConversationModel.state == "running",
                OperatorConversationModel.claim_generation
                == OperatorInvocationModel.claim_generation,
            )
        )
        async with self._session_factory() as session:
            async with session.begin():
                claimed = (
                    await session.execute(
                        update(OperatorInvocationModel)
                        .where(
                            OperatorInvocationModel.invocation_id == invocation_id,
                            OperatorInvocationModel.state == "queued",
                            current_conversation,
                        )
                        .values(state="running", started_at=now)
                        .returning(
                            OperatorInvocationModel.conversation_id,
                            OperatorInvocationModel.claim_generation,
                            OperatorInvocationModel.provider_input,
                        )
                        .execution_options(synchronize_session=False)
                    )
                ).one_or_none()
                if claimed is None:
                    await session.execute(
                        update(OperatorInvocationModel)
                        .where(
                            OperatorInvocationModel.invocation_id == invocation_id,
                            OperatorInvocationModel.state == "queued",
                            ~current_conversation,
                        )
                        .values(
                            state="failed",
                            failure_problem="stale_claim",
                            is_retry_safe=False,
                            ended_at=now,
                        )
                    )
                    return None
                conversation = (
                    await session.execute(
                        select(
                            OperatorConversationModel.provider_thread_id,
                            OperatorConversationModel.resolved_model,
                            OperatorConversationModel.resolved_effort,
                        ).where(
                            OperatorConversationModel.conversation_id == claimed.conversation_id
                        )
                    )
                ).one()
                return OperatorProviderInvocation(
                    conversation_id=claimed.conversation_id,
                    invocation_id=invocation_id,
                    claim_generation=claimed.claim_generation,
                    provider_input=claimed.provider_input,
                    provider_thread_id=conversation.provider_thread_id,
                    resolved_model=conversation.resolved_model,
                    resolved_effort=conversation.resolved_effort,
                )

    async def complete_provider_invocation(
        self,
        invocation: OperatorProviderInvocation,
        outcome: OperatorProviderOutcome,
    ) -> None:
        for attempt in range(OPERATOR_PERSISTENCE_ATTEMPTS):
            try:
                continuity_was_lost = await self._complete_provider_invocation(
                    invocation,
                    outcome,
                )
                if continuity_was_lost:
                    await finalize_operator_thread_loss(
                        self._session_factory,
                        invocation,
                        problem="thread_lost",
                        explanation=OperatorProviderError.explanation_for("thread_lost"),
                        provider_turn_reference=outcome.provider_turn_reference,
                    )
                return
            except OperationalError as exc:
                if not is_recognized_persistence_contention(exc):
                    raise
                if attempt + 1 == OPERATOR_PERSISTENCE_ATTEMPTS:
                    raise OperatorPersistenceContentionError from None
                await asyncio.sleep(0)

    async def _complete_provider_invocation(
        self,
        invocation: OperatorProviderInvocation,
        outcome: OperatorProviderOutcome,
    ) -> bool:
        entry_kind, entry_body, conversation_state = _provider_result_entry(outcome)
        now = utc_now()
        async with self._session_factory() as session:
            try:
                async with session.begin():
                    stored = (
                        await session.execute(
                            update(OperatorInvocationModel)
                            .where(
                                OperatorInvocationModel.invocation_id == invocation.invocation_id,
                                OperatorInvocationModel.conversation_id
                                == invocation.conversation_id,
                                OperatorInvocationModel.claim_generation
                                == invocation.claim_generation,
                                OperatorInvocationModel.state == "running",
                            )
                            .values(
                                state="completed",
                                provider_turn_reference=outcome.provider_turn_reference,
                                ended_at=now,
                            )
                            .returning(OperatorInvocationModel.input_entry_id)
                            .execution_options(synchronize_session=False)
                        )
                    ).one_or_none()
                    if stored is None:
                        return False
                    if outcome.provider_thread_id is None:
                        raise _ThreadContinuityLostError
                    conversation = (
                        await session.execute(
                            update(OperatorConversationModel)
                            .where(
                                OperatorConversationModel.conversation_id
                                == invocation.conversation_id,
                                OperatorConversationModel.state == "running",
                                OperatorConversationModel.claim_generation
                                == invocation.claim_generation,
                                or_(
                                    OperatorConversationModel.provider_thread_id.is_(None),
                                    OperatorConversationModel.provider_thread_id
                                    == outcome.provider_thread_id,
                                ),
                            )
                            .values(
                                state=conversation_state,
                                provider_thread_id=outcome.provider_thread_id,
                                next_entry_sequence=(
                                    OperatorConversationModel.next_entry_sequence + 1
                                ),
                                updated_at=now,
                            )
                            .returning(OperatorConversationModel.next_entry_sequence)
                            .execution_options(synchronize_session=False)
                        )
                    ).one_or_none()
                    if conversation is None:
                        raise _ThreadContinuityLostError
                    session.add(
                        create_operator_entry_at_sequence(
                            conversation_id=invocation.conversation_id,
                            sequence=conversation.next_entry_sequence - 1,
                            kind=entry_kind,
                            body=entry_body,
                            causal_entry_id=stored.input_entry_id,
                        )
                    )
            except _ThreadContinuityLostError:
                return True
        return False

    async def fail_provider_invocation(
        self,
        invocation: OperatorProviderInvocation,
        failure: OperatorProviderError,
    ) -> None:
        for attempt in range(OPERATOR_PERSISTENCE_ATTEMPTS):
            try:
                if failure.is_thread_lost:
                    await finalize_operator_thread_loss(
                        self._session_factory,
                        invocation,
                        problem=failure.problem,
                        explanation=failure.explanation,
                    )
                    return
                if await self._finalize_crossed_effect_failure(invocation, failure):
                    return
                await self._finalize_retryable_failure(invocation, failure)
                return
            except OperationalError as exc:
                if not is_recognized_persistence_contention(exc):
                    raise
                if attempt + 1 == OPERATOR_PERSISTENCE_ATTEMPTS:
                    raise OperatorPersistenceContentionError from None
                await asyncio.sleep(0)

    async def _finalize_crossed_effect_failure(
        self,
        invocation: OperatorProviderInvocation,
        failure: OperatorProviderError,
    ) -> bool:
        crossed_effect = exists(
            select(OperatorEffectModel.effect_id).where(
                OperatorEffectModel.invocation_id == invocation.invocation_id,
                OperatorEffectModel.state.in_(_CROSSED_EFFECT_STATES),
            )
        )
        now = utc_now()
        async with self._session_factory() as session:
            try:
                async with session.begin():
                    stored = (
                        await session.execute(
                            update(OperatorInvocationModel)
                            .where(
                                OperatorInvocationModel.invocation_id == invocation.invocation_id,
                                OperatorInvocationModel.conversation_id
                                == invocation.conversation_id,
                                OperatorInvocationModel.claim_generation
                                == invocation.claim_generation,
                                OperatorInvocationModel.state == "running",
                                crossed_effect,
                            )
                            .values(
                                state="failed",
                                failure_problem=failure.problem,
                                is_retry_safe=False,
                                ended_at=now,
                            )
                            .returning(OperatorInvocationModel.invocation_id)
                            .execution_options(synchronize_session=False)
                        )
                    ).one_or_none()
                    if stored is None:
                        return False
                    conversation = (
                        await session.execute(
                            update(OperatorConversationModel)
                            .where(
                                OperatorConversationModel.conversation_id
                                == invocation.conversation_id,
                                OperatorConversationModel.state == "running",
                                OperatorConversationModel.claim_generation
                                == invocation.claim_generation,
                            )
                            .values(state="ready", updated_at=now)
                            .returning(OperatorConversationModel.conversation_id)
                            .execution_options(synchronize_session=False)
                        )
                    ).one_or_none()
                    if conversation is None:
                        raise _ClaimLostError
            except _ClaimLostError:
                return False
        return True

    async def _finalize_retryable_failure(
        self,
        invocation: OperatorProviderInvocation,
        failure: OperatorProviderError,
    ) -> None:
        crossed_effect = exists(
            select(OperatorEffectModel.effect_id).where(
                OperatorEffectModel.invocation_id == invocation.invocation_id,
                OperatorEffectModel.state.in_(_CROSSED_EFFECT_STATES),
            )
        )
        now = utc_now()
        async with self._session_factory() as session:
            try:
                async with session.begin():
                    stored = (
                        await session.execute(
                            update(OperatorInvocationModel)
                            .where(
                                OperatorInvocationModel.invocation_id == invocation.invocation_id,
                                OperatorInvocationModel.conversation_id
                                == invocation.conversation_id,
                                OperatorInvocationModel.claim_generation
                                == invocation.claim_generation,
                                OperatorInvocationModel.state == "running",
                                ~crossed_effect,
                            )
                            .values(
                                state="failed",
                                failure_problem=failure.problem,
                                is_retry_safe=failure.is_retry_safe,
                                ended_at=now,
                            )
                            .returning(OperatorInvocationModel.input_entry_id)
                            .execution_options(synchronize_session=False)
                        )
                    ).one_or_none()
                    if stored is None:
                        return
                    conversation = (
                        await session.execute(
                            update(OperatorConversationModel)
                            .where(
                                OperatorConversationModel.conversation_id
                                == invocation.conversation_id,
                                OperatorConversationModel.state == "running",
                                OperatorConversationModel.claim_generation
                                == invocation.claim_generation,
                            )
                            .values(
                                state="failed",
                                next_entry_sequence=(
                                    OperatorConversationModel.next_entry_sequence + 1
                                ),
                                updated_at=now,
                            )
                            .returning(OperatorConversationModel.next_entry_sequence)
                            .execution_options(synchronize_session=False)
                        )
                    ).one_or_none()
                    if conversation is None:
                        raise _ClaimLostError
                    session.add(
                        create_operator_entry_at_sequence(
                            conversation_id=invocation.conversation_id,
                            sequence=conversation.next_entry_sequence - 1,
                            kind="recoverable_error",
                            body=build_provider_failure_body(
                                invocation.conversation_id,
                                problem=failure.problem,
                                explanation=failure.explanation,
                                is_thread_lost=False,
                            ),
                            causal_entry_id=stored.input_entry_id,
                        )
                    )
            except _ClaimLostError:
                return

    async def recover_provider_startup(self) -> tuple[str, ...]:
        crossed_invocations = await self._effects.recover_executing_effects()
        async with self._session_factory() as session:
            async with session.begin():
                running = tuple(
                    (
                        await session.scalars(
                            select(OperatorInvocationModel).where(
                                OperatorInvocationModel.state == "running"
                            )
                        )
                    ).all()
                )
                for invocation in running:
                    await self._recover_running(
                        session,
                        invocation,
                        crossed_effect_boundary=(invocation.invocation_id in crossed_invocations),
                    )
                queued = tuple(
                    (
                        await session.scalars(
                            select(OperatorInvocationModel.invocation_id)
                            .where(OperatorInvocationModel.state == "queued")
                            .order_by(OperatorInvocationModel.created_at)
                        )
                    ).all()
                )
            return queued

    async def _recover_running(
        self,
        session: AsyncSession,
        invocation: OperatorInvocationModel,
        *,
        crossed_effect_boundary: bool,
    ) -> None:
        conversation = await session.get(
            OperatorConversationModel,
            invocation.conversation_id,
            with_for_update=True,
        )
        if conversation is None:
            return
        if crossed_effect_boundary:
            invocation.state = "failed"
            invocation.failure_problem = "effect_boundary_crossed"
            invocation.is_retry_safe = False
            invocation.ended_at = utc_now()
            conversation.state = "ready"
            conversation.updated_at = utc_now()
            return
        entry = create_operator_entry(
            conversation,
            kind="recoverable_error",
            body=build_provider_failure_body(
                conversation.conversation_id,
                problem="interrupted",
                explanation="The interrupted provider turn is safe to retry.",
                is_thread_lost=False,
            ),
            causal_entry_id=invocation.input_entry_id,
        )
        session.add(entry)
        invocation.state = "failed"
        invocation.failure_problem = "interrupted"
        invocation.is_retry_safe = True
        invocation.ended_at = utc_now()
        conversation.state = "failed"
        conversation.updated_at = utc_now()


class _ThreadContinuityLostError(Exception):
    pass


class _ClaimLostError(Exception):
    pass


def _provider_result_entry(
    outcome: OperatorProviderOutcome,
) -> tuple[str, dict[str, object], str]:
    if isinstance(outcome.result, OperatorProviderMessageResult):
        return "assistant_message", {"text": outcome.result.text}, "ready"
    if isinstance(outcome.result, OperatorProviderAskUserResult):
        return (
            "question_set",
            {
                "explanation": outcome.result.explanation,
                "questions": [
                    {
                        "id": allocate_operator_id("question"),
                        "header": question.header,
                        "question": question.question,
                        "allow_skip": question.is_skip_allowed,
                        "options": [
                            {
                                "id": allocate_operator_id("option"),
                                "label": option.label,
                                "consequence": option.consequence,
                            }
                            for option in question.options
                        ],
                    }
                    for question in outcome.result.questions
                ],
            },
            "awaiting_answer",
        )
    raise RuntimeError("provider returned an unsupported Operator result")


__all__ = ["OperatorInvocationService"]
