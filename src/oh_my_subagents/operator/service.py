from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from oh_my_subagents.operator.contracts import (
    OperatorConversationPage,
    OperatorConversationView,
    OperatorMessageRequest,
    OperatorQuestionAnswersRequest,
    OperatorStatusResponse,
)
from oh_my_subagents.operator.conversation_reads import (
    OperatorSessionFactory,
    create_operator_conversation,
    list_operator_conversations,
    read_operator_conversation,
    read_operator_conversation_by_create_idempotency_key,
)
from oh_my_subagents.operator.duplicate_wait import wait_for_active_duplicate
from oh_my_subagents.operator.errors import (
    OperatorIdempotencyKeyValidationError,
    OperatorUnavailableError,
)
from oh_my_subagents.operator.persistence import (
    OperatorTurnClaim,
    claim_operator_answer_turn,
    claim_operator_message_turn,
    complete_operator_turn,
    interrupt_operator_turn,
    repair_stranded_operator_turns,
)
from oh_my_subagents.operator.provider import (
    OperatorProviderThreadUnavailableError,
    OperatorTurnOutcome,
    OperatorTurnRunner,
)

MAX_IDEMPOTENCY_KEY_CHARACTERS = 200
_TaskResult = TypeVar("_TaskResult")


class OperatorConversationService:
    """Own the two-record synchronous Operator conversation boundary."""

    def __init__(
        self,
        *,
        session_factory: OperatorSessionFactory,
        runner: OperatorTurnRunner,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner

    def read_status(self) -> OperatorStatusResponse:
        status = self._runner.status
        return OperatorStatusResponse(
            availability=status.availability,
            configured_provider=status.configured_provider,
            explanation=status.explanation,
            setup_action=status.setup_action,
        )

    async def create_conversation(
        self,
        *,
        idempotency_key: str,
    ) -> OperatorConversationView:
        normalized_key = normalize_idempotency_key(idempotency_key)
        existing = await read_operator_conversation_by_create_idempotency_key(
            self._session_factory,
            idempotency_key=normalized_key,
        )
        if existing is not None:
            return existing
        status = self._runner.status
        if status.availability != "available" or status.configured_provider is None:
            raise OperatorUnavailableError(status.explanation)
        return await create_operator_conversation(
            self._session_factory,
            idempotency_key=normalized_key,
            provider=status.configured_provider,
            model=status.model,
            effort=status.effort,
        )

    async def list_conversations(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> OperatorConversationPage:
        return await list_operator_conversations(
            self._session_factory,
            cursor=cursor,
            limit=limit,
        )

    async def read_conversation(
        self,
        conversation_id: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> OperatorConversationView:
        return await read_operator_conversation(
            self._session_factory,
            conversation_id=conversation_id,
            cursor=cursor,
            limit=limit,
        )

    async def submit_message(
        self,
        conversation_id: str,
        request: OperatorMessageRequest,
        *,
        idempotency_key: str,
    ) -> OperatorConversationView:
        return await self._admit_and_run(
            claim_operator_message_turn(
                self._session_factory,
                conversation_id=conversation_id,
                request=request,
                idempotency_key=normalize_idempotency_key(idempotency_key),
            )
        )

    async def submit_question_answers(
        self,
        conversation_id: str,
        question_set_id: str,
        request: OperatorQuestionAnswersRequest,
        *,
        idempotency_key: str,
    ) -> OperatorConversationView:
        return await self._admit_and_run(
            claim_operator_answer_turn(
                self._session_factory,
                conversation_id=conversation_id,
                question_set_id=question_set_id,
                request=request,
                idempotency_key=normalize_idempotency_key(idempotency_key),
            )
        )

    async def repair_stranded_turns(self) -> int:
        return await repair_stranded_operator_turns(self._session_factory)

    async def _admit_and_run(
        self,
        admission: Coroutine[Any, Any, OperatorTurnClaim],
    ) -> OperatorConversationView:
        admission_task = asyncio.create_task(admission)
        try:
            claim = await asyncio.shield(admission_task)
        except asyncio.CancelledError as cancellation:
            admitted_claim = await _drain_task(admission_task)
            if admitted_claim is not None and not admitted_claim.is_duplicate:
                await self._interrupt_during_cancellation(
                    admitted_claim,
                    diagnostic_category="admission_cancelled",
                )
            raise cancellation
        return await self._run_claimed_turn(claim)

    async def _run_claimed_turn(
        self,
        claim: OperatorTurnClaim,
    ) -> OperatorConversationView:
        if claim.is_duplicate:
            await wait_for_active_duplicate(
                self._session_factory,
                claim=claim,
            )
            return await self.read_conversation(claim.conversation_id)
        if claim.request is None:
            raise RuntimeError("a claimed Operator turn is missing its provider request")

        try:
            outcome = await self._runner.execute_turn(claim.request)
        except asyncio.CancelledError as cancellation:
            await self._interrupt_during_cancellation(
                claim,
                diagnostic_category="turn_cancelled",
            )
            raise cancellation
        except OperatorProviderThreadUnavailableError:
            await interrupt_operator_turn(
                self._session_factory,
                claim=claim,
                is_thread_unavailable=True,
                diagnostic_category="provider_thread_unavailable",
            )
            return await self.read_conversation(claim.conversation_id)
        except Exception:
            await interrupt_operator_turn(
                self._session_factory,
                claim=claim,
                is_thread_unavailable=False,
                diagnostic_category="provider_failure",
            )
            return await self.read_conversation(claim.conversation_id)

        try:
            validate_provider_thread_continuity(claim, outcome)
        except Exception:
            await interrupt_operator_turn(
                self._session_factory,
                claim=claim,
                is_thread_unavailable=False,
                diagnostic_category="thread_identity_changed",
            )
            return await self.read_conversation(claim.conversation_id)

        try:
            await complete_operator_turn(
                self._session_factory,
                claim=claim,
                outcome=outcome,
            )
        except asyncio.CancelledError as cancellation:
            await self._interrupt_during_cancellation(
                claim,
                diagnostic_category="completion_cancelled",
                provider_thread_id=outcome.provider_thread_id,
            )
            raise cancellation
        except Exception:
            await interrupt_operator_turn(
                self._session_factory,
                claim=claim,
                is_thread_unavailable=False,
                diagnostic_category="completion_failed",
                provider_thread_id=outcome.provider_thread_id,
            )

        return await self.read_conversation(claim.conversation_id)

    async def _interrupt_during_cancellation(
        self,
        claim: OperatorTurnClaim,
        *,
        diagnostic_category: str,
        provider_thread_id: str | None = None,
    ) -> None:
        cleanup_task = asyncio.create_task(
            interrupt_operator_turn(
                self._session_factory,
                claim=claim,
                is_thread_unavailable=False,
                diagnostic_category=diagnostic_category,
                provider_thread_id=provider_thread_id,
            )
        )
        await _drain_task(cleanup_task)


def normalize_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise OperatorIdempotencyKeyValidationError("Idempotency-Key must not be blank")
    if len(normalized) > MAX_IDEMPOTENCY_KEY_CHARACTERS:
        raise OperatorIdempotencyKeyValidationError("Idempotency-Key exceeds the controller limit")
    return normalized


def validate_provider_thread_continuity(
    claim: OperatorTurnClaim,
    outcome: OperatorTurnOutcome,
) -> None:
    if claim.request is None:
        raise RuntimeError("a claimed Operator turn is missing its provider request")
    current_thread_id = claim.request.provider_thread_id
    if current_thread_id is not None and outcome.provider_thread_id != current_thread_id:
        raise RuntimeError("the Operator provider changed its opaque thread identity")


async def _drain_task(task: asyncio.Task[_TaskResult]) -> _TaskResult | None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    try:
        return task.result()
    except BaseException:
        return None


__all__ = [
    "MAX_IDEMPOTENCY_KEY_CHARACTERS",
    "OperatorConversationService",
    "normalize_idempotency_key",
    "validate_provider_thread_continuity",
]
