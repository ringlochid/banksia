from __future__ import annotations

from dataclasses import dataclass

from autoclaw.runtime.contracts import CheckpointWriteBody, TaskRootPaths


@dataclass(frozen=True, slots=True)
class ArtifactBodyPreparation:
    artifact_publication_id: str
    slot: str
    description: str
    source_logical_path: str
    final_logical_path: str
    version: int
    observed_pointer_id: str | None
    observed_publication_id: str | None
    observed_version: int | None
    observed_attempt_id: str | None
    observed_checkpoint_id: str | None


@dataclass(frozen=True, slots=True)
class TransientBodyPreparation:
    transient_localization_id: str
    source_logical_path: str
    final_logical_path: str
    description: str
    order_index: int


@dataclass(frozen=True, slots=True)
class CheckpointPreparation:
    checkpoint_id: str
    task_id: str
    flow_id: str
    assignment_id: str
    attempt_id: str
    dispatch_id: str
    observed_latest_checkpoint_id: str | None
    body: CheckpointWriteBody
    paths: TaskRootPaths | None
    artifacts: tuple[ArtifactBodyPreparation, ...]
    transients: tuple[TransientBodyPreparation, ...]


__all__ = [
    "ArtifactBodyPreparation",
    "CheckpointPreparation",
    "TransientBodyPreparation",
]
