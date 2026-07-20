from __future__ import annotations

import re
from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    AssignmentDecisionModel,
    AttemptCheckpointModel,
)
from autoclaw.runtime.contracts import CheckpointWriteBody
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import (
    RuntimeOperationError,
    illegal_state_error,
    missing_required_publication_error,
)
from autoclaw.runtime.task_root.file_access import publish_logical_regular_file
from autoclaw.runtime.task_root.reads import read_task_root_paths

from .models import (
    ArtifactBodyPreparation,
    CheckpointPreparation,
    TransientBodyPreparation,
)

_SAFE_SUFFIX = re.compile(r"\.[A-Za-z0-9][A-Za-z0-9._-]{0,31}")


async def plan_checkpoint_preparation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    body: CheckpointWriteBody,
) -> CheckpointPreparation:
    declared = _declared_artifacts(authority)
    claimed_slots = {claim.slot for claim in body.produced_artifacts}
    undeclared = claimed_slots.difference(declared)
    if undeclared:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_STATE,
            summary=f"checkpoint claims undeclared artifact slot '{min(undeclared)}'",
            is_retryable=False,
        )
    if (
        body.checkpoint_kind.value == "terminal"
        and body.outcome is not None
        and body.outcome.value == "green"
    ):
        missing = declared.keys() - claimed_slots
        if missing:
            raise missing_required_publication_error(
                "terminal green checkpoint is missing required artifact "
                f"publication '{min(missing)}'"
            )
    await require_legal_checkpoint_successor(session, authority, body)
    _require_safe_segment(authority.node_key, label="node key")
    paths = await read_task_root_paths(session, authority.task_id)
    checkpoint_id = f"checkpoint.{uuid4().hex}"
    artifacts: list[ArtifactBodyPreparation] = []
    for artifact_claim in body.produced_artifacts:
        _require_safe_segment(artifact_claim.slot, label="artifact slot")
        pointer = await session.scalar(
            select(ArtifactCurrentPointerModel).where(
                ArtifactCurrentPointerModel.task_id == authority.task_id,
                ArtifactCurrentPointerModel.flow_id == authority.flow_id,
                ArtifactCurrentPointerModel.assignment_id == authority.assignment_id,
                ArtifactCurrentPointerModel.slot == artifact_claim.slot,
            )
        )
        version = 1 if pointer is None else pointer.current_version + 1
        publication_id = f"artifact-publication.{uuid4().hex}"
        artifacts.append(
            ArtifactBodyPreparation(
                artifact_publication_id=publication_id,
                slot=artifact_claim.slot,
                description=declared[artifact_claim.slot],
                source_logical_path=artifact_claim.path,
                final_logical_path=(
                    f"outputs/artifacts/{authority.node_key}/{artifact_claim.slot}/"
                    f"{publication_id}{_safe_suffix(artifact_claim.path)}"
                ),
                version=version,
                observed_pointer_id=(
                    pointer.artifact_current_pointer_id if pointer is not None else None
                ),
                observed_publication_id=(
                    pointer.current_publication_id if pointer is not None else None
                ),
                observed_version=pointer.current_version if pointer is not None else None,
                observed_attempt_id=pointer.attempt_id if pointer is not None else None,
                observed_checkpoint_id=pointer.checkpoint_id if pointer is not None else None,
            )
        )
    transients: list[TransientBodyPreparation] = []
    for index, transient_claim in enumerate(body.transient_surfaces):
        localization_id = f"transient-localization.{uuid4().hex}"
        transients.append(
            TransientBodyPreparation(
                transient_localization_id=localization_id,
                source_logical_path=transient_claim.path,
                final_logical_path=(
                    f"tmp/transfers/localized/{localization_id}{_safe_suffix(transient_claim.path)}"
                ),
                description=transient_claim.description,
                order_index=index,
            )
        )
    return CheckpointPreparation(
        checkpoint_id=checkpoint_id,
        task_id=authority.task_id,
        flow_id=authority.flow_id,
        assignment_id=authority.assignment_id,
        attempt_id=authority.attempt_id,
        dispatch_id=authority.dispatch_id,
        observed_latest_checkpoint_id=authority.attempt.latest_checkpoint_id,
        body=body,
        paths=paths,
        artifacts=tuple(artifacts),
        transients=tuple(transients),
    )


async def publish_checkpoint_bodies(
    preparation: CheckpointPreparation,
) -> CheckpointPreparation:
    if not preparation.artifacts and not preparation.transients:
        return preparation
    assert preparation.paths is not None
    _publish_checkpoint_bodies(preparation)
    return preparation


def empty_checkpoint_preparation(
    authority: NodeOperationAuthority,
    body: CheckpointWriteBody,
) -> CheckpointPreparation:
    if body.produced_artifacts or body.transient_surfaces:
        raise illegal_state_error(
            "checkpoint bodies were not prepared before the final transaction"
        )
    return CheckpointPreparation(
        checkpoint_id=f"checkpoint.{uuid4().hex}",
        task_id=authority.task_id,
        flow_id=authority.flow_id,
        assignment_id=authority.assignment_id,
        attempt_id=authority.attempt_id,
        dispatch_id=authority.dispatch_id,
        observed_latest_checkpoint_id=authority.attempt.latest_checkpoint_id,
        body=body,
        paths=None,
        artifacts=(),
        transients=(),
    )


def _publish_checkpoint_bodies(preparation: CheckpointPreparation) -> None:
    assert preparation.paths is not None
    for artifact in preparation.artifacts:
        publish_logical_regular_file(
            preparation.paths,
            artifact.source_logical_path,
            artifact.final_logical_path,
        )
    for transient in preparation.transients:
        publish_logical_regular_file(
            preparation.paths,
            transient.source_logical_path,
            transient.final_logical_path,
        )


def _declared_artifacts(authority: NodeOperationAuthority) -> dict[str, str]:
    result: dict[str, str] = {}
    for requirement in authority.assignment.produces_json:
        slot = requirement.get("slot")
        description = requirement.get("description")
        if not isinstance(slot, str) or not slot or slot in result:
            raise illegal_state_error("current assignment has invalid artifact produce truth")
        result[slot] = description if isinstance(description, str) and description else slot
    return result


async def require_legal_checkpoint_successor(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    body: CheckpointWriteBody,
) -> None:
    decision_kind = await session.scalar(
        select(AssignmentDecisionModel.decision_kind).where(
            AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id
        )
    )
    if decision_kind in {"release_green", "release_blocked"}:
        raise illegal_state_error(
            "the terminal release decision freezes checkpoint evidence for this dispatch"
        )
    if decision_kind == "staged_child" and body.checkpoint_kind.value == "terminal":
        raise illegal_state_error(
            "a staged-child continuation may publish only a progress checkpoint before yield"
        )

    latest_checkpoint_id = authority.attempt.latest_checkpoint_id
    if latest_checkpoint_id is None:
        return
    latest = await session.get(AttemptCheckpointModel, latest_checkpoint_id)
    if (
        latest is not None
        and latest.task_id == authority.task_id
        and latest.flow_id == authority.flow_id
        and latest.assignment_id == authority.assignment_id
        and latest.attempt_id == authority.attempt_id
        and latest.checkpoint_kind == "terminal"
        and body.checkpoint_kind.value != "terminal"
    ):
        raise illegal_state_error(
            "a terminal checkpoint may be corrected only by a later terminal checkpoint"
        )


def _require_safe_segment(value: str, *, label: str) -> None:
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise illegal_state_error(f"current {label} is not safe for task-root publication")


def _safe_suffix(logical_path: str) -> str:
    suffix = PurePosixPath(logical_path).suffix
    return suffix if _SAFE_SUFFIX.fullmatch(suffix) else ""


__all__ = [
    "empty_checkpoint_preparation",
    "plan_checkpoint_preparation",
    "publish_checkpoint_bodies",
    "require_legal_checkpoint_successor",
]
