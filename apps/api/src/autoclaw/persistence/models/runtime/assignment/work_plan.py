from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.models.runtime.common import (
    WORK_PLAN_STEP_STATUS_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.assignment.execution import AssignmentModel
    from autoclaw.persistence.models.runtime.dispatch.turns import DispatchTurnModel


class AssignmentWorkPlanModel(RuntimeBase):
    __tablename__ = "assignment_work_plans"
    __table_args__ = (
        UniqueConstraint("assignment_id", "revision"),
        CheckConstraint("revision >= 1", name="ck_assignment_work_plans_revision"),
        ForeignKeyConstraint(
            ["assignment_id", "revision"],
            ["assignments.assignment_id", "assignments.work_plan_revision"],
            name="fk_assignment_work_plans_current_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["authoring_dispatch_id", "assignment_id"],
            ["dispatch_turns.dispatch_id", "dispatch_turns.assignment_id"],
            name="fk_assignment_work_plans_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("assignments.assignment_id"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    authoring_dispatch_id: Mapped[str] = mapped_column(String(255))
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    assignment: Mapped[AssignmentModel] = relationship(
        back_populates="work_plan",
        primaryjoin=(
            "and_(AssignmentWorkPlanModel.assignment_id == AssignmentModel.assignment_id, "
            "AssignmentWorkPlanModel.revision == AssignmentModel.work_plan_revision)"
        ),
        foreign_keys=[assignment_id, revision],
        lazy="raise",
        viewonly=True,
    )
    authoring_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="authored_work_plans",
        foreign_keys=[authoring_dispatch_id, assignment_id],
        lazy="raise",
        viewonly=True,
    )
    steps: Mapped[list[AssignmentWorkPlanStepModel]] = relationship(
        back_populates="work_plan",
        foreign_keys="AssignmentWorkPlanStepModel.assignment_id",
        lazy="raise",
        order_by="AssignmentWorkPlanStepModel.order_index",
    )


class AssignmentWorkPlanStepModel(RuntimeBase):
    __tablename__ = "assignment_work_plan_steps"
    __table_args__ = (
        UniqueConstraint("assignment_id", "order_index"),
        CheckConstraint("order_index BETWEEN 0 AND 8", name="ck_work_plan_steps_order"),
        CheckConstraint(
            f"status IN ({sql_in(WORK_PLAN_STEP_STATUS_VALUES)})",
            name="ck_work_plan_steps_status",
        ),
        Index(
            "uq_work_plan_steps_one_in_progress",
            "assignment_id",
            unique=True,
            sqlite_where=text("status = 'in_progress'"),
            postgresql_where=text("status = 'in_progress'"),
        ),
    )

    work_plan_step_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("assignment_work_plans.assignment_id"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    step: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64))
    work_plan: Mapped[AssignmentWorkPlanModel] = relationship(
        back_populates="steps",
        foreign_keys=[assignment_id],
        lazy="raise",
    )


__all__ = ["AssignmentWorkPlanModel", "AssignmentWorkPlanStepModel"]
