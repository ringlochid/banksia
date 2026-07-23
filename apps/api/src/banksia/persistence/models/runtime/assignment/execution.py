from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    and_,
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
    from banksia.persistence.models.runtime.flow.runtime import FlowModel
    from banksia.persistence.models.runtime.task import TaskModel


class AssignmentModel(RuntimeBase):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("assignment_id", "node_key"),
        UniqueConstraint("assignment_id", "parent_assignment_id"),
        UniqueConstraint(
            "assignment_id",
            "parent_assignment_id",
            "created_by_dispatch_id",
        ),
        UniqueConstraint("assignment_id", "work_plan_revision"),
        UniqueConstraint("task_id", "flow_id", "assignment_id"),
        UniqueConstraint(
            "task_id",
            "flow_id",
            "assignment_id",
            "member_id",
            name="uq_assignments_member_identity",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "parent_assignment_id"],
            ["assignments.task_id", "assignments.flow_id", "assignments.assignment_id"],
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
            ["flow_id", "created_by_dispatch_id"],
            ["dispatch_turns.flow_id", "dispatch_turns.dispatch_id"],
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
        Index("ix_assignments_task_node", "task_id", "node_key"),
    )

    assignment_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    member_id: Mapped[str] = mapped_column(String(128))
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    assignment_key: Mapped[str] = mapped_column(String(255), unique=True)
    node_key: Mapped[str] = mapped_column(String(255), index=True)
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
    created_by_dispatch_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    terminal_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        foreign_keys=[task_id],
        lazy="raise",
    )
    flow: Mapped[FlowModel] = relationship(
        "FlowModel",
        back_populates="assignments",
        foreign_keys=[flow_id],
        lazy="raise",
    )
    parent: Mapped[AssignmentModel | None] = relationship(
        back_populates="children",
        foreign_keys=[task_id, flow_id, parent_assignment_id],
        remote_side=lambda: [
            AssignmentModel.task_id,
            AssignmentModel.flow_id,
            AssignmentModel.assignment_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    children: Mapped[list[AssignmentModel]] = relationship(
        back_populates="parent",
        foreign_keys=(
            "[AssignmentModel.task_id, AssignmentModel.flow_id, "
            "AssignmentModel.parent_assignment_id]"
        ),
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
            AssignmentModel.flow_id == AttemptModel.flow_id,
            AssignmentModel.assignment_id == AttemptModel.assignment_id,
            AssignmentModel.node_key == AttemptModel.node_key,
        ),
        foreign_keys=(
            "[AttemptModel.task_id, AttemptModel.flow_id, AttemptModel.assignment_id, "
            "AttemptModel.node_key]"
        ),
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
        foreign_keys=[flow_id, created_by_dispatch_id],
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
        UniqueConstraint("task_id", "flow_id", "assignment_id", "attempt_id"),
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
        ForeignKeyConstraint(
            ["task_id", "flow_id", "assignment_id"],
            ["assignments.task_id", "assignments.flow_id", "assignments.assignment_id"],
            name="fk_attempts_assignment_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["assignment_id", "node_key"],
            ["assignments.assignment_id", "assignments.node_key"],
            name="fk_attempts_assignment_node_owner",
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
            [
                "task_id",
                "flow_id",
                "assignment_id",
                "attempt_id",
                "latest_checkpoint_id",
            ],
            [
                "attempt_checkpoints.task_id",
                "attempt_checkpoints.flow_id",
                "attempt_checkpoints.assignment_id",
                "attempt_checkpoints.attempt_id",
                "attempt_checkpoints.checkpoint_id",
            ],
            name="fk_attempts_latest_checkpoint_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_attempts_task_node", "task_id", "node_key"),
    )

    attempt_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    node_key: Mapped[str] = mapped_column(String(255), index=True)
    retry_of_attempt_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latest_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="running")
    terminal_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    assignment: Mapped[AssignmentModel] = relationship(
        back_populates="attempts",
        primaryjoin=lambda: and_(
            AttemptModel.task_id == AssignmentModel.task_id,
            AttemptModel.flow_id == AssignmentModel.flow_id,
            AttemptModel.assignment_id == AssignmentModel.assignment_id,
            AttemptModel.node_key == AssignmentModel.node_key,
        ),
        foreign_keys=[task_id, flow_id, assignment_id, node_key],
        lazy="raise",
        viewonly=True,
    )
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        foreign_keys=[task_id],
        lazy="raise",
    )
    flow: Mapped[FlowModel] = relationship(
        "FlowModel",
        foreign_keys=[flow_id],
        lazy="raise",
    )
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
        foreign_keys=[
            task_id,
            flow_id,
            assignment_id,
            attempt_id,
            latest_checkpoint_id,
        ],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    checkpoints: Mapped[list[AttemptCheckpointModel]] = relationship(
        back_populates="attempt",
        primaryjoin=lambda: and_(
            AttemptModel.task_id == AttemptCheckpointModel.task_id,
            AttemptModel.flow_id == AttemptCheckpointModel.flow_id,
            AttemptModel.assignment_id == AttemptCheckpointModel.assignment_id,
            AttemptModel.attempt_id == AttemptCheckpointModel.attempt_id,
        ),
        foreign_keys=(
            "[AttemptCheckpointModel.task_id, AttemptCheckpointModel.flow_id, "
            "AttemptCheckpointModel.assignment_id, AttemptCheckpointModel.attempt_id]"
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
            "AttemptModel.flow_id == DispatchTurnModel.flow_id, "
            "AttemptModel.assignment_id == DispatchTurnModel.assignment_id, "
            "AttemptModel.attempt_id == DispatchTurnModel.attempt_id)"
        ),
        foreign_keys=(
            "[DispatchTurnModel.task_id, DispatchTurnModel.flow_id, "
            "DispatchTurnModel.assignment_id, DispatchTurnModel.attempt_id]"
        ),
        lazy="raise",
        order_by="DispatchTurnModel.created_at",
        viewonly=True,
    )


class AttemptCheckpointModel(RuntimeBase):
    __tablename__ = "attempt_checkpoints"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", "attempt_id"),
        UniqueConstraint("task_id", "assignment_id", "attempt_id", "checkpoint_id"),
        UniqueConstraint(
            "task_id",
            "flow_id",
            "assignment_id",
            "attempt_id",
            "checkpoint_id",
        ),
        CheckConstraint(
            f"outcome IS NULL OR outcome IN ({sql_in(CHECKPOINT_OUTCOME_VALUES)})",
            name="ck_attempt_checkpoints_outcome",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "assignment_id", "attempt_id"],
            [
                "attempts.task_id",
                "attempts.flow_id",
                "attempts.assignment_id",
                "attempts.attempt_id",
            ],
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
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    authoring_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        foreign_keys=[task_id],
        lazy="raise",
    )
    flow: Mapped[FlowModel] = relationship(
        "FlowModel",
        foreign_keys=[flow_id],
        lazy="raise",
    )
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
            AttemptCheckpointModel.flow_id == AttemptModel.flow_id,
            AttemptCheckpointModel.assignment_id == AttemptModel.assignment_id,
            AttemptCheckpointModel.attempt_id == AttemptModel.attempt_id,
        ),
        foreign_keys=[task_id, flow_id, assignment_id, attempt_id],
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
