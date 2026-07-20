from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from autoclaw.runtime.checkpoint import CheckpointPreparation
from autoclaw.runtime.contracts import (
    CommandRunStartResponse,
    HumanRequestOpenResponse,
)
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.node_operations.contracts import (
    NodeOperationName,
)
from autoclaw.runtime.post_commit.signals import (
    BoundaryAccepted,
    CommandRunPending,
    HumanRequestOpened,
    RuntimeEffectSignal,
)
from autoclaw.runtime.projection.signals import (
    ArtifactProjection,
    LatestCheckpointProjection,
    SupportProjectionSignal,
    TransientProjection,
)


class SupportProjectionPublisher(Protocol):
    """Nonblocking publication boundary for disposable support projections."""

    def publish(self, signal: SupportProjectionSignal) -> bool:
        """Attempt an in-process enqueue without waiting for projection work."""

        ...


@dataclass(frozen=True, slots=True)
class CommittedNodeOperationFollowOn:
    """Exact signals derivable from one already-committed Node operation."""

    runtime_signals: tuple[RuntimeEffectSignal, ...] = ()
    projection_signals: tuple[SupportProjectionSignal, ...] = ()

    def combined_with(
        self,
        other: CommittedNodeOperationFollowOn,
    ) -> CommittedNodeOperationFollowOn:
        return CommittedNodeOperationFollowOn(
            runtime_signals=(*self.runtime_signals, *other.runtime_signals),
            projection_signals=(*self.projection_signals, *other.projection_signals),
        )


class CommittedNodeOperationResult(BaseModel):
    """Internal committed response plus exact post-commit scheduling metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    response: BaseModel
    follow_on: CommittedNodeOperationFollowOn


def committed_node_operation_follow_on(
    *,
    operation_name: NodeOperationName,
    authority: NodeOperationAuthority,
    request: BaseModel,
    response: BaseModel,
    checkpoint_preparation: CheckpointPreparation | None,
) -> CommittedNodeOperationFollowOn:
    """Build exact post-commit hints without rereading broad task state."""

    if operation_name == NodeOperationName.RETURN_BOUNDARY:
        return CommittedNodeOperationFollowOn(
            runtime_signals=(BoundaryAccepted(authority.dispatch_id),),
        )
    if operation_name == NodeOperationName.OPEN_HUMAN_REQUEST:
        assert isinstance(response, HumanRequestOpenResponse)
        return CommittedNodeOperationFollowOn(
            runtime_signals=(HumanRequestOpened(response.request_id),),
        )
    if operation_name == NodeOperationName.START_COMMAND_RUN:
        assert isinstance(response, CommandRunStartResponse)
        return CommittedNodeOperationFollowOn(
            runtime_signals=(CommandRunPending(response.run_id),),
        )
    if operation_name == NodeOperationName.RECORD_CHECKPOINT:
        assert checkpoint_preparation is not None
        return CommittedNodeOperationFollowOn(
            projection_signals=(
                LatestCheckpointProjection(
                    attempt_id=checkpoint_preparation.attempt_id,
                    checkpoint_id=checkpoint_preparation.checkpoint_id,
                ),
                *(
                    ArtifactProjection(
                        artifact_publication_id=artifact.artifact_publication_id,
                        version=artifact.version,
                    )
                    for artifact in checkpoint_preparation.artifacts
                ),
                *(
                    TransientProjection(
                        transient_localization_id=transient.transient_localization_id,
                    )
                    for transient in checkpoint_preparation.transients
                ),
            ),
        )
    return CommittedNodeOperationFollowOn()


__all__ = [
    "CommittedNodeOperationFollowOn",
    "CommittedNodeOperationResult",
    "SupportProjectionPublisher",
    "committed_node_operation_follow_on",
]
