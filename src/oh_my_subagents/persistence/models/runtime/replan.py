from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
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
    REPLAN_MANIFEST_STATE_VALUES,
    REPLAN_OPERATION_VALUES,
    REPLAN_SUCCESSOR_STATE_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from oh_my_subagents.persistence.models.runtime.assignment.execution import (
        AssignmentModel,
        AttemptModel,
    )
    from oh_my_subagents.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from oh_my_subagents.persistence.models.runtime.task import TaskModel
    from oh_my_subagents.persistence.models.runtime.team import TeamRevisionModel


class ReplanTransitionModel(RuntimeBase):
    """Durable barrier between one accepted Team replan and its fresh Dispatch."""

    __tablename__ = "replan_transitions"
    __table_args__ = (
        UniqueConstraint("source_dispatch_id", name="uq_replan_transitions_source_dispatch"),
        UniqueConstraint(
            "successor_dispatch_id",
            name="uq_replan_transitions_successor_dispatch",
        ),
        CheckConstraint(
            f"operation IN ({sql_in(REPLAN_OPERATION_VALUES)})",
            name="ck_replan_transitions_operation",
        ),
        CheckConstraint(
            f"manifest_state IN ({sql_in(REPLAN_MANIFEST_STATE_VALUES)})",
            name="ck_replan_transitions_manifest_state",
        ),
        CheckConstraint(
            f"successor_state IN ({sql_in(REPLAN_SUCCESSOR_STATE_VALUES)})",
            name="ck_replan_transitions_successor_state",
        ),
        CheckConstraint(
            "manifest_state = 'pending' AND successor_state = 'blocked' OR "
            "manifest_state = 'repair_required' AND successor_state = 'blocked' OR "
            "manifest_state = 'current' AND successor_state = 'pending' OR "
            "manifest_state = 'current' AND successor_state = 'opening_failed' OR "
            "manifest_state = 'current' AND successor_state = 'opened' OR "
            "successor_state = 'cancelled'",
            name="ck_replan_transitions_barrier_state",
        ),
        CheckConstraint(
            "(successor_state = 'opened' AND successor_dispatch_id IS NOT NULL AND "
            "successor_opened_at IS NOT NULL) OR "
            "(successor_state != 'opened' AND successor_dispatch_id IS NULL AND "
            "successor_opened_at IS NULL)",
            name="ck_replan_transitions_successor_shape",
        ),
        CheckConstraint(
            "(failure_code IS NULL AND failure_detail IS NULL) OR "
            "(failure_code IS NOT NULL AND failure_detail IS NOT NULL)",
            name="ck_replan_transitions_failure_pair",
        ),
        CheckConstraint(
            "manifest_state = 'repair_required' AND failure_code IS NOT NULL OR "
            "successor_state = 'opening_failed' AND failure_code IS NOT NULL OR "
            "manifest_state != 'repair_required' AND "
            "successor_state != 'opening_failed' AND failure_code IS NULL",
            name="ck_replan_transitions_failure_state",
        ),
        ForeignKeyConstraint(
            ["task_id", "assignment_id"],
            ["assignments.task_id", "assignments.assignment_id"],
            name="fk_replan_transitions_assignment_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "assignment_id", "attempt_id"],
            ["attempts.task_id", "attempts.assignment_id", "attempts.attempt_id"],
            name="fk_replan_transitions_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "source_dispatch_id",
                "task_id",
                "assignment_id",
                "attempt_id",
            ],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
            ],
            name="fk_replan_transitions_source_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "successor_dispatch_id",
                "task_id",
                "assignment_id",
                "attempt_id",
                "successor_team_revision_id",
            ],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
                "dispatch_turns.team_revision_id",
            ],
            name="fk_replan_transitions_successor_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["source_dispatch_id", "successor_dispatch_id"],
            ["dispatch_turns.predecessor_dispatch_id", "dispatch_turns.dispatch_id"],
            name="fk_replan_transitions_successor_lineage",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "source_team_revision_id"],
            ["team_revisions.task_id", "team_revisions.team_revision_id"],
            name="fk_replan_transitions_source_team_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "successor_team_revision_id"],
            ["team_revisions.task_id", "team_revisions.team_revision_id"],
            name="fk_replan_transitions_successor_team_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "successor_team_revision_id", "source_team_revision_id"],
            [
                "team_revisions.task_id",
                "team_revisions.team_revision_id",
                "team_revisions.predecessor_team_revision_id",
            ],
            name="fk_replan_transitions_successor_team_predecessor",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    replan_transition_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    normalized_request_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    committed_result_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    source_team_revision_id: Mapped[str] = mapped_column(String(255))
    successor_team_revision_id: Mapped[str] = mapped_column(String(255))
    manifest_state: Mapped[str] = mapped_column(String(64), default="pending")
    successor_state: Mapped[str] = mapped_column(String(64), default="blocked")
    successor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    manifest_current_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    successor_opened_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    task: Mapped[TaskModel] = relationship("TaskModel", foreign_keys=[task_id], lazy="raise")
    assignment: Mapped[AssignmentModel] = relationship(
        "AssignmentModel",
        foreign_keys=[task_id, assignment_id],
        lazy="raise",
        viewonly=True,
    )
    attempt: Mapped[AttemptModel] = relationship(
        "AttemptModel",
        foreign_keys=[task_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        foreign_keys=[
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
        foreign_keys=[
            successor_dispatch_id,
            task_id,
            assignment_id,
            attempt_id,
            successor_team_revision_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    source_team_revision: Mapped[TeamRevisionModel] = relationship(
        "TeamRevisionModel",
        foreign_keys=[task_id, source_team_revision_id],
        lazy="raise",
        viewonly=True,
    )
    successor_team_revision: Mapped[TeamRevisionModel] = relationship(
        "TeamRevisionModel",
        foreign_keys=[task_id, successor_team_revision_id],
        lazy="raise",
        viewonly=True,
    )


__all__ = ["ReplanTransitionModel"]
