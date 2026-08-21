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

from oh_my_subagents.persistence.base import RuntimeBase
from oh_my_subagents.persistence.datetimes import UtcDateTime
from oh_my_subagents.persistence.models.runtime.common import (
    BOUNDARY_OUTCOME_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from oh_my_subagents.persistence.models.runtime.assignment.execution import (
        AttemptCheckpointModel,
        AttemptModel,
    )
    from oh_my_subagents.persistence.models.runtime.dispatch.turns import DispatchTurnModel


class AcceptedBoundaryModel(RuntimeBase):
    """Internal exact terminal boundary selected by committed controller truth."""

    __tablename__ = "accepted_boundaries"
    __table_args__ = (
        UniqueConstraint("source_dispatch_id"),
        UniqueConstraint("accepted_boundary_id", "task_id"),
        UniqueConstraint(
            "accepted_boundary_id",
            "task_id",
            "assignment_id",
            "outcome",
            name="uq_accepted_boundaries_terminal_owner",
        ),
        UniqueConstraint(
            "successor_dispatch_id",
            name="uq_accepted_boundaries_successor_dispatch",
        ),
        UniqueConstraint(
            "successor_attempt_id",
            name="uq_accepted_boundaries_successor_attempt",
        ),
        CheckConstraint(
            f"outcome IN ({sql_in(BOUNDARY_OUTCOME_VALUES)})",
            name="ck_accepted_boundaries_outcome",
        ),
        CheckConstraint(
            "checkpoint_id IS NOT NULL",
            name="ck_accepted_boundaries_source_shape",
        ),
        CheckConstraint(
            "(outcome = 'retry' AND successor_attempt_id IS NOT NULL AND "
            "successor_dispatch_id IS NOT NULL) OR "
            "(outcome IN ('green', 'blocked') AND successor_attempt_id IS NULL AND "
            "successor_dispatch_id IS NULL)",
            name="ck_accepted_boundaries_successor_shape",
        ),
        ForeignKeyConstraint(
            ["source_dispatch_id", "task_id", "assignment_id", "attempt_id"],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
            ],
            name="fk_accepted_boundaries_source_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "assignment_id",
                "attempt_id",
                "checkpoint_id",
                "source_dispatch_id",
                "outcome",
            ],
            [
                "attempt_checkpoints.task_id",
                "attempt_checkpoints.assignment_id",
                "attempt_checkpoints.attempt_id",
                "attempt_checkpoints.checkpoint_id",
                "attempt_checkpoints.authoring_dispatch_id",
                "attempt_checkpoints.outcome",
            ],
            name="fk_accepted_boundaries_checkpoint_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "assignment_id",
                "successor_attempt_id",
                "attempt_id",
            ],
            [
                "attempts.task_id",
                "attempts.assignment_id",
                "attempts.attempt_id",
                "attempts.retry_of_attempt_id",
            ],
            name="fk_accepted_boundaries_retry_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "successor_dispatch_id",
                "task_id",
                "assignment_id",
                "successor_attempt_id",
            ],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
            ],
            name="fk_accepted_boundaries_successor_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    accepted_boundary_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"))
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"))
    outcome: Mapped[str] = mapped_column(String(64))
    checkpoint_id: Mapped[str] = mapped_column(String(255))
    successor_attempt_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    successor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="accepted_boundary",
        foreign_keys=[source_dispatch_id, task_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    checkpoint: Mapped[AttemptCheckpointModel] = relationship(
        "AttemptCheckpointModel",
        foreign_keys=[
            task_id,
            assignment_id,
            attempt_id,
            checkpoint_id,
            source_dispatch_id,
            outcome,
        ],
        lazy="raise",
        viewonly=True,
    )
    successor_attempt: Mapped[AttemptModel | None] = relationship(
        "AttemptModel",
        foreign_keys=[
            task_id,
            assignment_id,
            successor_attempt_id,
            attempt_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    successor_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        foreign_keys=[
            successor_dispatch_id,
            task_id,
            assignment_id,
            successor_attempt_id,
        ],
        lazy="raise",
        viewonly=True,
    )


__all__ = ["AcceptedBoundaryModel"]
