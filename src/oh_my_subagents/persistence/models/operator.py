from __future__ import annotations

from datetime import UTC, datetime
from functools import partial

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from oh_my_subagents.persistence.base import RuntimeBase
from oh_my_subagents.persistence.datetimes import UtcDateTime

utcnow = partial(datetime.now, tz=UTC)


class OperatorConversationModel(RuntimeBase):
    __tablename__ = "operator_conversations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('ready', 'running', 'awaiting_answer', 'interrupted', 'closed')",
            name="ck_operator_conversations_state",
        ),
        CheckConstraint(
            "(state = 'running' AND active_turn_id IS NOT NULL) OR "
            "(state != 'running' AND active_turn_id IS NULL)",
            name="ck_operator_conversations_active_turn",
        ),
        UniqueConstraint(
            "create_idempotency_key",
            name="uq_operator_conversations_create_idempotency_key",
        ),
        Index(
            "ix_operator_conversations_updated_at_id",
            "updated_at",
            "conversation_id",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effort: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_thread_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(32))
    active_turn_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    create_idempotency_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    entries: Mapped[list[OperatorConversationEntryModel]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="OperatorConversationEntryModel.sequence",
    )


class OperatorConversationEntryModel(RuntimeBase):
    __tablename__ = "operator_conversation_entries"
    __table_args__ = (
        CheckConstraint(
            "sequence >= 1",
            name="ck_operator_conversation_entries_sequence",
        ),
        CheckConstraint(
            "kind IN "
            "('user_message', 'user_question_answers', 'assistant_message', "
            "'assistant_question_set', 'turn_interrupted')",
            name="ck_operator_conversation_entries_kind",
        ),
        CheckConstraint(
            "(kind IN ('user_message', 'user_question_answers') "
            "AND request_idempotency_key IS NOT NULL AND request_digest IS NOT NULL) OR "
            "(kind NOT IN ('user_message', 'user_question_answers') "
            "AND request_idempotency_key IS NULL AND request_digest IS NULL)",
            name="ck_operator_conversation_entries_request_identity",
        ),
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_operator_conversation_entries_order",
        ),
        UniqueConstraint(
            "conversation_id",
            "request_idempotency_key",
            name="uq_operator_conversation_entries_request",
        ),
    )

    entry_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("operator_conversations.conversation_id", ondelete="CASCADE"),
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    body_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    request_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    conversation: Mapped[OperatorConversationModel] = relationship(
        back_populates="entries",
        lazy="raise",
    )


__all__ = [
    "OperatorConversationEntryModel",
    "OperatorConversationModel",
]
