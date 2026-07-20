from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.models.runtime.common import (
    ASSIGNMENT_DECISION_KIND_VALUES,
    BOUNDARY_OUTCOME_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.assignment.artifacts import (
        ArtifactPublicationModel,
    )
    from autoclaw.persistence.models.runtime.assignment.execution import (
        AssignmentModel,
        AttemptCheckpointModel,
        AttemptModel,
    )
    from autoclaw.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from autoclaw.persistence.models.runtime.flow.runtime import FlowRevisionModel


class AssignmentDecisionModel(RuntimeBase):
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
        UniqueConstraint("assignment_decision_id", "task_id", "flow_id"),
        CheckConstraint(
            f"decision_kind IN ({sql_in(ASSIGNMENT_DECISION_KIND_VALUES)})",
            name="ck_assignment_decisions_kind",
        ),
        CheckConstraint(
            "(decision_kind = 'staged_child' AND staged_child_assignment_id IS NOT NULL AND "
            "staged_child_attempt_id IS NOT NULL) OR "
            "(decision_kind IN ('release_green', 'release_blocked') AND "
            "staged_child_assignment_id IS NULL AND staged_child_attempt_id IS NULL)",
            name="ck_assignment_decisions_kind_ownership",
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
    decision_kind: Mapped[str] = mapped_column(String(64))
    staged_child_assignment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    staged_child_attempt_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
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
    staged_child_assignment: Mapped[AssignmentModel | None] = relationship(
        "AssignmentModel",
        foreign_keys=[task_id, flow_id, staged_child_assignment_id],
        lazy="raise",
        viewonly=True,
    )
    staged_child_attempt: Mapped[AttemptModel | None] = relationship(
        "AttemptModel",
        foreign_keys=[task_id, flow_id, staged_child_assignment_id, staged_child_attempt_id],
        lazy="raise",
        viewonly=True,
    )
    checkpoint_evidence: Mapped[list[AssignmentDecisionCheckpointModel]] = relationship(
        back_populates="assignment_decision",
        foreign_keys=(
            "[AssignmentDecisionCheckpointModel.assignment_decision_id, "
            "AssignmentDecisionCheckpointModel.task_id, "
            "AssignmentDecisionCheckpointModel.flow_id]"
        ),
        lazy="raise",
        order_by="AssignmentDecisionCheckpointModel.order_index",
        viewonly=True,
    )
    artifact_evidence: Mapped[list[AssignmentDecisionArtifactModel]] = relationship(
        back_populates="assignment_decision",
        foreign_keys=(
            "[AssignmentDecisionArtifactModel.assignment_decision_id, "
            "AssignmentDecisionArtifactModel.task_id, AssignmentDecisionArtifactModel.flow_id]"
        ),
        lazy="raise",
        order_by="AssignmentDecisionArtifactModel.order_index",
        viewonly=True,
    )


class AcceptedBoundaryModel(RuntimeBase):
    __tablename__ = "accepted_boundaries"
    __table_args__ = (
        UniqueConstraint("source_dispatch_id"),
        CheckConstraint(
            f"outcome IN ({sql_in(BOUNDARY_OUTCOME_VALUES)})",
            name="ck_accepted_boundaries_outcome",
        ),
        CheckConstraint(
            "outcome = 'yield' OR checkpoint_id IS NOT NULL",
            name="ck_accepted_boundaries_terminal_checkpoint",
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
            ["source_dispatch_id", "successor_dispatch_id"],
            ["dispatch_turns.predecessor_dispatch_id", "dispatch_turns.dispatch_id"],
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
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
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
        foreign_keys=[source_dispatch_id, successor_dispatch_id],
        lazy="raise",
        viewonly=True,
    )


class AssignmentDecisionCheckpointModel(RuntimeBase):
    __tablename__ = "assignment_decision_checkpoints"
    __table_args__ = (
        UniqueConstraint("assignment_decision_id", "checkpoint_id"),
        UniqueConstraint("assignment_decision_id", "order_index"),
        CheckConstraint(
            "order_index >= 0",
            name="ck_assignment_decision_checkpoints_order_index",
        ),
        ForeignKeyConstraint(
            ["assignment_decision_id", "task_id", "flow_id"],
            [
                "assignment_decisions.assignment_decision_id",
                "assignment_decisions.task_id",
                "assignment_decisions.flow_id",
            ],
            name="fk_assignment_decision_checkpoints_decision_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "flow_id",
                "evidence_assignment_id",
                "evidence_attempt_id",
                "checkpoint_id",
            ],
            [
                "attempt_checkpoints.task_id",
                "attempt_checkpoints.flow_id",
                "attempt_checkpoints.assignment_id",
                "attempt_checkpoints.attempt_id",
                "attempt_checkpoints.checkpoint_id",
            ],
            name="fk_assignment_decision_checkpoints_checkpoint_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    assignment_decision_checkpoint_id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
    )
    assignment_decision_id: Mapped[str] = mapped_column(String(255), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"))
    evidence_assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"))
    evidence_attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"))
    checkpoint_id: Mapped[str] = mapped_column(ForeignKey("attempt_checkpoints.checkpoint_id"))
    order_index: Mapped[int] = mapped_column(Integer)
    assignment_decision: Mapped[AssignmentDecisionModel] = relationship(
        back_populates="checkpoint_evidence",
        foreign_keys=[assignment_decision_id, task_id, flow_id],
        lazy="raise",
        viewonly=True,
    )
    checkpoint: Mapped[AttemptCheckpointModel] = relationship(
        "AttemptCheckpointModel",
        foreign_keys=[
            task_id,
            flow_id,
            evidence_assignment_id,
            evidence_attempt_id,
            checkpoint_id,
        ],
        lazy="raise",
        viewonly=True,
    )


class AssignmentDecisionArtifactModel(RuntimeBase):
    __tablename__ = "assignment_decision_artifacts"
    __table_args__ = (
        UniqueConstraint("assignment_decision_id", "artifact_publication_id"),
        UniqueConstraint("assignment_decision_id", "order_index"),
        CheckConstraint(
            "order_index >= 0",
            name="ck_assignment_decision_artifacts_order_index",
        ),
        ForeignKeyConstraint(
            ["assignment_decision_id", "task_id", "flow_id"],
            [
                "assignment_decisions.assignment_decision_id",
                "assignment_decisions.task_id",
                "assignment_decisions.flow_id",
            ],
            name="fk_assignment_decision_artifacts_decision_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "artifact_publication_id",
                "task_id",
                "flow_id",
                "evidence_assignment_id",
                "evidence_attempt_id",
                "checkpoint_id",
                "slot",
                "version",
            ],
            [
                "artifact_publications.artifact_publication_id",
                "artifact_publications.task_id",
                "artifact_publications.flow_id",
                "artifact_publications.assignment_id",
                "artifact_publications.attempt_id",
                "artifact_publications.checkpoint_id",
                "artifact_publications.slot",
                "artifact_publications.version",
            ],
            name="fk_assignment_decision_artifacts_publication_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    assignment_decision_artifact_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    assignment_decision_id: Mapped[str] = mapped_column(String(255), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"))
    evidence_assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.assignment_id"))
    evidence_attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"))
    checkpoint_id: Mapped[str] = mapped_column(ForeignKey("attempt_checkpoints.checkpoint_id"))
    slot: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer)
    artifact_publication_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_publications.artifact_publication_id")
    )
    order_index: Mapped[int] = mapped_column(Integer)
    assignment_decision: Mapped[AssignmentDecisionModel] = relationship(
        back_populates="artifact_evidence",
        foreign_keys=[assignment_decision_id, task_id, flow_id],
        lazy="raise",
        viewonly=True,
    )
    artifact_publication: Mapped[ArtifactPublicationModel] = relationship(
        "ArtifactPublicationModel",
        foreign_keys=[
            artifact_publication_id,
            task_id,
            flow_id,
            evidence_assignment_id,
            evidence_attempt_id,
            checkpoint_id,
            slot,
            version,
        ],
        lazy="raise",
        viewonly=True,
    )


__all__ = [
    "AcceptedBoundaryModel",
    "AssignmentDecisionArtifactModel",
    "AssignmentDecisionCheckpointModel",
    "AssignmentDecisionModel",
]
