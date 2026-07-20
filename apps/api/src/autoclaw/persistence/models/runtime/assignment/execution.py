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
    and_,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.models.runtime.common import (
    ATTEMPT_STATUS_VALUES,
    CHECKPOINT_KIND_VALUES,
    CHECKPOINT_OUTCOME_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.assignment.artifacts import (
        ArtifactPublicationModel,
        CheckpointTransientModel,
        TransientLocalizationModel,
    )
    from autoclaw.persistence.models.runtime.assignment.work_plan import (
        AssignmentWorkPlanModel,
    )
    from autoclaw.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from autoclaw.persistence.models.runtime.flow.graph import FlowNodeModel
    from autoclaw.persistence.models.runtime.flow.runtime import FlowModel, FlowRevisionModel
    from autoclaw.persistence.models.runtime.task import TaskModel


class AssignmentModel(RuntimeBase):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("assignment_id", "flow_node_id"),
        UniqueConstraint("assignment_id", "node_key"),
        UniqueConstraint("assignment_id", "flow_revision_id"),
        UniqueConstraint("assignment_id", "parent_assignment_id"),
        UniqueConstraint(
            "assignment_id",
            "parent_assignment_id",
            "created_by_dispatch_id",
        ),
        UniqueConstraint("assignment_id", "work_plan_revision"),
        UniqueConstraint("task_id", "flow_id", "assignment_id"),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "parent_assignment_id"],
            ["assignments.task_id", "assignments.flow_id", "assignments.assignment_id"],
            name="fk_assignments_parent_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["flow_id", "flow_revision_id", "flow_node_id"],
            ["flow_nodes.flow_id", "flow_nodes.flow_revision_id", "flow_nodes.flow_node_id"],
            name="fk_assignments_flow_node_owner",
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
        Index("ix_assignments_task_node", "task_id", "node_key"),
    )

    assignment_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    flow_revision_id: Mapped[str] = mapped_column(String(255))
    flow_node_id: Mapped[str] = mapped_column(String(255), index=True)
    assignment_key: Mapped[str] = mapped_column(String(255), unique=True)
    node_key: Mapped[str] = mapped_column(String(255), index=True)
    parent_assignment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    criteria_json: Mapped[list[dict[str, object]]] = mapped_column(JSON(none_as_null=True))
    consumes_json: Mapped[list[dict[str, object]]] = mapped_column(JSON(none_as_null=True))
    produces_json: Mapped[list[dict[str, object]]] = mapped_column(JSON(none_as_null=True))
    current_attempt_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_plan_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    child_assignment_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    child_assignments_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retries_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_dispatch_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    flow_revision: Mapped[FlowRevisionModel] = relationship(
        "FlowRevisionModel",
        back_populates="assignments",
        primaryjoin=(
            "and_(AssignmentModel.flow_id == FlowRevisionModel.flow_id, "
            "AssignmentModel.flow_revision_id == FlowRevisionModel.flow_revision_id)"
        ),
        foreign_keys=[flow_id, flow_revision_id],
        lazy="raise",
        viewonly=True,
    )
    flow_node: Mapped[FlowNodeModel] = relationship(
        "FlowNodeModel",
        back_populates="assignments",
        foreign_keys=[flow_id, flow_revision_id, flow_node_id],
        lazy="raise",
        viewonly=True,
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
    criteria_refs: Mapped[list[AssignmentCriteriaRefModel]] = relationship(
        back_populates="assignment",
        foreign_keys="AssignmentCriteriaRefModel.assignment_id",
        lazy="raise",
        order_by="AssignmentCriteriaRefModel.order_index",
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


class AssignmentCriteriaRefModel(RuntimeBase):
    __tablename__ = "assignment_criteria_refs"
    __table_args__ = (UniqueConstraint("assignment_id", "order_index"),)

    assignment_criteria_ref_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"), index=True)
    slot: Mapped[str] = mapped_column(String(255))
    logical_path: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer)
    assignment: Mapped[AssignmentModel] = relationship(
        back_populates="criteria_refs",
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
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
            f"checkpoint_kind IN ({sql_in(CHECKPOINT_KIND_VALUES)})",
            name="ck_attempt_checkpoints_kind",
        ),
        CheckConstraint(
            f"outcome IS NULL OR outcome IN ({sql_in(CHECKPOINT_OUTCOME_VALUES)})",
            name="ck_attempt_checkpoints_outcome",
        ),
        CheckConstraint(
            "(checkpoint_kind = 'progress' AND outcome IS NULL) OR "
            "(checkpoint_kind = 'terminal' AND outcome IS NOT NULL)",
            name="ck_attempt_checkpoints_kind_outcome",
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
        Index(
            "uq_attempt_checkpoints_one_terminal_per_dispatch",
            "authoring_dispatch_id",
            unique=True,
            sqlite_where=text("checkpoint_kind = 'terminal'"),
            postgresql_where=text("checkpoint_kind = 'terminal'"),
        ),
        Index("ix_attempt_checkpoints_attempt_recorded_at", "attempt_id", "recorded_at"),
    )

    checkpoint_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    authoring_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    checkpoint_kind: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    criteria_results_json: Mapped[list[dict[str, object]]] = mapped_column(JSON(none_as_null=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
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
    artifact_publications: Mapped[list[ArtifactPublicationModel]] = relationship(
        "ArtifactPublicationModel",
        back_populates="checkpoint",
        foreign_keys=(
            "[ArtifactPublicationModel.task_id, ArtifactPublicationModel.flow_id, "
            "ArtifactPublicationModel.assignment_id, ArtifactPublicationModel.attempt_id, "
            "ArtifactPublicationModel.checkpoint_id]"
        ),
        lazy="raise",
        order_by="ArtifactPublicationModel.published_at",
        viewonly=True,
    )
    transient_localizations: Mapped[list[TransientLocalizationModel]] = relationship(
        "TransientLocalizationModel",
        back_populates="checkpoint",
        foreign_keys=(
            "[TransientLocalizationModel.task_id, TransientLocalizationModel.assignment_id, "
            "TransientLocalizationModel.attempt_id, "
            "TransientLocalizationModel.checkpoint_id]"
        ),
        lazy="raise",
        viewonly=True,
    )
    checkpoint_transients: Mapped[list[CheckpointTransientModel]] = relationship(
        "CheckpointTransientModel",
        back_populates="checkpoint",
        foreign_keys=(
            "[CheckpointTransientModel.task_id, CheckpointTransientModel.assignment_id, "
            "CheckpointTransientModel.attempt_id, CheckpointTransientModel.checkpoint_id]"
        ),
        lazy="raise",
        order_by="CheckpointTransientModel.order_index",
        viewonly=True,
    )


__all__ = [
    "AssignmentCriteriaRefModel",
    "AssignmentModel",
    "AttemptCheckpointModel",
    "AttemptModel",
]
