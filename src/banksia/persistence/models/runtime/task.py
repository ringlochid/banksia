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
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.registry import WorkflowRevisionModel
from banksia.persistence.models.runtime.common import (
    TASK_STATUS_VALUES,
    TASK_TERMINAL_OUTCOME_VALUES,
    WORKSPACE_BINDING_MODE_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.assignment.execution import AssignmentModel
    from banksia.persistence.models.runtime.dispatch.support import AcceptedBoundaryModel
    from banksia.persistence.models.runtime.task_events import (
        TaskEventModel,
        TaskEventStreamHeadModel,
    )
    from banksia.persistence.models.runtime.team import TeamRevisionModel


class TaskModel(RuntimeBase):
    __tablename__ = "tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_key", "workflow_revision_no", "workflow_content_hash"],
            [
                "workflow_revisions.workflow_key",
                "workflow_revisions.revision_no",
                "workflow_revisions.content_hash",
            ],
            name="fk_tasks_workflow_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "current_team_revision_id",
                "workflow_key",
                "workflow_revision_no",
                "workflow_content_hash",
            ],
            [
                "team_revisions.task_id",
                "team_revisions.team_revision_id",
                "team_revisions.workflow_key",
                "team_revisions.workflow_revision_no",
                "team_revisions.workflow_content_hash",
            ],
            name="fk_tasks_current_team_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "root_assignment_id"],
            ["assignments.task_id", "assignments.assignment_id"],
            name="fk_tasks_root_assignment",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "result_boundary_id",
                "task_id",
                "root_assignment_id",
                "terminal_outcome",
            ],
            [
                "accepted_boundaries.accepted_boundary_id",
                "accepted_boundaries.task_id",
                "accepted_boundaries.assignment_id",
                "accepted_boundaries.outcome",
            ],
            name="fk_tasks_result_boundary",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("workflow_revision_no >= 1", name="ck_tasks_workflow_revision_no"),
        CheckConstraint(
            f"status IN ({sql_in(TASK_STATUS_VALUES)})",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "terminal_outcome IS NULL OR "
            f"terminal_outcome IN ({sql_in(TASK_TERMINAL_OUTCOME_VALUES)})",
            name="ck_tasks_terminal_outcome_value",
        ),
        CheckConstraint(
            "(status = 'completed' AND terminal_outcome IS NOT NULL AND "
            "root_assignment_id IS NOT NULL AND result_boundary_id IS NOT NULL) OR "
            "(status != 'completed' AND terminal_outcome IS NULL AND "
            "result_boundary_id IS NULL)",
            name="ck_tasks_terminal_outcome_status",
        ),
        CheckConstraint("control_revision >= 0", name="ck_tasks_control_revision"),
        CheckConstraint(
            "(status = 'paused' AND pause_reason IS NOT NULL AND paused_at IS NOT NULL) OR "
            "(status != 'paused' AND pause_reason IS NULL AND pause_details IS NULL AND "
            "paused_at IS NULL AND paused_by_actor_ref IS NULL)",
            name="ck_tasks_pause_state",
        ),
        CheckConstraint(
            "max_child_assignments_per_assignment >= 0",
            name="ck_tasks_max_child_assignments_per_assignment",
        ),
        CheckConstraint(
            "max_retries_per_assignment >= 0",
            name="ck_tasks_max_retries_per_assignment",
        ),
        CheckConstraint("max_wave_members >= 1", name="ck_tasks_max_wave_members"),
        Index("ix_tasks_workflow_key", "workflow_key"),
        Index("ix_tasks_status_updated_at", "status", "updated_at"),
    )

    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    workflow_key: Mapped[str] = mapped_column(String(255))
    workflow_revision_no: Mapped[int] = mapped_column(Integer)
    workflow_content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), default="running", server_default="running")
    terminal_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    control_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pause_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pause_details: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    paused_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    paused_by_actor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    root_assignment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_team_revision_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_boundary_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_child_assignments_per_assignment: Mapped[int] = mapped_column(
        Integer,
        default=20,
        server_default="20",
    )
    max_retries_per_assignment: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
    )
    max_wave_members: Mapped[int] = mapped_column(Integer, default=8, server_default="8")
    task_root_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    workspace_binding: Mapped[WorkspaceBindingModel | None] = relationship(
        back_populates="task",
        foreign_keys="WorkspaceBindingModel.task_id",
        lazy="raise",
        uselist=False,
    )
    root_assignment: Mapped[AssignmentModel | None] = relationship(
        "AssignmentModel",
        foreign_keys=[task_id, root_assignment_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    event_stream_head: Mapped[TaskEventStreamHeadModel | None] = relationship(
        "TaskEventStreamHeadModel",
        back_populates="task",
        foreign_keys="TaskEventStreamHeadModel.task_id",
        lazy="raise",
        uselist=False,
    )
    task_events: Mapped[list[TaskEventModel]] = relationship(
        "TaskEventModel",
        back_populates="task",
        foreign_keys="TaskEventModel.task_id",
        lazy="raise",
        order_by="TaskEventModel.event_seq",
    )
    workflow_revision: Mapped[WorkflowRevisionModel] = relationship(
        "WorkflowRevisionModel",
        foreign_keys=[workflow_key, workflow_revision_no, workflow_content_hash],
        lazy="raise",
        viewonly=True,
    )
    current_team_revision: Mapped[TeamRevisionModel | None] = relationship(
        "TeamRevisionModel",
        foreign_keys=[
            task_id,
            current_team_revision_id,
            workflow_key,
            workflow_revision_no,
            workflow_content_hash,
        ],
        lazy="raise",
        viewonly=True,
    )
    result_boundary: Mapped[AcceptedBoundaryModel | None] = relationship(
        "AcceptedBoundaryModel",
        foreign_keys=[
            result_boundary_id,
            task_id,
            root_assignment_id,
            terminal_outcome,
        ],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )


class WorkspaceBindingModel(RuntimeBase):
    __tablename__ = "workspace_bindings"
    __table_args__ = (
        CheckConstraint(
            f"binding_mode IN ({sql_in(WORKSPACE_BINDING_MODE_VALUES)})",
            name="ck_workspace_bindings_mode",
        ),
    )

    workspace_binding_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), unique=True, index=True)
    binding_mode: Mapped[str] = mapped_column(String(64))
    normalized_root_path: Mapped[str] = mapped_column(Text)
    bound_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship(
        back_populates="workspace_binding",
        foreign_keys=[task_id],
        lazy="raise",
    )


__all__ = ["TaskModel", "WorkspaceBindingModel"]
