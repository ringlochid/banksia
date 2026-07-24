from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import utcnow

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.assignment.execution import (
        AssignmentModel,
        AttemptModel,
    )
    from banksia.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from banksia.persistence.models.runtime.task import TaskModel


class TaskStartSourceModel(RuntimeBase):
    """The exact root lane and first Dispatch source selected at Task start."""

    __tablename__ = "task_start_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "root_assignment_id"],
            ["assignments.task_id", "assignments.assignment_id"],
            name="fk_task_start_sources_root_assignment",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "root_assignment_id", "root_attempt_id"],
            ["attempts.task_id", "attempts.assignment_id", "attempts.attempt_id"],
            name="fk_task_start_sources_root_attempt",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "successor_dispatch_id"],
            ["dispatch_turns.task_start_source_task_id", "dispatch_turns.dispatch_id"],
            name="fk_task_start_sources_successor_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), primary_key=True)
    root_assignment_id: Mapped[str] = mapped_column(String(255))
    root_attempt_id: Mapped[str] = mapped_column(String(255))
    successor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship("TaskModel", foreign_keys=[task_id], lazy="raise")
    root_assignment: Mapped[AssignmentModel] = relationship(
        "AssignmentModel",
        foreign_keys=[task_id, root_assignment_id],
        lazy="raise",
        viewonly=True,
    )
    root_attempt: Mapped[AttemptModel] = relationship(
        "AttemptModel",
        foreign_keys=[task_id, root_assignment_id, root_attempt_id],
        lazy="raise",
        viewonly=True,
    )
    successor_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        foreign_keys=[task_id, successor_dispatch_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )


__all__ = ["TaskStartSourceModel"]
