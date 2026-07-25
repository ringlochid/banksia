from __future__ import annotations

from datetime import UTC, datetime
from functools import partial

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Computed,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime

utcnow = partial(datetime.now, tz=UTC)


class OperatorConversationModel(RuntimeBase):
    __tablename__ = "operator_conversations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('ready', 'running', 'awaiting_answer', 'failed', 'provider_thread_lost')",
            name="ck_operator_conversations_state",
        ),
        CheckConstraint(
            "claim_generation >= 0",
            name="ck_operator_conversations_claim_generation",
        ),
        CheckConstraint(
            "next_entry_sequence >= 1",
            name="ck_operator_conversations_next_entry_sequence",
        ),
        UniqueConstraint(
            "create_idempotency_key",
            name="uq_operator_conversations_create_idempotency_key",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    create_idempotency_key: Mapped[str] = mapped_column(String(200))
    create_request_digest: Mapped[str] = mapped_column(String(64))
    configured_provider: Mapped[str] = mapped_column(String(64))
    resolved_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_effort: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_thread_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(32))
    claim_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_entry_sequence: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
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
    )
    invocations: Mapped[list[OperatorInvocationModel]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    effects: Mapped[list[OperatorEffectModel]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="raise",
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
            "('user_message', 'assistant_message', 'question_set', 'question_answer', "
            "'action_proposal', 'effect_receipt', 'recoverable_error')",
            name="ck_operator_conversation_entries_kind",
        ),
        CheckConstraint(
            "(request_operation IS NULL AND request_owner_id IS NULL "
            "AND request_idempotency_key IS NULL AND request_digest IS NULL) OR "
            "(request_operation IS NOT NULL AND request_owner_id IS NOT NULL "
            "AND request_idempotency_key IS NOT NULL AND request_digest IS NOT NULL)",
            name="ck_operator_conversation_entries_request_identity",
        ),
        CheckConstraint(
            "(kind = 'question_answer' AND answered_question_set_id IS NOT NULL) OR "
            "(kind <> 'question_answer' AND answered_question_set_id IS NULL)",
            name="ck_operator_conversation_entries_answer_owner",
        ),
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_operator_conversation_entries_order",
        ),
        UniqueConstraint(
            "conversation_id",
            "request_operation",
            "request_owner_id",
            "request_idempotency_key",
            name="uq_operator_conversation_entries_request",
        ),
        UniqueConstraint(
            "answered_question_set_id",
            name="uq_operator_conversation_entries_question_answer",
        ),
    )

    entry_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("operator_conversations.conversation_id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    body_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    causal_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("operator_conversation_entries.entry_id"),
        nullable=True,
    )
    answered_question_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("operator_conversation_entries.entry_id"),
        nullable=True,
    )
    request_operation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_owner_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    conversation: Mapped[OperatorConversationModel] = relationship(
        back_populates="entries",
        lazy="raise",
    )
    causal_entry: Mapped[OperatorConversationEntryModel | None] = relationship(
        foreign_keys=[causal_entry_id],
        remote_side=[entry_id],
        lazy="raise",
    )
    answered_question_set: Mapped[OperatorConversationEntryModel | None] = relationship(
        foreign_keys=[answered_question_set_id],
        remote_side=[entry_id],
        lazy="raise",
    )


class OperatorInvocationModel(RuntimeBase):
    __tablename__ = "operator_invocations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'provider_thread_lost')",
            name="ck_operator_invocations_state",
        ),
        CheckConstraint(
            "claim_generation >= 1",
            name="ck_operator_invocations_claim_generation",
        ),
        UniqueConstraint(
            "conversation_id",
            "active_claim_marker",
            name="uq_operator_invocations_one_active",
        ),
        UniqueConstraint(
            "conversation_id",
            "retry_idempotency_key",
            name="uq_operator_invocations_retry_idempotency",
        ),
    )

    invocation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("operator_conversations.conversation_id", ondelete="CASCADE"),
        index=True,
    )
    input_entry_id: Mapped[str] = mapped_column(
        ForeignKey("operator_conversation_entries.entry_id")
    )
    retry_basis_invocation_id: Mapped[str | None] = mapped_column(
        ForeignKey("operator_invocations.invocation_id"),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(String(32))
    active_claim_marker: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN state IN ('queued', 'running') THEN 1 ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    claim_generation: Mapped[int] = mapped_column(Integer)
    provider_input: Mapped[str] = mapped_column(Text)
    provider_turn_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_problem: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_retry_safe: Mapped[bool] = mapped_column(default=False, server_default="0")
    retry_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retry_request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    conversation: Mapped[OperatorConversationModel] = relationship(
        back_populates="invocations",
        lazy="raise",
    )
    input_entry: Mapped[OperatorConversationEntryModel] = relationship(
        foreign_keys=[input_entry_id],
        lazy="raise",
    )
    retry_basis: Mapped[OperatorInvocationModel | None] = relationship(
        foreign_keys=[retry_basis_invocation_id],
        remote_side=[invocation_id],
        lazy="raise",
    )
    effects: Mapped[list[OperatorEffectModel]] = relationship(
        back_populates="invocation",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class OperatorEffectModel(RuntimeBase):
    __tablename__ = "operator_effects"
    __table_args__ = (
        CheckConstraint(
            "state IN ('proposed', 'executing', 'succeeded', 'failed', 'indeterminate')",
            name="ck_operator_effects_state",
        ),
        CheckConstraint(
            "confirmation_state IS NULL OR "
            "confirmation_state IN ('available', 'consumed', 'expired')",
            name="ck_operator_effects_confirmation_state",
        ),
        CheckConstraint(
            "(confirmation_id IS NULL AND confirmation_state IS NULL) OR "
            "(confirmation_id IS NOT NULL AND confirmation_state IS NOT NULL)",
            name="ck_operator_effects_confirmation_identity",
        ),
        UniqueConstraint(
            "invocation_id",
            "provider_call_id",
            name="uq_operator_effects_provider_call",
        ),
        UniqueConstraint(
            "confirmation_id",
            name="uq_operator_effects_confirmation_id",
        ),
        UniqueConstraint(
            "conversation_id",
            "confirmation_id",
            "confirmation_idempotency_key",
            name="uq_operator_effects_confirmation_idempotency",
        ),
    )

    effect_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("operator_conversations.conversation_id", ondelete="CASCADE"),
        index=True,
    )
    invocation_id: Mapped[str] = mapped_column(
        ForeignKey("operator_invocations.invocation_id", ondelete="CASCADE"),
        index=True,
    )
    provider_call_id: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    request_digest: Mapped[str] = mapped_column(String(64))
    action_guard: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(32))
    confirmation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmation_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confirmation_idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    confirmation_request_digest: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    result_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("operator_conversation_entries.entry_id"),
        nullable=True,
    )
    result_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    conversation: Mapped[OperatorConversationModel] = relationship(
        back_populates="effects",
        lazy="raise",
    )
    invocation: Mapped[OperatorInvocationModel] = relationship(
        back_populates="effects",
        lazy="raise",
    )
    result_entry: Mapped[OperatorConversationEntryModel | None] = relationship(
        foreign_keys=[result_entry_id],
        lazy="raise",
    )


__all__ = [
    "OperatorConversationEntryModel",
    "OperatorConversationModel",
    "OperatorEffectModel",
    "OperatorInvocationModel",
]
