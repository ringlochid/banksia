from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import (
    HUMAN_REQUEST_KIND_VALUES,
    HUMAN_REQUEST_RESOLUTION_KIND_VALUES,
    HUMAN_REQUEST_RESOLUTION_SURFACE_VALUES,
    HUMAN_REQUEST_STATUS_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from banksia.persistence.models.runtime.waiting import AttemptWaitModel


class HumanRequestModel(RuntimeBase):
    __tablename__ = "human_requests"
    __table_args__ = (
        UniqueConstraint("source_dispatch_id"),
        UniqueConstraint("request_id", "task_id", "source_dispatch_id"),
        UniqueConstraint(
            "request_id",
            "task_id",
            "assignment_id",
            "attempt_id",
            "source_dispatch_id",
            name="uq_human_requests_attempt_source_owner",
        ),
        CheckConstraint(
            f"request_kind IN ({sql_in(HUMAN_REQUEST_KIND_VALUES)})",
            name="ck_human_requests_kind",
        ),
        CheckConstraint(
            f"status IN ({sql_in(HUMAN_REQUEST_STATUS_VALUES)})",
            name="ck_human_requests_status",
        ),
        CheckConstraint(
            "resolution_kind IS NULL OR "
            f"resolution_kind IN ({sql_in(HUMAN_REQUEST_RESOLUTION_KIND_VALUES)})",
            name="ck_human_requests_resolution_kind",
        ),
        CheckConstraint(
            "resolved_by_surface IS NULL OR "
            f"resolved_by_surface IN ({sql_in(HUMAN_REQUEST_RESOLUTION_SURFACE_VALUES)})",
            name="ck_human_requests_resolution_surface",
        ),
        CheckConstraint(
            "(due_at IS NULL AND timeout_policy_json IS NULL AND default_behavior_json IS NULL) OR "
            "(due_at IS NOT NULL AND timeout_policy_json IS NOT NULL)",
            name="ck_human_requests_timeout_policy",
        ),
        CheckConstraint(
            "status != 'timed_out' OR due_at IS NOT NULL",
            name="ck_human_requests_timeout_requires_deadline",
        ),
        CheckConstraint(
            "(status = 'open' AND resolution_kind IS NULL AND item_responses_json IS NULL AND "
            "resolution_policy_basis_json IS NULL AND resolution_summary IS NULL AND "
            "resolved_by_actor_ref IS NULL AND resolved_by_surface IS NULL AND "
            "resolved_at IS NULL AND successor_dispatch_id IS NULL) OR "
            "(status != 'open' AND resolution_kind IS NOT NULL AND "
            "resolution_summary IS NOT NULL AND resolved_by_surface IS NOT NULL AND "
            "resolved_at IS NOT NULL)",
            name="ck_human_requests_terminal_state",
        ),
        CheckConstraint(
            "(status = 'resolved' AND resolution_kind = 'answered' AND "
            "item_responses_json IS NOT NULL) OR "
            "(status = 'timed_out' AND resolution_kind = 'timed_out' AND "
            "item_responses_json IS NULL AND resolution_policy_basis_json IS NOT NULL) OR "
            "(status = 'cancelled' AND resolution_kind = 'cancelled' AND "
            "item_responses_json IS NULL) OR status = 'open'",
            name="ck_human_requests_status_resolution",
        ),
        ForeignKeyConstraint(
            ["source_dispatch_id", "task_id", "assignment_id", "attempt_id"],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
            ],
            name="fk_human_requests_source_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["source_dispatch_id", "successor_dispatch_id"],
            ["dispatch_turns.predecessor_dispatch_id", "dispatch_turns.dispatch_id"],
            name="fk_human_requests_successor_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_human_requests_status_due", "status", "due_at"),
        Index("ix_human_requests_task_status", "task_id", "status"),
    )

    request_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"))
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"))
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    request_kind: Mapped[str] = mapped_column(String(64))
    request_summary: Mapped[str] = mapped_column(Text)
    request_items_json: Mapped[list[dict[str, object]]] = mapped_column(JSON(none_as_null=True))
    capability_basis_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    due_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    timeout_policy_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    default_behavior_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(64), default="open")
    resolution_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_responses_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    resolution_policy_basis_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_actor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_by_surface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    successor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="human_request",
        foreign_keys=[source_dispatch_id, task_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    successor_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        foreign_keys=[source_dispatch_id, successor_dispatch_id],
        lazy="raise",
        viewonly=True,
    )
    attempt_wait: Mapped[AttemptWaitModel | None] = relationship(
        "AttemptWaitModel",
        back_populates="human_request",
        foreign_keys="AttemptWaitModel.human_request_id",
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    file_references: Mapped[list[HumanRequestFileReferenceModel]] = relationship(
        back_populates="human_request",
        foreign_keys="HumanRequestFileReferenceModel.request_id",
        lazy="raise",
        order_by="HumanRequestFileReferenceModel.order_index",
    )


class HumanRequestFileReferenceModel(RuntimeBase):
    """One ordered loose-file reference owned by a Human Request."""

    __tablename__ = "human_request_file_references"
    __table_args__ = (
        PrimaryKeyConstraint("request_id", "order_index"),
        UniqueConstraint("request_id", "path"),
        CheckConstraint(
            "order_index >= 0",
            name="ck_human_request_file_references_order",
        ),
    )

    request_id: Mapped[str] = mapped_column(ForeignKey("human_requests.request_id"))
    order_index: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_request: Mapped[HumanRequestModel] = relationship(
        back_populates="file_references",
        foreign_keys=[request_id],
        lazy="raise",
    )


__all__ = ["HumanRequestFileReferenceModel", "HumanRequestModel"]
