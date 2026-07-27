from __future__ import annotations

import base64
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.contracts import (
    OperatorAnswerQuestionSetAction,
    OperatorAssistantMessageEntry,
    OperatorAssistantQuestionSetEntry,
    OperatorConversationAction,
    OperatorConversationEntry,
    OperatorConversationPage,
    OperatorConversationState,
    OperatorConversationSummary,
    OperatorConversationView,
    OperatorCreateNewConversationAction,
    OperatorSendMessageAction,
    OperatorTurnInterruptedEntry,
    OperatorUserMessageEntry,
    OperatorUserQuestionAnswersEntry,
)
from banksia.operator.errors import (
    OperatorConversationNotFoundError,
    OperatorCursorValidationError,
)
from banksia.persistence.models import (
    OperatorConversationEntryModel,
    OperatorConversationModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.product.paths import build_product_api_path

type OperatorSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_CONVERSATION_PREVIEW_MAX_CHARS = 64


async def create_operator_conversation(
    session_factory: OperatorSessionFactory,
    *,
    idempotency_key: str,
    provider: str,
    model: str | None,
    effort: str | None,
) -> OperatorConversationView:
    now = utc_now()
    conversation = OperatorConversationModel(
        conversation_id=f"operator-conversation.{uuid4().hex}",
        provider=provider,
        model=model,
        effort=effort,
        provider_thread_id=None,
        state="ready",
        active_turn_id=None,
        create_idempotency_key=idempotency_key,
        created_at=now,
        updated_at=now,
    )
    async with session_factory() as session:
        try:
            session.add(conversation)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing_id = await session.scalar(
                select(OperatorConversationModel.conversation_id).where(
                    OperatorConversationModel.create_idempotency_key == idempotency_key
                )
            )
            if existing_id is None:
                raise
            conversation_id = existing_id
        else:
            conversation_id = conversation.conversation_id

    return await read_operator_conversation(
        session_factory,
        conversation_id=conversation_id,
    )


async def list_operator_conversations(
    session_factory: OperatorSessionFactory,
    *,
    cursor: str | None,
    limit: int,
) -> OperatorConversationPage:
    statement = select(OperatorConversationModel)
    if cursor is not None:
        cursor_updated_at, cursor_id = _decode_conversation_cursor(cursor)
        statement = statement.where(
            or_(
                OperatorConversationModel.updated_at < cursor_updated_at,
                and_(
                    OperatorConversationModel.updated_at == cursor_updated_at,
                    OperatorConversationModel.conversation_id < cursor_id,
                ),
            )
        )
    statement = statement.order_by(
        OperatorConversationModel.updated_at.desc(),
        OperatorConversationModel.conversation_id.desc(),
    ).limit(limit + 1)

    async with session_factory() as session:
        conversations = list((await session.scalars(statement)).all())
        has_more = len(conversations) > limit
        visible = conversations[:limit]
        previews = await _read_conversation_previews(
            session,
            conversation_ids=tuple(conversation.conversation_id for conversation in visible),
        )

    next_cursor = (
        _encode_conversation_cursor(visible[-1].updated_at, visible[-1].conversation_id)
        if has_more and visible
        else None
    )
    return OperatorConversationPage(
        items=tuple(
            OperatorConversationSummary(
                id=conversation.conversation_id,
                state=cast(OperatorConversationState, conversation.state),
                provider=conversation.provider,
                preview=previews.get(conversation.conversation_id),
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
            for conversation in visible
        ),
        next_cursor=next_cursor,
    )


async def _read_conversation_previews(
    session: AsyncSession,
    *,
    conversation_ids: tuple[str, ...],
) -> dict[str, str]:
    if not conversation_ids:
        return {}

    first_user_messages = (
        select(
            OperatorConversationEntryModel.conversation_id.label("conversation_id"),
            func.min(OperatorConversationEntryModel.sequence).label("sequence"),
        )
        .where(
            OperatorConversationEntryModel.conversation_id.in_(conversation_ids),
            OperatorConversationEntryModel.kind == "user_message",
        )
        .group_by(OperatorConversationEntryModel.conversation_id)
        .subquery()
    )
    statement = select(
        OperatorConversationEntryModel.conversation_id,
        OperatorConversationEntryModel.body_json,
    ).join(
        first_user_messages,
        and_(
            OperatorConversationEntryModel.conversation_id == first_user_messages.c.conversation_id,
            OperatorConversationEntryModel.sequence == first_user_messages.c.sequence,
        ),
    )
    rows = (await session.execute(statement)).all()
    previews: dict[str, str] = {}
    for conversation_id, body in rows:
        preview = _conversation_preview(body)
        if preview is not None:
            previews[conversation_id] = preview
    return previews


def _conversation_preview(body: dict[str, object]) -> str | None:
    text = body.get("text")
    if not isinstance(text, str):
        return None

    normalized = " ".join(text.split())
    if not normalized:
        return None
    if len(normalized) <= _CONVERSATION_PREVIEW_MAX_CHARS:
        return normalized
    return f"{normalized[: _CONVERSATION_PREVIEW_MAX_CHARS - 1].rstrip()}…"


async def read_operator_conversation(
    session_factory: OperatorSessionFactory,
    *,
    conversation_id: str,
    cursor: str | None = None,
    limit: int = 100,
) -> OperatorConversationView:
    before_sequence = _decode_entry_cursor(cursor) if cursor is not None else None
    async with session_factory() as session:
        async with session.begin():
            conversation = await session.scalar(
                select(OperatorConversationModel)
                .where(OperatorConversationModel.conversation_id == conversation_id)
                .with_for_update(read=True)
            )
            if conversation is None:
                raise OperatorConversationNotFoundError(conversation_id)
            return await _read_conversation_view(
                session,
                conversation=conversation,
                before_sequence=before_sequence,
                limit=limit,
            )


async def read_operator_conversation_by_create_idempotency_key(
    session_factory: OperatorSessionFactory,
    *,
    idempotency_key: str,
) -> OperatorConversationView | None:
    async with session_factory() as session:
        async with session.begin():
            conversation = await session.scalar(
                select(OperatorConversationModel)
                .where(OperatorConversationModel.create_idempotency_key == idempotency_key)
                .with_for_update(read=True)
            )
            if conversation is None:
                return None
            return await _read_conversation_view(
                session,
                conversation=conversation,
                before_sequence=None,
                limit=100,
            )


def map_entry(entry: OperatorConversationEntryModel) -> OperatorConversationEntry:
    body = entry.body_json
    common = {
        "id": entry.entry_id,
        "kind": entry.kind,
        "created_at": entry.created_at,
    }
    if entry.kind == "user_message":
        return OperatorUserMessageEntry.model_validate({**common, "text": body.get("text")})
    if entry.kind == "user_question_answers":
        return OperatorUserQuestionAnswersEntry.model_validate(
            {
                **common,
                "question_set_id": body.get("question_set_id"),
                "answers": body.get("answers"),
            }
        )
    if entry.kind == "assistant_message":
        return OperatorAssistantMessageEntry.model_validate({**common, "text": body.get("text")})
    if entry.kind == "assistant_question_set":
        return OperatorAssistantQuestionSetEntry.model_validate(
            {
                **common,
                "explanation": body.get("explanation"),
                "questions": body.get("questions"),
            }
        )
    if entry.kind == "turn_interrupted":
        return OperatorTurnInterruptedEntry.model_validate(
            {
                **common,
                "explanation": body.get("explanation"),
                "next_step": body.get("next_step"),
            }
        )
    raise RuntimeError(f"unknown stored Operator entry kind: {entry.kind}")


async def _read_conversation_view(
    session: AsyncSession,
    *,
    conversation: OperatorConversationModel,
    before_sequence: int | None,
    limit: int,
) -> OperatorConversationView:
    entries, older_cursor = await _read_entry_page(
        session,
        conversation_id=conversation.conversation_id,
        before_sequence=before_sequence,
        limit=limit,
    )
    current_question_set_id = await _read_current_question_set_id(
        session,
        conversation_id=conversation.conversation_id,
    )
    return _build_conversation_view(
        conversation,
        entries=entries,
        older_cursor=older_cursor,
        current_question_set_id=current_question_set_id,
    )


def _encode_conversation_cursor(updated_at: datetime, conversation_id: str) -> str:
    return _encode_cursor(
        {
            "updated_at": updated_at.isoformat(),
            "conversation_id": conversation_id,
        }
    )


def _decode_conversation_cursor(cursor: str) -> tuple[datetime, str]:
    payload = _decode_cursor(cursor)
    try:
        updated_at = datetime.fromisoformat(cast(str, payload["updated_at"]))
        conversation_id = cast(str, payload["conversation_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OperatorCursorValidationError("invalid Operator conversation cursor") from exc
    if updated_at.tzinfo is None or not conversation_id:
        raise OperatorCursorValidationError("invalid Operator conversation cursor")
    return updated_at, conversation_id


def _encode_entry_cursor(sequence: int) -> str:
    return _encode_cursor({"before_sequence": sequence})


def _decode_entry_cursor(cursor: str) -> int:
    payload = _decode_cursor(cursor)
    sequence = payload.get("before_sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise OperatorCursorValidationError("invalid Operator entry cursor")
    return sequence


def _encode_cursor(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(serialized).decode().rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, object]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise OperatorCursorValidationError("invalid Operator cursor") from exc
    if not isinstance(payload, dict):
        raise OperatorCursorValidationError("invalid Operator cursor")
    return cast(dict[str, object], payload)


async def _read_entry_page(
    session: AsyncSession,
    *,
    conversation_id: str,
    before_sequence: int | None,
    limit: int,
) -> tuple[tuple[OperatorConversationEntry, ...], str | None]:
    statement: Select[tuple[OperatorConversationEntryModel]] = select(
        OperatorConversationEntryModel
    ).where(OperatorConversationEntryModel.conversation_id == conversation_id)
    if before_sequence is not None:
        statement = statement.where(OperatorConversationEntryModel.sequence < before_sequence)
    statement = statement.order_by(OperatorConversationEntryModel.sequence.desc()).limit(limit + 1)
    stored_entries = list((await session.scalars(statement)).all())
    has_older = len(stored_entries) > limit
    visible_descending = stored_entries[:limit]
    visible = tuple(map_entry(entry) for entry in reversed(visible_descending))
    older_cursor = (
        _encode_entry_cursor(visible_descending[-1].sequence)
        if has_older and visible_descending
        else None
    )
    return visible, older_cursor


async def _read_current_question_set_id(
    session: AsyncSession,
    *,
    conversation_id: str,
) -> str | None:
    return cast(
        str | None,
        await session.scalar(
            select(OperatorConversationEntryModel.entry_id)
            .where(
                OperatorConversationEntryModel.conversation_id == conversation_id,
                OperatorConversationEntryModel.kind == "assistant_question_set",
            )
            .order_by(OperatorConversationEntryModel.sequence.desc())
            .limit(1)
        ),
    )


def _build_conversation_view(
    conversation: OperatorConversationModel,
    *,
    entries: tuple[OperatorConversationEntry, ...],
    older_cursor: str | None,
    current_question_set_id: str | None,
) -> OperatorConversationView:
    state = cast(OperatorConversationState, conversation.state)
    actions: tuple[OperatorConversationAction, ...] = ()
    conversation_path = f"/operator/conversations/{conversation.conversation_id}"
    if state in {"ready", "interrupted"}:
        actions = (
            OperatorSendMessageAction(href=build_product_api_path(f"{conversation_path}/messages")),
        )
    elif state == "awaiting_answer" and current_question_set_id is not None:
        actions = (
            OperatorAnswerQuestionSetAction(
                href=build_product_api_path(
                    f"{conversation_path}/question-sets/{current_question_set_id}/answers"
                ),
                question_set_id=current_question_set_id,
            ),
        )
    elif state == "closed":
        actions = (
            OperatorCreateNewConversationAction(
                href=build_product_api_path("/operator/conversations")
            ),
        )

    return OperatorConversationView(
        id=conversation.conversation_id,
        state=state,
        provider=conversation.provider,
        model=conversation.model,
        effort=conversation.effort,
        entries=entries,
        older_cursor=older_cursor,
        actions=actions,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


__all__ = [
    "OperatorSessionFactory",
    "create_operator_conversation",
    "list_operator_conversations",
    "map_entry",
    "read_operator_conversation",
    "read_operator_conversation_by_create_idempotency_key",
]
