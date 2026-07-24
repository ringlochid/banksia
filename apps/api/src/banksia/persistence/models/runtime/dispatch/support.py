from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import (
    BOUNDARY_OUTCOME_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.assignment.execution import (
        AssignmentModel,
        AttemptCheckpointModel,
        AttemptModel,
    )
    from banksia.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from banksia.persistence.models.runtime.flow.runtime import FlowRevisionModel


class AssignmentDecisionModel(RuntimeBase):
    """Temporary staged-child decision retained with the yield bridge until WP-08."""

    __tablename__ = "assignment_decisions"
    __table_args__ = (
        UniqueConstraint("source_dispatch_id"),
        UniqueConstraint(
            "assignment_decision_id",
            "source_dispatch_id",
            "task_id",
            "assignment_id",
            "attempt_id",
        ),
        CheckConstraint(
            "decision_kind = 'staged_child'",
            name="ck_assignment_decisions_kind",
        ),
        CheckConstraint(
            "staged_child_assignment_id IS NOT NULL AND staged_child_attempt_id IS NOT NULL",
            name="ck_assignment_decisions_staged_child",
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
            name="fk_assignment_decisions_source_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["flow_id", "source_flow_revision_id"],
            ["flow_revisions.flow_id", "flow_revisions.flow_revision_id"],
            name="fk_assignment_decisions_flow_revision_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["staged_child_assignment_id", "assignment_id", "source_dispatch_id"],
            [
                "assignments.assignment_id",
                "assignments.parent_assignment_id",
                "assignments.created_by_dispatch_id",
            ],
            name="fk_assignment_decisions_child_authoring_source",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "staged_child_assignment_id"],
            ["assignments.task_id", "assignments.flow_id", "assignments.assignment_id"],
            name="fk_assignment_decisions_child_assignment_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "staged_child_assignment_id", "staged_child_attempt_id"],
            [
                "attempts.task_id",
                "attempts.flow_id",
                "attempts.assignment_id",
                "attempts.attempt_id",
            ],
            name="fk_assignment_decisions_child_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    assignment_decision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"))
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"))
    source_flow_revision_id: Mapped[str] = mapped_column(String(255))
    decision_kind: Mapped[str] = mapped_column(
        String(64),
        default="staged_child",
        server_default="staged_child",
    )
    staged_child_assignment_id: Mapped[str] = mapped_column(String(255))
    staged_child_attempt_id: Mapped[str] = mapped_column(String(255))
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="assignment_decision",
        foreign_keys=[source_dispatch_id, task_id, flow_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    source_flow_revision: Mapped[FlowRevisionModel] = relationship(
        "FlowRevisionModel",
        foreign_keys=[flow_id, source_flow_revision_id],
        lazy="raise",
        viewonly=True,
    )
    staged_child_assignment: Mapped[AssignmentModel] = relationship(
        "AssignmentModel",
        foreign_keys=[task_id, flow_id, staged_child_assignment_id],
        lazy="raise",
        viewonly=True,
    )
    staged_child_attempt: Mapped[AttemptModel] = relationship(
        "AttemptModel",
        foreign_keys=[task_id, flow_id, staged_child_assignment_id, staged_child_attempt_id],
        lazy="raise",
        viewonly=True,
    )


class AcceptedBoundaryModel(RuntimeBase):
    """Internal exact terminal/yield boundary selected by committed controller truth."""

    __tablename__ = "accepted_boundaries"
    __table_args__ = (
        UniqueConstraint("source_dispatch_id"),
        UniqueConstraint("accepted_boundary_id", "task_id"),
        UniqueConstraint(
            "successor_dispatch_id",
            name="uq_accepted_boundaries_successor_dispatch",
        ),
        CheckConstraint(
            f"outcome IN ({sql_in(BOUNDARY_OUTCOME_VALUES)})",
            name="ck_accepted_boundaries_outcome",
        ),
        CheckConstraint(
            "(outcome = 'yield' AND checkpoint_id IS NULL AND "
            "assignment_decision_id IS NOT NULL) OR "
            "(outcome IN ('green', 'blocked', 'retry') AND "
            "checkpoint_id IS NOT NULL AND assignment_decision_id IS NULL)",
            name="ck_accepted_boundaries_source_shape",
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
            name="fk_accepted_boundaries_source_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "assignment_id", "attempt_id", "checkpoint_id"],
            [
                "attempt_checkpoints.task_id",
                "attempt_checkpoints.assignment_id",
                "attempt_checkpoints.attempt_id",
                "attempt_checkpoints.checkpoint_id",
            ],
            name="fk_accepted_boundaries_checkpoint_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "assignment_decision_id",
                "source_dispatch_id",
                "task_id",
                "assignment_id",
                "attempt_id",
            ],
            [
                "assignment_decisions.assignment_decision_id",
                "assignment_decisions.source_dispatch_id",
                "assignment_decisions.task_id",
                "assignment_decisions.assignment_id",
                "assignment_decisions.attempt_id",
            ],
            name="fk_accepted_boundaries_decision_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["successor_dispatch_id"],
            ["dispatch_turns.dispatch_id"],
            name="fk_accepted_boundaries_successor_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    accepted_boundary_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"))
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"))
    outcome: Mapped[str] = mapped_column(String(64))
    checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assignment_decision_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    successor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="accepted_boundary",
        foreign_keys=[source_dispatch_id, task_id, flow_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    checkpoint: Mapped[AttemptCheckpointModel | None] = relationship(
        "AttemptCheckpointModel",
        foreign_keys=[task_id, assignment_id, attempt_id, checkpoint_id],
        lazy="raise",
        viewonly=True,
    )
    assignment_decision: Mapped[AssignmentDecisionModel | None] = relationship(
        "AssignmentDecisionModel",
        foreign_keys=[
            assignment_decision_id,
            source_dispatch_id,
            task_id,
            assignment_id,
            attempt_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    successor_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        foreign_keys=[successor_dispatch_id],
        lazy="raise",
        viewonly=True,
    )


__all__ = ["AcceptedBoundaryModel", "AssignmentDecisionModel"]
