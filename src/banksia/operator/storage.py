from __future__ import annotations

import base64
import json
import secrets
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol, cast

from pydantic import BaseModel, ValidationError
from sqlalchemy import Select, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.contracts import (
    OPERATOR_ENTRY_ADAPTER,
    OperatorAnswerQuestionSetAction,
    OperatorConfirmEffectAction,
    OperatorConversationEntry,
    OperatorConversationPage,
    OperatorConversationState,
    OperatorConversationSummary,
    OperatorConversationView,
    OperatorCreateNewConversationAction,
    OperatorEmptyInput,
    OperatorLegalAction,
    OperatorMessageTextInput,
    OperatorQuestionAnswersInput,
    OperatorRetryProviderInvocationAction,
    OperatorSendMessageAction,
)
from banksia.operator.errors import conversation_not_found
from banksia.persistence.models import (
    OperatorConversationEntryModel,
    OperatorConversationModel,
    OperatorEffectModel,
    OperatorInvocationModel,
)
from banksia.runtime.clock import utc_now

type OperatorSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class OperatorProposalCurrentness(Protocol):
    async def is_stored_proposal_current(
        self,
        operation_name: str,
        payload: object,
        guard: str | None,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class _StoredOperatorProposal:
    effect_id: str
    operation: str
    request_payload: dict[str, object]
    guard: str | None


class OperatorConversationReader:
    def __init__(self, session_factory: OperatorSessionFactory) -> None:
        self._session_factory = session_factory
        self._proposal_currentness: OperatorProposalCurrentness | None = None

    def bind_proposal_currentness(
        self,
        currentness: OperatorProposalCurrentness,
    ) -> None:
        if self._proposal_currentness is not None and self._proposal_currentness is not currentness:
            raise RuntimeError("Operator proposal currentness owner is already bound")
        self._proposal_currentness = currentness

    async def list_conversations(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> OperatorConversationPage:
        cursor_value = decode_conversation_cursor(cursor) if cursor is not None else None
        async with self._session_factory() as session:
            statement = select(OperatorConversationModel).order_by(
                desc(OperatorConversationModel.updated_at),
                desc(OperatorConversationModel.conversation_id),
            )
            if cursor_value is not None:
                updated_at, conversation_id = cursor_value
                statement = statement.where(
                    (OperatorConversationModel.updated_at < updated_at)
                    | (
                        (OperatorConversationModel.updated_at == updated_at)
                        & (OperatorConversationModel.conversation_id < conversation_id)
                    )
                )
            conversations = tuple((await session.scalars(statement.limit(limit + 1))).all())
            visible = conversations[:limit]
            items = tuple([await self._summary(session, conversation) for conversation in visible])
        next_cursor = (
            encode_conversation_cursor(visible[-1]) if len(conversations) > limit else None
        )
        return OperatorConversationPage(items=items, next_cursor=next_cursor)

    async def read_view(
        self,
        conversation_id: str,
        *,
        before_entry: str | None = None,
        limit: int = 50,
    ) -> OperatorConversationView:
        async with self._session_factory() as session:
            view, proposals = await self._read_view_snapshot(
                session,
                conversation_id,
                before_entry=before_entry,
                limit=limit,
            )
        stale_effect_ids = await self._find_stale_effect_ids(proposals)
        if not stale_effect_ids:
            return view
        await self._expire_stale_proposals(stale_effect_ids)
        async with self._session_factory() as session:
            current, _proposals = await self._read_view_snapshot(
                session,
                conversation_id,
                before_entry=before_entry,
                limit=limit,
            )
        return current

    async def _read_view_snapshot(
        self,
        session: AsyncSession,
        conversation_id: str,
        *,
        before_entry: str | None,
        limit: int,
    ) -> tuple[OperatorConversationView, tuple[_StoredOperatorProposal, ...]]:
        conversation = await session.get(OperatorConversationModel, conversation_id)
        if conversation is None:
            raise conversation_not_found()
        entries, older_cursor = await self._read_entries(
            session,
            conversation_id,
            before_entry=before_entry,
            limit=limit,
        )
        actions, proposals = await self._read_actions(session, conversation)
        return (
            OperatorConversationView(
                id=conversation.conversation_id,
                state=cast(OperatorConversationState, conversation.state),
                configured_provider=conversation.configured_provider,
                entries=entries,
                older_cursor=older_cursor,
                legal_actions=actions,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            ),
            proposals,
        )

    async def _read_entries(
        self,
        session: AsyncSession,
        conversation_id: str,
        *,
        before_entry: str | None,
        limit: int,
    ) -> tuple[tuple[OperatorConversationEntry, ...], str | None]:
        statement: Select[tuple[OperatorConversationEntryModel]] = select(
            OperatorConversationEntryModel
        ).where(OperatorConversationEntryModel.conversation_id == conversation_id)
        if before_entry is not None:
            before = await session.get(OperatorConversationEntryModel, before_entry)
            if before is None or before.conversation_id != conversation_id:
                raise ValueError("before_entry is not part of this conversation")
            statement = statement.where(OperatorConversationEntryModel.sequence < before.sequence)
        rows = tuple(
            (
                await session.scalars(
                    statement.order_by(desc(OperatorConversationEntryModel.sequence)).limit(
                        limit + 1
                    )
                )
            ).all()
        )
        visible = rows[:limit]
        parsed = tuple(parse_operator_entry(row) for row in reversed(visible))
        older_cursor = visible[-1].entry_id if len(rows) > limit else None
        return parsed, older_cursor

    async def _read_actions(
        self,
        session: AsyncSession,
        conversation: OperatorConversationModel,
    ) -> tuple[tuple[OperatorLegalAction, ...], tuple[_StoredOperatorProposal, ...]]:
        base = f"/api/operator/conversations/{conversation.conversation_id}"
        if conversation.state == "running":
            return (), ()
        if conversation.state == "provider_thread_lost":
            return (_create_new_conversation_action(),), ()
        if conversation.state == "awaiting_answer":
            return await self._read_answer_action(session, conversation, base), ()
        if conversation.state == "failed":
            return await self._read_retry_action(session, conversation, base), ()
        return await self._read_ready_actions(session, conversation, base)

    async def _read_answer_action(
        self,
        session: AsyncSession,
        conversation: OperatorConversationModel,
        base: str,
    ) -> tuple[OperatorLegalAction, ...]:
        question = await session.scalar(
            select(OperatorConversationEntryModel)
            .where(
                OperatorConversationEntryModel.conversation_id == conversation.conversation_id,
                OperatorConversationEntryModel.kind == "question_set",
            )
            .order_by(desc(OperatorConversationEntryModel.sequence))
            .limit(1)
        )
        if question is None:
            return ()
        return (
            OperatorAnswerQuestionSetAction(
                kind="answer_question_set",
                label="Continue",
                href=f"{base}/question-sets/{question.entry_id}/answers",
                input=OperatorQuestionAnswersInput(question_set_id=question.entry_id),
                question_set_id=question.entry_id,
            ),
        )

    async def _read_retry_action(
        self,
        session: AsyncSession,
        conversation: OperatorConversationModel,
        base: str,
    ) -> tuple[OperatorLegalAction, ...]:
        latest = await session.scalar(
            select(OperatorInvocationModel)
            .where(OperatorInvocationModel.conversation_id == conversation.conversation_id)
            .order_by(desc(OperatorInvocationModel.created_at))
            .limit(1)
        )
        if latest is None or not latest.is_retry_safe:
            return ()
        return (
            OperatorRetryProviderInvocationAction(
                kind="retry_provider_invocation",
                label="Retry",
                href=f"{base}/retries",
                input=OperatorEmptyInput(),
            ),
        )

    async def _read_ready_actions(
        self,
        session: AsyncSession,
        conversation: OperatorConversationModel,
        base: str,
    ) -> tuple[tuple[OperatorLegalAction, ...], tuple[_StoredOperatorProposal, ...]]:
        proposals = tuple(
            (
                await session.scalars(
                    select(OperatorEffectModel)
                    .where(
                        OperatorEffectModel.conversation_id == conversation.conversation_id,
                        OperatorEffectModel.state == "proposed",
                        OperatorEffectModel.confirmation_state == "available",
                    )
                    .order_by(OperatorEffectModel.created_at)
                )
            ).all()
        )
        return (
            (
                OperatorSendMessageAction(
                    kind="send_message",
                    label="Send message",
                    href=f"{base}/messages",
                    input=OperatorMessageTextInput(),
                ),
                *(
                    OperatorConfirmEffectAction(
                        kind="confirm_effect",
                        label=cast(str, effect.result_json["label"]),
                        href=f"{base}/confirmations/{effect.confirmation_id}",
                        consequence=cast(str, effect.result_json["consequence"]),
                        input=OperatorEmptyInput(),
                        confirmation_id=effect.confirmation_id,
                        scope=cast(str, effect.result_json["scope"]),
                    )
                    for effect in proposals
                    if effect.result_json is not None and effect.confirmation_id is not None
                ),
            ),
            tuple(
                _StoredOperatorProposal(
                    effect_id=effect.effect_id,
                    operation=effect.operation,
                    request_payload=effect.request_json,
                    guard=effect.action_guard,
                )
                for effect in proposals
            ),
        )

    async def _find_stale_effect_ids(
        self,
        proposals: tuple[_StoredOperatorProposal, ...],
    ) -> tuple[str, ...]:
        if self._proposal_currentness is None:
            return ()
        stale_effect_ids = []
        for proposal in proposals:
            is_current = await self._proposal_currentness.is_stored_proposal_current(
                proposal.operation,
                proposal.request_payload,
                proposal.guard,
            )
            if not is_current:
                stale_effect_ids.append(proposal.effect_id)
        return tuple(stale_effect_ids)

    async def _expire_stale_proposals(
        self,
        effect_ids: tuple[str, ...],
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(OperatorEffectModel)
                    .where(
                        OperatorEffectModel.effect_id.in_(effect_ids),
                        OperatorEffectModel.state == "proposed",
                        OperatorEffectModel.confirmation_state == "available",
                    )
                    .values(
                        state="failed",
                        confirmation_state="expired",
                        ended_at=utc_now(),
                    )
                    .execution_options(synchronize_session=False)
                )

    async def _summary(
        self,
        session: AsyncSession,
        conversation: OperatorConversationModel,
    ) -> OperatorConversationSummary:
        entry = await session.scalar(
            select(OperatorConversationEntryModel)
            .where(
                OperatorConversationEntryModel.conversation_id == conversation.conversation_id,
                OperatorConversationEntryModel.kind.in_(("user_message", "assistant_message")),
            )
            .order_by(desc(OperatorConversationEntryModel.sequence))
            .limit(1)
        )
        preview = None
        if entry is not None:
            text = entry.body_json.get("text")
            if isinstance(text, str):
                preview = text[:160]
        return OperatorConversationSummary(
            id=conversation.conversation_id,
            state=cast(OperatorConversationState, conversation.state),
            preview=preview,
            configured_provider=conversation.configured_provider,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


def create_operator_entry(
    conversation: OperatorConversationModel,
    *,
    kind: str,
    body: dict[str, object],
    causal_entry_id: str | None = None,
    answered_question_set_id: str | None = None,
    request_operation: str | None = None,
    request_owner_id: str | None = None,
    idempotency_key: str | None = None,
    request_digest: str | None = None,
) -> OperatorConversationEntryModel:
    entry = OperatorConversationEntryModel(
        entry_id=allocate_operator_id("entry"),
        conversation_id=conversation.conversation_id,
        sequence=conversation.next_entry_sequence,
        kind=kind,
        body_json=body,
        causal_entry_id=causal_entry_id,
        answered_question_set_id=answered_question_set_id,
        request_operation=request_operation,
        request_owner_id=request_owner_id,
        request_idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    conversation.next_entry_sequence += 1
    return entry


def create_operator_entry_at_sequence(
    *,
    conversation_id: str,
    sequence: int,
    kind: str,
    body: dict[str, object],
    causal_entry_id: str | None = None,
    answered_question_set_id: str | None = None,
    request_operation: str | None = None,
    request_owner_id: str | None = None,
    idempotency_key: str | None = None,
    request_digest: str | None = None,
) -> OperatorConversationEntryModel:
    return OperatorConversationEntryModel(
        entry_id=allocate_operator_id("entry"),
        conversation_id=conversation_id,
        sequence=sequence,
        kind=kind,
        body_json=body,
        causal_entry_id=causal_entry_id,
        answered_question_set_id=answered_question_set_id,
        request_operation=request_operation,
        request_owner_id=request_owner_id,
        request_idempotency_key=idempotency_key,
        request_digest=request_digest,
    )


def parse_operator_entry(
    entry: OperatorConversationEntryModel,
) -> OperatorConversationEntry:
    try:
        return OPERATOR_ENTRY_ADAPTER.validate_python(
            {
                "id": entry.entry_id,
                "kind": entry.kind,
                **entry.body_json,
                "created_at": entry.created_at,
            }
        )
    except ValidationError as exc:  # pragma: no cover - schema is controller-owned
        raise RuntimeError("stored Operator entry failed its closed contract") from exc


def encode_conversation_cursor(conversation: OperatorConversationModel) -> str:
    payload = json.dumps(
        {
            "updated_at": conversation.updated_at.isoformat(),
            "conversation_id": conversation.conversation_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_conversation_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if not isinstance(payload, dict):
            raise TypeError
        updated_at = datetime.fromisoformat(payload["updated_at"])
        conversation_id = payload["conversation_id"]
        if not isinstance(conversation_id, str):
            raise TypeError
        return updated_at, conversation_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Operator conversation cursor") from exc


def model_payload(value: BaseModel) -> dict[str, object]:
    return cast(dict[str, object], value.model_dump(mode="json"))


def digest_operator_request(
    operation: str,
    owner_id: str,
    payload: object,
) -> str:
    normalized = json.dumps(
        {
            "operation": operation,
            "owner_id": owner_id,
            "body": payload,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(normalized).hexdigest()


def allocate_operator_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(18)}"


def _create_new_conversation_action() -> OperatorCreateNewConversationAction:
    return OperatorCreateNewConversationAction(
        kind="create_new_conversation",
        label="Start a new conversation",
        href="/api/operator/conversations",
        input=OperatorEmptyInput(),
    )


__all__ = [
    "OperatorConversationReader",
    "OperatorSessionFactory",
    "allocate_operator_id",
    "create_operator_entry",
    "create_operator_entry_at_sequence",
    "decode_conversation_cursor",
    "digest_operator_request",
    "encode_conversation_cursor",
    "model_payload",
    "parse_operator_entry",
]
