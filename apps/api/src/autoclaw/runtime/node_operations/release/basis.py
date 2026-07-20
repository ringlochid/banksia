from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    ArtifactPublicationModel,
    AssignmentDecisionArtifactModel,
    AssignmentDecisionCheckpointModel,
    AttemptCheckpointModel,
)
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority


@dataclass(frozen=True)
class ReleaseBasis:
    checkpoints: tuple[AttemptCheckpointModel, ...]
    artifacts: tuple[ArtifactPublicationModel, ...]


def add_release_basis_rows(
    session: AsyncSession,
    *,
    authority: NodeOperationAuthority,
    assignment_decision_id: str,
    basis: ReleaseBasis,
) -> None:
    for order_index, checkpoint in enumerate(basis.checkpoints):
        session.add(
            AssignmentDecisionCheckpointModel(
                assignment_decision_checkpoint_id=(f"assignment-decision-checkpoint.{uuid4().hex}"),
                assignment_decision_id=assignment_decision_id,
                task_id=authority.task_id,
                flow_id=authority.flow_id,
                evidence_assignment_id=checkpoint.assignment_id,
                evidence_attempt_id=checkpoint.attempt_id,
                checkpoint_id=checkpoint.checkpoint_id,
                order_index=order_index,
            )
        )
    for order_index, publication in enumerate(basis.artifacts):
        session.add(
            AssignmentDecisionArtifactModel(
                assignment_decision_artifact_id=(f"assignment-decision-artifact.{uuid4().hex}"),
                assignment_decision_id=assignment_decision_id,
                task_id=authority.task_id,
                flow_id=authority.flow_id,
                evidence_assignment_id=publication.assignment_id,
                evidence_attempt_id=publication.attempt_id,
                checkpoint_id=publication.checkpoint_id,
                slot=publication.slot,
                version=publication.version,
                artifact_publication_id=publication.artifact_publication_id,
                order_index=order_index,
            )
        )


__all__ = ["ReleaseBasis", "add_release_basis_rows"]
