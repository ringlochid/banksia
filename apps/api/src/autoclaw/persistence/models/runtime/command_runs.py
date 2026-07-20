from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.models.runtime.common import (
    COMMAND_RUN_STATE_VALUES,
    COMMAND_RUN_TERMINAL_SOURCE_VALUES,
    COMMAND_RUN_TERMINAL_STATE_VALUES,
    sql_in,
    utcnow,
)
from autoclaw.persistence.models.runtime.waiting import FlowWaitModel

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.dispatch.turns import DispatchTurnModel


class CommandRunModel(RuntimeBase):
    __tablename__ = "command_runs"
    __table_args__ = (
        UniqueConstraint("source_dispatch_id"),
        UniqueConstraint("run_id", "task_id", "flow_id", "source_dispatch_id"),
        CheckConstraint(
            f"state IN ({sql_in(COMMAND_RUN_STATE_VALUES)})",
            name="ck_command_runs_state",
        ),
        CheckConstraint("ownership_revision >= 0", name="ck_command_runs_ownership_revision"),
        CheckConstraint(
            "timeout_seconds IS NULL OR timeout_seconds > 0",
            name="ck_command_runs_timeout_seconds",
        ),
        CheckConstraint(
            "(started_at IS NULL AND due_at IS NULL) OR "
            "(started_at IS NOT NULL AND timeout_seconds IS NULL AND due_at IS NULL) OR "
            "(started_at IS NOT NULL AND timeout_seconds IS NOT NULL AND due_at IS NOT NULL)",
            name="ck_command_runs_launch_deadline",
        ),
        CheckConstraint(
            "state != 'timed_out' OR due_at IS NOT NULL",
            name="ck_command_runs_timeout_requires_deadline",
        ),
        CheckConstraint(
            "terminal_event_source IS NULL OR "
            f"terminal_event_source IN ({sql_in(COMMAND_RUN_TERMINAL_SOURCE_VALUES)})",
            name="ck_command_runs_terminal_event_source",
        ),
        CheckConstraint(
            "state != 'abandoned' OR "
            "(terminal_failure_code IS NOT NULL AND "
            "terminal_failure_code = 'command_ownership_lost')",
            name="ck_command_runs_abandoned_diagnostic",
        ),
        CheckConstraint(
            "(state = 'pending_start' AND started_at IS NULL AND ended_at IS NULL AND "
            "cancellation_requested_at IS NULL AND cancellation_requested_by_actor_ref IS NULL "
            "AND terminal_summary IS NULL AND terminal_exit_code IS NULL AND "
            "terminal_failure_code IS NULL AND terminal_event_source IS NULL AND "
            "terminal_actor_ref IS NULL AND successor_dispatch_id IS NULL) OR "
            "(state = 'running' AND started_at IS NOT NULL AND ended_at IS NULL AND "
            "cancellation_requested_at IS NULL AND cancellation_requested_by_actor_ref IS NULL "
            "AND terminal_summary IS NULL AND terminal_exit_code IS NULL AND "
            "terminal_failure_code IS NULL AND terminal_event_source IS NULL AND "
            "terminal_actor_ref IS NULL AND successor_dispatch_id IS NULL) OR "
            "(state = 'cancellation_requested' AND ended_at IS NULL AND "
            "cancellation_requested_at IS NOT NULL AND terminal_summary IS NULL AND "
            "terminal_exit_code IS NULL AND terminal_failure_code IS NULL AND "
            "terminal_event_source IS NULL AND terminal_actor_ref IS NULL AND "
            "successor_dispatch_id IS NULL) OR "
            f"(state IN ({sql_in(COMMAND_RUN_TERMINAL_STATE_VALUES)}) AND "
            "ended_at IS NOT NULL AND terminal_summary IS NOT NULL AND "
            "terminal_event_source IS NOT NULL)",
            name="ck_command_runs_terminal_state",
        ),
        ForeignKeyConstraint(
            ["source_dispatch_id", "task_id", "flow_id", "assignment_id", "attempt_id"],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.flow_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
            ],
            name="fk_command_runs_source_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["source_dispatch_id", "successor_dispatch_id"],
            ["dispatch_turns.predecessor_dispatch_id", "dispatch_turns.dispatch_id"],
            name="fk_command_runs_successor_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_command_runs_state_due", "state", "due_at"),
        Index("ix_command_runs_task_created", "task_id", "created_at"),
    )

    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"))
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"))
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    command_spec_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    cwd_policy_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    environment_refs_json: Mapped[list[str] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text)
    expected_outputs_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stdout_logical_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_logical_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(64), default="pending_start")
    ownership_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    process_metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancellation_requested_by_actor_ref: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    terminal_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terminal_failure_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    terminal_event_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    terminal_actor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    successor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="command_run",
        foreign_keys=[source_dispatch_id, task_id, flow_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    successor_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        foreign_keys=[source_dispatch_id, successor_dispatch_id],
        lazy="raise",
        viewonly=True,
    )
    flow_wait: Mapped[FlowWaitModel | None] = relationship(
        "FlowWaitModel",
        back_populates="command_run",
        foreign_keys=[FlowWaitModel.command_run_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )


__all__ = ["CommandRunModel"]
