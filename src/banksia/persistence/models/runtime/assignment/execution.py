from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    and_,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import (
    ATTEMPT_STATUS_VALUES,
    CHECKPOINT_OUTCOME_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.assignment.work_plan import (
        AssignmentWorkPlanModel,
    )
    from banksia.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from banksia.persistence.models.runtime.task import TaskModel
    from banksia.persistence.models.runtime.team import MemberModel
    from banksia.persistence.models.runtime.waiting import AttemptWaitModel


class AssignmentModel(RuntimeBase):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("task_id", "assignment_id"),
        UniqueConstraint(
            "task_id",
            "assignment_id",
            "member_id",
            name="uq_assignments_member_identity",
        ),
        UniqueConstraint("assignment_id", "parent_assignment_id"),
        UniqueConstraint(
            "assignment_id",
            "parent_assignment_id",
            "created_by_dispatch_id",
        ),
        UniqueConstraint("assignment_id", "work_plan_revision"),
        ForeignKeyConstraint(
            ["task_id", "member_id"],
            ["members.task_id", "members.member_id"],
            name="fk_assignments_member",
        ),
        ForeignKeyConstraint(
            ["task_id", "parent_assignment_id"],
            ["assignments.task_id", "assignments.assignment_id"],
            name="fk_assignments_parent_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["current_attempt_id", "assignment_id"],
            ["attempts.attempt_id", "attempts.assignment_id"],
            name="fk_assignments_current_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "created_by_dispatch_id"],
            ["dispatch_turns.task_id", "dispatch_turns.dispatch_id"],
            name="fk_assignments_authoring_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("work_plan_revision >= 0", name="ck_assignments_work_plan_revision"),
        CheckConstraint(
            "(child_assignment_limit IS NULL AND child_assignments_remaining IS NULL) OR "
            "(child_assignment_limit IS NOT NULL AND "
            "child_assignments_remaining IS NOT NULL AND "
            "child_assignment_limit >= 0 AND child_assignments_remaining >= 0 AND "
            "child_assignments_remaining <= child_assignment_limit)",
            name="ck_assignments_child_budget",
        ),
        CheckConstraint(
            "(retry_limit IS NULL AND retries_remaining IS NULL) OR "
            "(retry_limit IS NOT NULL AND retries_remaining IS NOT NULL AND "
            "retry_limit >= 0 AND retries_remaining >= 0 AND "
            "retries_remaining <= retry_limit)",
            name="ck_assignments_retry_budget",
        ),
        CheckConstraint(
            "terminal_outcome IS NULL OR terminal_outcome IN ('green', 'blocked')",
            name="ck_assignments_terminal_outcome",
        ),
        CheckConstraint(
            "(terminal_outcome IS NULL AND closed_at IS NULL) OR "
            "(terminal_outcome IS NOT NULL AND closed_at IS NOT NULL)",
            name="ck_assignments_terminal_state",
        ),
        Index(
            "uq_assignments_one_open_per_member",
            "task_id",
            "member_id",
            unique=True,
            sqlite_where=text("closed_at IS NULL"),
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index("ix_assignments_task_member", "task_id", "member_id"),
    )

    assignment_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    member_id: Mapped[str] = mapped_column(String(128))
    parent_assignment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    current_attempt_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_plan_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    child_assignment_limit: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    child_assignments_remaining: Mapped[int] = mapped_column(
        Integer,
        default=20,
        server_default="20",
    )
    retry_limit: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    retries_remaining: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    terminal_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    task: Mapped[TaskModel] = relationship("TaskModel", foreign_keys=[task_id], lazy="raise")
    member: Mapped[MemberModel] = relationship(
        "MemberModel",
        foreign_keys=[task_id, member_id],
        lazy="raise",
        viewonly=True,
    )
    parent: Mapped[AssignmentModel | None] = relationship(
        back_populates="children",
        foreign_keys=[task_id, parent_assignment_id],
        remote_side=lambda: [AssignmentModel.task_id, AssignmentModel.assignment_id],
        lazy="raise",
        viewonly=True,
    )
    children: Mapped[list[AssignmentModel]] = relationship(
        back_populates="parent",
        foreign_keys="[AssignmentModel.task_id, AssignmentModel.parent_assignment_id]",
        lazy="raise",
        order_by="AssignmentModel.created_at",
        viewonly=True,
    )
    file_references: Mapped[list[AssignmentFileReferenceModel]] = relationship(
        back_populates="assignment",
        foreign_keys="AssignmentFileReferenceModel.assignment_id",
        lazy="raise",
        order_by="AssignmentFileReferenceModel.order_index",
    )
    attempts: Mapped[list[AttemptModel]] = relationship(
        back_populates="assignment",
        primaryjoin=lambda: and_(
            AssignmentModel.task_id == AttemptModel.task_id,
            AssignmentModel.assignment_id == AttemptModel.assignment_id,
        ),
        foreign_keys="[AttemptModel.task_id, AttemptModel.assignment_id]",
        lazy="raise",
        order_by="AttemptModel.opened_at",
        viewonly=True,
    )
    current_attempt: Mapped[AttemptModel | None] = relationship(
        primaryjoin=lambda: and_(
            AssignmentModel.assignment_id == AttemptModel.assignment_id,
            AssignmentModel.current_attempt_id == AttemptModel.attempt_id,
        ),
        foreign_keys=[current_attempt_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    created_by_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        back_populates="created_assignments",
        foreign_keys=[task_id, created_by_dispatch_id],
        lazy="raise",
        viewonly=True,
    )
    work_plan: Mapped[AssignmentWorkPlanModel | None] = relationship(
        back_populates="assignment",
        primaryjoin=(
            "and_(AssignmentModel.assignment_id == AssignmentWorkPlanModel.assignment_id, "
            "AssignmentModel.work_plan_revision == AssignmentWorkPlanModel.revision)"
        ),
        foreign_keys=("[AssignmentWorkPlanModel.assignment_id, AssignmentWorkPlanModel.revision]"),
        lazy="raise",
        uselist=False,
        viewonly=True,
    )


class AssignmentFileReferenceModel(RuntimeBase):
    __tablename__ = "assignment_file_references"
    __table_args__ = (
        PrimaryKeyConstraint("assignment_id", "order_index"),
        UniqueConstraint("assignment_id", "path"),
        CheckConstraint("order_index >= 0", name="ck_assignment_file_references_order"),
    )

    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"))
    order_index: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignment: Mapped[AssignmentModel] = relationship(
        back_populates="file_references",
        foreign_keys=[assignment_id],
        lazy="raise",
    )


class AttemptModel(RuntimeBase):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("attempt_id", "assignment_id"),
        UniqueConstraint("attempt_id", "task_id"),
        UniqueConstraint("task_id", "assignment_id", "attempt_id"),
        UniqueConstraint(
            "task_id",
            "assignment_id",
            "attempt_id",
            "retry_of_attempt_id",
            name="uq_attempts_exact_retry_owner",
        ),
        UniqueConstraint(
            "attempt_id",
            "current_dispatch_id",
            "current_dispatch_presence_marker",
            name="uq_attempts_current_dispatch_owner",
        ),
        UniqueConstraint("attempt_id", "current_wait_id", name="uq_attempts_current_wait_owner"),
        CheckConstraint(
            f"status IN ({sql_in(ATTEMPT_STATUS_VALUES)})",
            name="ck_attempts_status",
        ),
        CheckConstraint(
            "terminal_outcome IS NULL OR "
            f"terminal_outcome IN ({sql_in(CHECKPOINT_OUTCOME_VALUES)})",
            name="ck_attempts_terminal_outcome_value",
        ),
        CheckConstraint(
            "(status = 'completed' AND terminal_outcome IS NOT NULL AND closed_at IS NOT NULL) OR "
            "(status = 'cancelled' AND terminal_outcome IS NULL AND closed_at IS NOT NULL) OR "
            "(status IN ('pending', 'running') AND terminal_outcome IS NULL AND closed_at IS NULL)",
            name="ck_attempts_terminal_state",
        ),
        CheckConstraint(
            "current_dispatch_id IS NULL OR current_wait_id IS NULL",
            name="ck_attempts_current_dispatch_excludes_wait",
        ),
        CheckConstraint(
            "status = 'running' OR (current_dispatch_id IS NULL AND current_wait_id IS NULL)",
            name="ck_attempts_nonrunning_has_no_current_authority",
        ),
        CheckConstraint(
            "watchdog_replacement_count >= 0",
            name="ck_attempts_watchdog_replacement_count",
        ),
        ForeignKeyConstraint(
            ["task_id", "assignment_id"],
            ["assignments.task_id", "assignments.assignment_id"],
            name="fk_attempts_assignment_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["assignment_id", "retry_of_attempt_id"],
            ["attempts.assignment_id", "attempts.attempt_id"],
            name="fk_attempts_retry_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "assignment_id", "attempt_id", "latest_checkpoint_id"],
            [
                "attempt_checkpoints.task_id",
                "attempt_checkpoints.assignment_id",
                "attempt_checkpoints.attempt_id",
                "attempt_checkpoints.checkpoint_id",
            ],
            name="fk_attempts_latest_checkpoint_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "current_dispatch_id",
                "task_id",
                "assignment_id",
                "attempt_id",
                "current_dispatch_presence_marker",
            ],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
                "dispatch_turns.active_status_marker",
            ],
            name="fk_attempts_current_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["current_wait_id", "task_id", "assignment_id", "attempt_id"],
            [
                "attempt_waits.wait_id",
                "attempt_waits.task_id",
                "attempt_waits.assignment_id",
                "attempt_waits.attempt_id",
            ],
            name="fk_attempts_current_wait_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_attempts_task_assignment", "task_id", "assignment_id"),
    )

    attempt_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    retry_of_attempt_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latest_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_wait_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    watchdog_replacement_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    current_dispatch_presence_marker: Mapped[int] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN current_dispatch_id IS NULL THEN 0 ELSE 1 END",
            persisted=True,
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(64), default="running")
    terminal_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    assignment: Mapped[AssignmentModel] = relationship(
        back_populates="attempts",
        primaryjoin=lambda: and_(
            AttemptModel.task_id == AssignmentModel.task_id,
            AttemptModel.assignment_id == AssignmentModel.assignment_id,
        ),
        foreign_keys=[task_id, assignment_id],
        lazy="raise",
        viewonly=True,
    )
    task: Mapped[TaskModel] = relationship("TaskModel", foreign_keys=[task_id], lazy="raise")
    retry_of_attempt: Mapped[AttemptModel | None] = relationship(
        back_populates="retry_attempts",
        foreign_keys=[assignment_id, retry_of_attempt_id],
        remote_side=lambda: [AttemptModel.assignment_id, AttemptModel.attempt_id],
        lazy="raise",
        viewonly=True,
    )
    retry_attempts: Mapped[list[AttemptModel]] = relationship(
        back_populates="retry_of_attempt",
        foreign_keys="[AttemptModel.assignment_id, AttemptModel.retry_of_attempt_id]",
        lazy="raise",
        order_by="AttemptModel.opened_at",
        viewonly=True,
    )
    latest_checkpoint: Mapped[AttemptCheckpointModel | None] = relationship(
        "AttemptCheckpointModel",
        foreign_keys=[task_id, assignment_id, attempt_id, latest_checkpoint_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    checkpoints: Mapped[list[AttemptCheckpointModel]] = relationship(
        back_populates="attempt",
        primaryjoin=lambda: and_(
            AttemptModel.task_id == AttemptCheckpointModel.task_id,
            AttemptModel.assignment_id == AttemptCheckpointModel.assignment_id,
            AttemptModel.attempt_id == AttemptCheckpointModel.attempt_id,
        ),
        foreign_keys=(
            "[AttemptCheckpointModel.task_id, AttemptCheckpointModel.assignment_id, "
            "AttemptCheckpointModel.attempt_id]"
        ),
        lazy="raise",
        order_by="AttemptCheckpointModel.recorded_at",
        viewonly=True,
    )
    dispatch_turns: Mapped[list[DispatchTurnModel]] = relationship(
        "DispatchTurnModel",
        back_populates="attempt",
        primaryjoin=(
            "and_(AttemptModel.task_id == DispatchTurnModel.task_id, "
            "AttemptModel.assignment_id == DispatchTurnModel.assignment_id, "
            "AttemptModel.attempt_id == DispatchTurnModel.attempt_id)"
        ),
        foreign_keys=(
            "[DispatchTurnModel.task_id, DispatchTurnModel.assignment_id, "
            "DispatchTurnModel.attempt_id]"
        ),
        lazy="raise",
        order_by="DispatchTurnModel.created_at",
        viewonly=True,
    )
    current_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        primaryjoin=(
            "and_(AttemptModel.current_dispatch_id == DispatchTurnModel.dispatch_id, "
            "AttemptModel.task_id == DispatchTurnModel.task_id, "
            "AttemptModel.assignment_id == DispatchTurnModel.assignment_id, "
            "AttemptModel.attempt_id == DispatchTurnModel.attempt_id, "
            "AttemptModel.current_dispatch_presence_marker == "
            "DispatchTurnModel.active_status_marker)"
        ),
        foreign_keys=[
            current_dispatch_id,
            task_id,
            assignment_id,
            attempt_id,
            current_dispatch_presence_marker,
        ],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    current_wait: Mapped[AttemptWaitModel | None] = relationship(
        "AttemptWaitModel",
        primaryjoin=(
            "and_(AttemptModel.current_wait_id == AttemptWaitModel.wait_id, "
            "AttemptModel.task_id == AttemptWaitModel.task_id, "
            "AttemptModel.assignment_id == AttemptWaitModel.assignment_id, "
            "AttemptModel.attempt_id == AttemptWaitModel.attempt_id)"
        ),
        foreign_keys=[current_wait_id, task_id, assignment_id, attempt_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )


class AttemptCheckpointModel(RuntimeBase):
    __tablename__ = "attempt_checkpoints"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", "attempt_id"),
        UniqueConstraint("task_id", "assignment_id", "attempt_id", "checkpoint_id"),
        UniqueConstraint(
            "task_id",
            "assignment_id",
            "attempt_id",
            "checkpoint_id",
            "authoring_dispatch_id",
            "outcome",
            name="uq_attempt_checkpoints_boundary_owner",
        ),
        CheckConstraint(
            f"outcome IS NULL OR outcome IN ({sql_in(CHECKPOINT_OUTCOME_VALUES)})",
            name="ck_attempt_checkpoints_outcome",
        ),
        ForeignKeyConstraint(
            ["task_id", "assignment_id", "attempt_id"],
            ["attempts.task_id", "attempts.assignment_id", "attempts.attempt_id"],
            name="fk_attempt_checkpoints_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["authoring_dispatch_id", "assignment_id", "attempt_id"],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
            ],
            name="fk_attempt_checkpoints_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_attempt_checkpoints_attempt_recorded_at", "attempt_id", "recorded_at"),
    )

    checkpoint_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    authoring_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship("TaskModel", foreign_keys=[task_id], lazy="raise")
    assignment: Mapped[AssignmentModel] = relationship(
        primaryjoin=lambda: AssignmentModel.assignment_id == AttemptCheckpointModel.assignment_id,
        foreign_keys=[assignment_id],
        lazy="raise",
        viewonly=True,
    )
    attempt: Mapped[AttemptModel] = relationship(
        back_populates="checkpoints",
        primaryjoin=lambda: and_(
            AttemptCheckpointModel.task_id == AttemptModel.task_id,
            AttemptCheckpointModel.assignment_id == AttemptModel.assignment_id,
            AttemptCheckpointModel.attempt_id == AttemptModel.attempt_id,
        ),
        foreign_keys=[task_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    authoring_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="authored_checkpoints",
        foreign_keys=[authoring_dispatch_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    file_references: Mapped[list[CheckpointFileReferenceModel]] = relationship(
        back_populates="checkpoint",
        foreign_keys="CheckpointFileReferenceModel.checkpoint_id",
        lazy="raise",
        order_by="CheckpointFileReferenceModel.order_index",
    )


class CheckpointFileReferenceModel(RuntimeBase):
    __tablename__ = "checkpoint_file_references"
    __table_args__ = (
        PrimaryKeyConstraint("checkpoint_id", "order_index"),
        UniqueConstraint("checkpoint_id", "path"),
        CheckConstraint("order_index >= 0", name="ck_checkpoint_file_references_order"),
    )

    checkpoint_id: Mapped[str] = mapped_column(ForeignKey("attempt_checkpoints.checkpoint_id"))
    order_index: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint: Mapped[AttemptCheckpointModel] = relationship(
        back_populates="file_references",
        foreign_keys=[checkpoint_id],
        lazy="raise",
    )


__all__ = [
    "AssignmentFileReferenceModel",
    "AssignmentModel",
    "AttemptCheckpointModel",
    "AttemptModel",
    "CheckpointFileReferenceModel",
]
