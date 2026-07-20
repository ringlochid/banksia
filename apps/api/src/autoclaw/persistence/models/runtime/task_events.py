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
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.datetimes import UtcDateTime
from autoclaw.persistence.models.runtime.common import (
    TASK_EVENT_SOURCE_VALUES,
    TASK_EVENT_TYPE_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.assignment.execution import AttemptModel
    from autoclaw.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from autoclaw.persistence.models.runtime.flow.runtime import FlowRevisionModel
    from autoclaw.persistence.models.runtime.task import TaskModel


class TaskEventStreamHeadModel(RuntimeBase):
    """Chronology-only task-event sequencing state, never runtime currentness."""

    __tablename__ = "task_event_stream_heads"
    __table_args__ = (
        CheckConstraint(
            "allocator_revision >= 0",
            name="ck_task_event_stream_heads_allocator_revision",
        ),
        CheckConstraint(
            "last_event_seq >= 0",
            name="ck_task_event_stream_heads_last_event_seq",
        ),
        CheckConstraint(
            "(last_event_seq = 0 AND last_event_hash IS NULL) OR "
            "(last_event_seq >= 1 AND last_event_hash IS NOT NULL)",
            name="ck_task_event_stream_heads_last_event_pair",
        ),
        ForeignKeyConstraint(
            ["task_id"],
            ["tasks.task_id"],
            name="fk_task_event_stream_heads_task",
        ),
    )

    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    allocator_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_event_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_event_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        back_populates="event_stream_head",
        foreign_keys=[task_id],
        lazy="raise",
    )


class TaskEventModel(RuntimeBase):
    __tablename__ = "task_events"
    __table_args__ = (
        CheckConstraint(
            f"event_source IN ({sql_in(TASK_EVENT_SOURCE_VALUES)})",
            name="ck_task_events_event_source",
        ),
        CheckConstraint(
            f"event_type IN ({sql_in(TASK_EVENT_TYPE_VALUES)})",
            name="ck_task_events_event_type",
        ),
        CheckConstraint("event_seq >= 1", name="ck_task_events_event_seq"),
        ForeignKeyConstraint(
            ["dispatch_id", "task_id"],
            ["dispatch_turns.dispatch_id", "dispatch_turns.task_id"],
            name="fk_task_events_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "task_id"],
            ["attempts.attempt_id", "attempts.task_id"],
            name="fk_task_events_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_task_events_task_seq", "task_id", "event_seq", unique=True),
        Index("ix_task_events_task_event", "task_id", "event_id"),
    )

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_seq: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    event_type: Mapped[str] = mapped_column(String(255))
    event_source: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    flow_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("flow_revisions.flow_revision_id"),
        nullable=True,
        index=True,
    )
    dispatch_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    attempt_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    node_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    prev_event_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(255))
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        back_populates="task_events",
        foreign_keys=[task_id],
        lazy="raise",
    )
    flow_revision: Mapped[FlowRevisionModel | None] = relationship(
        "FlowRevisionModel",
        back_populates="task_events",
        foreign_keys=[flow_revision_id],
        lazy="raise",
    )
    dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        foreign_keys=[dispatch_id, task_id],
        lazy="raise",
        viewonly=True,
    )
    attempt: Mapped[AttemptModel | None] = relationship(
        "AttemptModel",
        foreign_keys=[attempt_id, task_id],
        lazy="raise",
        viewonly=True,
    )


__all__ = ["TaskEventModel", "TaskEventStreamHeadModel"]
