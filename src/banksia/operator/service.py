from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import desc, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from banksia.config import Settings
from banksia.operator.answers import validate_and_render_answers
from banksia.operator.contention import (
    OPERATOR_PERSISTENCE_ATTEMPTS,
    is_recognized_persistence_contention,
)
from banksia.operator.contracts import (
    OperatorConversationPage,
    OperatorConversationView,
    OperatorMessageRequest,
    OperatorQuestionAnswersRequest,
    OperatorStatusResponse,
)
from banksia.operator.effects import OperatorEffectService
from banksia.operator.errors import (
    action_not_current,
    idempotency_conflict,
    provider_unavailable,
    question_set_not_found,
)
from banksia.operator.invocations import OperatorInvocationService
from banksia.operator.operations import (
    BanksiaOperatorProductOperations,
    OperatorOperationExecutor,
)
from banksia.operator.provider import (
    OperatorInvocationCoordinator,
    OperatorProviderAvailability,
    OperatorProviderRunner,
    UnavailableOperatorProviderRunner,
)
from banksia.operator.retries import (
    OperatorRetryClaimLostError,
    store_operator_retry_invocation,
)
from banksia.operator.storage import (
    OperatorConversationReader,
    OperatorSessionFactory,
    allocate_operator_id,
    create_operator_entry_at_sequence,
    digest_operator_request,
    model_payload,
)
from banksia.persistence.models import (
    OperatorConversationEntryModel,
    OperatorConversationModel,
    OperatorInvocationModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import RuntimeEffectPublisher


@dataclass(frozen=True, slots=True)
class OperatorServices:
    conversations: OperatorConversationService
    coordinator: OperatorInvocationCoordinator
    invocations: OperatorInvocationService
    operations: OperatorOperationExecutor


class OperatorConversationService:
    def __init__(
        self,
        *,
        session_factory: OperatorSessionFactory,
        reader: OperatorConversationReader,
        coordinator: OperatorInvocationCoordinator,
        effects: OperatorEffectService,
    ) -> None:
        self._session_factory = session_factory
        self._reader = reader
        self._coordinator = coordinator
        self._effects = effects

    async def read_status(self) -> OperatorStatusResponse:
        availability = self._coordinator.availability
        return OperatorStatusResponse(
            availability=availability.availability,
            configured_provider=availability.configured_provider,
            problem_code=availability.problem_code,
            explanation=availability.explanation,
            setup_action=availability.setup_action,
        )

    async def list_conversations(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> OperatorConversationPage:
        return await self._reader.list_conversations(cursor=cursor, limit=limit)

    async def read_conversation(
        self,
        conversation_id: str,
        *,
        before_entry: str | None = None,
        limit: int = 50,
    ) -> OperatorConversationView:
        return await self._reader.read_view(
            conversation_id,
            before_entry=before_entry,
            limit=limit,
        )

    async def create_conversation(
        self,
        *,
        idempotency_key: str,
    ) -> OperatorConversationView:
        digest = digest_operator_request("operator_conversation_create", "operator", {})
        replay = await self._find_create_replay(idempotency_key, digest)
        if replay is not None:
            return replay
        availability = self._require_available()
        if availability.configured_provider is None:
            raise provider_unavailable(
                availability.availability,
                availability.explanation,
            )
        conversation_id = allocate_operator_id("conversation")
        async with self._session_factory() as session:
            session.add(
                OperatorConversationModel(
                    conversation_id=conversation_id,
                    create_idempotency_key=idempotency_key,
                    create_request_digest=digest,
                    configured_provider=availability.configured_provider,
                    resolved_model=availability.resolved_model,
                    resolved_effort=availability.resolved_effort,
                    state="ready",
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                replay = await self._find_create_replay(idempotency_key, digest)
                if replay is None:
                    raise
                return replay
        return await self._reader.read_view(conversation_id)

    async def submit_message(
        self,
        *,
        conversation_id: str,
        request: OperatorMessageRequest,
        idempotency_key: str,
    ) -> OperatorConversationView:
        body = model_payload(request)
        digest = digest_operator_request("message", conversation_id, body)
        replay = await self._find_entry_replay(
            conversation_id,
            operation="message",
            owner_id=conversation_id,
            idempotency_key=idempotency_key,
            digest=digest,
        )
        if replay is not None:
            return replay
        self._require_available()
        invocation_id = allocate_operator_id("invocation")
        is_committed = await self._commit_input_invocation(
            conversation_id=conversation_id,
            expected_state="ready",
            entry_kind="user_message",
            entry_body=body,
            request_operation="message",
            request_owner_id=conversation_id,
            idempotency_key=idempotency_key,
            digest=digest,
            provider_input=request.text,
            invocation_id=invocation_id,
        )
        if is_committed:
            await self._coordinator.publish(invocation_id)
        return await self._reader.read_view(conversation_id)

    async def answer_question_set(
        self,
        *,
        conversation_id: str,
        question_set_id: str,
        request: OperatorQuestionAnswersRequest,
        idempotency_key: str,
    ) -> OperatorConversationView:
        body = model_payload(request)
        digest = digest_operator_request(
            "answer",
            f"{conversation_id}:{question_set_id}",
            body,
        )
        replay = await self._find_entry_replay(
            conversation_id,
            operation="answer",
            owner_id=question_set_id,
            idempotency_key=idempotency_key,
            digest=digest,
        )
        if replay is not None:
            return replay
        self._require_available()
        question_entry = await self._read_question_set(
            conversation_id,
            question_set_id,
        )
        provider_input = validate_and_render_answers(question_entry, request)
        invocation_id = allocate_operator_id("invocation")
        is_committed = await self._commit_input_invocation(
            conversation_id=conversation_id,
            expected_state="awaiting_answer",
            entry_kind="question_answer",
            entry_body={"question_set_id": question_set_id, **body},
            request_operation="answer",
            request_owner_id=question_set_id,
            idempotency_key=idempotency_key,
            digest=digest,
            provider_input=provider_input,
            invocation_id=invocation_id,
            causal_entry_id=question_set_id,
            answered_question_set_id=question_set_id,
        )
        if is_committed:
            await self._coordinator.publish(invocation_id)
        return await self._reader.read_view(conversation_id)

    async def retry_provider_invocation(
        self,
        *,
        conversation_id: str,
        idempotency_key: str,
    ) -> OperatorConversationView:
        digest = digest_operator_request("retry", conversation_id, {})
        replay = await self._find_retry_replay(
            conversation_id,
            idempotency_key,
            digest,
        )
        if replay is not None:
            return replay
        self._require_available()
        invocation_id = allocate_operator_id("invocation")
        for attempt in range(OPERATOR_PERSISTENCE_ATTEMPTS):
            try:
                is_committed = await store_operator_retry_invocation(
                    self._session_factory,
                    conversation_id=conversation_id,
                    invocation_id=invocation_id,
                    idempotency_key=idempotency_key,
                    digest=digest,
                )
                break
            except IntegrityError:
                is_committed = False
                break
            except OperatorRetryClaimLostError:
                is_committed = False
                break
            except OperationalError as exc:
                if not is_recognized_persistence_contention(exc):
                    raise
                if attempt + 1 == OPERATOR_PERSISTENCE_ATTEMPTS:
                    is_committed = False
                    break
                await asyncio.sleep(0)
        else:  # pragma: no cover - bounded loop always breaks or returns
            raise AssertionError("Operator retry persistence loop did not return")
        if is_committed:
            await self._coordinator.publish(invocation_id)
            return await self._reader.read_view(conversation_id)
        replay = await self._find_retry_replay(
            conversation_id,
            idempotency_key,
            digest,
        )
        if replay is not None:
            return replay
        raise action_not_current(await self._reader.read_view(conversation_id)) from None

    async def confirm_effect(
        self,
        *,
        conversation_id: str,
        confirmation_id: str,
        idempotency_key: str,
    ) -> OperatorConversationView:
        return await self._effects.confirm_effect(
            conversation_id=conversation_id,
            confirmation_id=confirmation_id,
            idempotency_key=idempotency_key,
        )

    async def _commit_input_invocation(
        self,
        *,
        conversation_id: str,
        expected_state: str,
        entry_kind: str,
        entry_body: dict[str, object],
        request_operation: str,
        request_owner_id: str,
        idempotency_key: str,
        digest: str,
        provider_input: str,
        invocation_id: str,
        causal_entry_id: str | None = None,
        answered_question_set_id: str | None = None,
    ) -> bool:
        try:
            is_committed = await self._store_input_invocation(
                conversation_id=conversation_id,
                expected_state=expected_state,
                entry_kind=entry_kind,
                entry_body=entry_body,
                request_operation=request_operation,
                request_owner_id=request_owner_id,
                idempotency_key=idempotency_key,
                digest=digest,
                provider_input=provider_input,
                invocation_id=invocation_id,
                causal_entry_id=causal_entry_id,
                answered_question_set_id=answered_question_set_id,
            )
        except IntegrityError:
            is_committed = False
        if is_committed:
            return True
        replay = await self._find_entry_replay(
            conversation_id,
            operation=request_operation,
            owner_id=request_owner_id,
            idempotency_key=idempotency_key,
            digest=digest,
        )
        if replay is not None:
            return False
        raise action_not_current(await self._reader.read_view(conversation_id)) from None

    async def _store_input_invocation(
        self,
        *,
        conversation_id: str,
        expected_state: str,
        entry_kind: str,
        entry_body: dict[str, object],
        request_operation: str,
        request_owner_id: str,
        idempotency_key: str,
        digest: str,
        provider_input: str,
        invocation_id: str,
        causal_entry_id: str | None,
        answered_question_set_id: str | None,
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                claim = (
                    await session.execute(
                        update(OperatorConversationModel)
                        .where(
                            OperatorConversationModel.conversation_id == conversation_id,
                            OperatorConversationModel.state == expected_state,
                        )
                        .values(
                            state="running",
                            claim_generation=(OperatorConversationModel.claim_generation + 1),
                            next_entry_sequence=(OperatorConversationModel.next_entry_sequence + 1),
                            updated_at=utc_now(),
                        )
                        .returning(
                            OperatorConversationModel.claim_generation,
                            OperatorConversationModel.next_entry_sequence,
                        )
                        .execution_options(synchronize_session=False)
                    )
                ).one_or_none()
                if claim is None:
                    return False
                entry = create_operator_entry_at_sequence(
                    conversation_id=conversation_id,
                    sequence=claim.next_entry_sequence - 1,
                    kind=entry_kind,
                    body=entry_body,
                    causal_entry_id=causal_entry_id,
                    answered_question_set_id=answered_question_set_id,
                    request_operation=request_operation,
                    request_owner_id=request_owner_id,
                    idempotency_key=idempotency_key,
                    request_digest=digest,
                )
                session.add(entry)
                session.add(
                    OperatorInvocationModel(
                        invocation_id=invocation_id,
                        conversation_id=conversation_id,
                        input_entry_id=entry.entry_id,
                        state="queued",
                        claim_generation=claim.claim_generation,
                        provider_input=provider_input,
                    )
                )
        return True

    async def _find_create_replay(
        self,
        idempotency_key: str,
        digest: str,
    ) -> OperatorConversationView | None:
        async with self._session_factory() as session:
            conversation = await session.scalar(
                select(OperatorConversationModel).where(
                    OperatorConversationModel.create_idempotency_key == idempotency_key
                )
            )
            if conversation is None:
                return None
            if conversation.create_request_digest != digest:
                raise idempotency_conflict()
            conversation_id = conversation.conversation_id
        return await self._reader.read_view(conversation_id)

    async def _find_entry_replay(
        self,
        conversation_id: str,
        *,
        operation: str,
        owner_id: str,
        idempotency_key: str,
        digest: str,
    ) -> OperatorConversationView | None:
        async with self._session_factory() as session:
            entry = await session.scalar(
                select(OperatorConversationEntryModel).where(
                    OperatorConversationEntryModel.conversation_id == conversation_id,
                    OperatorConversationEntryModel.request_operation == operation,
                    OperatorConversationEntryModel.request_owner_id == owner_id,
                    OperatorConversationEntryModel.request_idempotency_key == idempotency_key,
                )
            )
            if entry is None:
                return None
            if entry.request_digest != digest:
                raise idempotency_conflict()
        return await self._reader.read_view(conversation_id)

    async def _find_retry_replay(
        self,
        conversation_id: str,
        idempotency_key: str,
        digest: str,
    ) -> OperatorConversationView | None:
        async with self._session_factory() as session:
            invocation = await session.scalar(
                select(OperatorInvocationModel).where(
                    OperatorInvocationModel.conversation_id == conversation_id,
                    OperatorInvocationModel.retry_idempotency_key == idempotency_key,
                )
            )
            if invocation is None:
                return None
            if invocation.retry_request_digest != digest:
                raise idempotency_conflict()
        return await self._reader.read_view(conversation_id)

    async def _read_question_set(
        self,
        conversation_id: str,
        question_set_id: str,
    ) -> OperatorConversationEntryModel:
        is_current = False
        async with self._session_factory() as session:
            conversation = await session.get(OperatorConversationModel, conversation_id)
            if conversation is None:
                raise question_set_not_found()
            entry = await session.get(OperatorConversationEntryModel, question_set_id)
            if (
                entry is None
                or entry.conversation_id != conversation_id
                or entry.kind != "question_set"
            ):
                raise question_set_not_found()
            latest = await session.scalar(
                select(OperatorConversationEntryModel)
                .where(
                    OperatorConversationEntryModel.conversation_id == conversation_id,
                    OperatorConversationEntryModel.kind == "question_set",
                )
                .order_by(desc(OperatorConversationEntryModel.sequence))
                .limit(1)
            )
            is_current = (
                conversation.state == "awaiting_answer"
                and latest is not None
                and latest.entry_id == question_set_id
            )
            session.expunge(entry)
        if not is_current:
            raise action_not_current(await self._reader.read_view(conversation_id))
        return entry

    def _require_available(self) -> OperatorProviderAvailability:
        availability = self._coordinator.availability
        if availability.availability != "available":
            raise provider_unavailable(
                availability.availability,
                availability.explanation,
            )
        return availability


def create_operator_services(
    *,
    session_factory: OperatorSessionFactory,
    settings: Settings,
    dispatch_dependencies: DispatchOpeningDependencies,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
    provider_runner: OperatorProviderRunner | None = None,
) -> OperatorServices:
    runner = provider_runner or UnavailableOperatorProviderRunner()
    reader = OperatorConversationReader(session_factory)
    product_operations = BanksiaOperatorProductOperations(
        session_factory=session_factory,
        settings=settings,
        dispatch_dependencies=dispatch_dependencies,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    operations = OperatorOperationExecutor(product_operations)
    reader.bind_proposal_currentness(operations)
    effects = OperatorEffectService(
        session_factory=session_factory,
        reader=reader,
        executor=operations,
    )
    invocations = OperatorInvocationService(
        session_factory=session_factory,
        effects=effects,
    )
    coordinator = OperatorInvocationCoordinator(
        runner=runner,
        operations=operations,
    )
    operations.bind_effect_owner(effects)
    coordinator.bind_owner(invocations)
    conversations = OperatorConversationService(
        session_factory=session_factory,
        reader=reader,
        coordinator=coordinator,
        effects=effects,
    )
    return OperatorServices(
        conversations=conversations,
        coordinator=coordinator,
        invocations=invocations,
        operations=operations,
    )


__all__ = [
    "OperatorConversationService",
    "OperatorServices",
    "create_operator_services",
]
