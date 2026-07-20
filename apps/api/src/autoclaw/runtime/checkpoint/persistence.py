from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

from sqlalchemy import exists, insert, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    AttemptCheckpointModel,
    AttemptModel,
    CheckpointTransientModel,
    TransientLocalizationModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import TaskEventSource, TaskEventType
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.task_events import append_task_event

from .models import ArtifactBodyPreparation, CheckpointPreparation


async def commit_checkpoint_preparation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
) -> None:
    _validate_preparation(authority, preparation)
    now = utc_now()
    evidence = _checkpoint_evidence(preparation)
    try:
        await _persist_checkpoint_rows(
            session,
            authority,
            preparation,
            evidence=evidence,
            now=now,
        )
        await _append_checkpoint_recorded_event(session, authority, preparation, occurred_at=now)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if not _is_expected_checkpoint_conflict(exc):
            raise
        raise _checkpoint_conflict(
            "another checkpoint won the final controller transaction"
        ) from exc
    except RuntimeOperationError:
        await session.rollback()
        raise


def _checkpoint_evidence(preparation: CheckpointPreparation) -> dict[str, object]:
    handoff = preparation.body.handoff
    return {
        "next_step": handoff.next_step,
        "blockers": list(handoff.blockers),
        "risks": list(handoff.risks),
    }


async def _persist_checkpoint_rows(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
    *,
    evidence: dict[str, object],
    now: datetime,
) -> None:
    await _insert_checkpoint(session, authority, preparation, evidence=evidence, now=now)
    for artifact in preparation.artifacts:
        await _insert_artifact_publication(
            session,
            authority,
            preparation,
            artifact,
            now=now,
        )
        await _advance_artifact_pointer(
            session,
            authority,
            preparation,
            artifact,
            now=now,
        )
    await _insert_transient_localizations(session, authority, preparation, now=now)
    await _advance_attempt_latest_checkpoint(session, authority, preparation)


async def _append_checkpoint_recorded_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
    *,
    occurred_at: datetime,
) -> None:
    body = preparation.body
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.CHECKPOINT_RECORDED,
        event_source=TaskEventSource.NODE,
        occurred_at=occurred_at,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "checkpoint_id": preparation.checkpoint_id,
            "assignment_id": authority.assignment_id,
            "attempt_id": authority.attempt_id,
            "checkpoint_kind": body.checkpoint_kind.value,
            "outcome": body.outcome.value if body.outcome is not None else None,
            "summary": body.handoff.summary,
            "checkpoint_ref": f"_runtime/attempts/{authority.attempt_id}/latest-checkpoint.md",
            "produced_artifacts": [
                {
                    "publication_id": artifact.artifact_publication_id,
                    "slot": artifact.slot,
                    "path": artifact.final_logical_path,
                    "version": artifact.version,
                }
                for artifact in preparation.artifacts
            ],
            "transient_surfaces": [
                {
                    "localization_id": transient.transient_localization_id,
                    "path": transient.final_logical_path,
                    "description": transient.description,
                }
                for transient in preparation.transients
            ],
            "authored_by_dispatch_id": authority.dispatch_id,
        },
    )


async def _insert_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
    *,
    evidence: dict[str, object],
    now: datetime,
) -> None:
    table = AttemptCheckpointModel.__table__
    inserted_id = await session.scalar(
        insert(AttemptCheckpointModel)
        .from_select(
            (
                "checkpoint_id",
                "task_id",
                "flow_id",
                "assignment_id",
                "attempt_id",
                "authoring_dispatch_id",
                "checkpoint_kind",
                "outcome",
                "summary",
                "evidence_json",
                "criteria_results_json",
                "recorded_at",
            ),
            select(
                literal(preparation.checkpoint_id),
                literal(authority.task_id),
                literal(authority.flow_id),
                literal(authority.assignment_id),
                literal(authority.attempt_id),
                literal(authority.dispatch_id),
                literal(preparation.body.checkpoint_kind.value),
                literal(
                    preparation.body.outcome.value if preparation.body.outcome else None,
                    type_=table.c.outcome.type,
                ),
                literal(preparation.body.handoff.summary),
                literal(evidence, type_=table.c.evidence_json.type),
                literal([], type_=table.c.criteria_results_json.type),
                literal(now, type_=table.c.recorded_at.type),
            ).where(
                exact_node_operation_authority_exists(authority),
                exists(
                    select(AttemptModel.attempt_id).where(
                        AttemptModel.task_id == authority.task_id,
                        AttemptModel.flow_id == authority.flow_id,
                        AttemptModel.assignment_id == authority.assignment_id,
                        AttemptModel.attempt_id == authority.attempt_id,
                        _nullable_equal(
                            AttemptModel.latest_checkpoint_id,
                            preparation.observed_latest_checkpoint_id,
                        ),
                    )
                ),
            ),
        )
        .returning(table.c.checkpoint_id)
    )
    if inserted_id is None:
        raise _checkpoint_conflict("another transition changed checkpoint authority")


async def _insert_artifact_publication(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
    artifact: ArtifactBodyPreparation,
    *,
    now: datetime,
) -> None:
    await session.execute(
        insert(ArtifactPublicationModel).values(
            artifact_publication_id=artifact.artifact_publication_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            checkpoint_id=preparation.checkpoint_id,
            slot=artifact.slot,
            version=artifact.version,
            logical_path=artifact.final_logical_path,
            description=artifact.description,
            supersedes_publication_id=artifact.observed_publication_id,
            supersedes_version=artifact.observed_version,
            published_at=now,
        )
    )


async def _insert_transient_localizations(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
    *,
    now: datetime,
) -> None:
    for transient in preparation.transients:
        await session.execute(
            insert(TransientLocalizationModel).values(
                transient_localization_id=transient.transient_localization_id,
                task_id=authority.task_id,
                flow_id=authority.flow_id,
                assignment_id=authority.assignment_id,
                attempt_id=authority.attempt_id,
                checkpoint_id=preparation.checkpoint_id,
                source_logical_path=transient.source_logical_path,
                localized_logical_path=transient.final_logical_path,
                description=transient.description,
                retention_status="active",
                localized_at=now,
                expires_at=None,
                removed_at=None,
            )
        )
        await session.execute(
            insert(CheckpointTransientModel).values(
                checkpoint_transient_id=f"checkpoint-transient.{uuid4().hex}",
                task_id=authority.task_id,
                assignment_id=authority.assignment_id,
                attempt_id=authority.attempt_id,
                checkpoint_id=preparation.checkpoint_id,
                transient_localization_id=transient.transient_localization_id,
                order_index=transient.order_index,
            )
        )


async def _advance_attempt_latest_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
) -> None:
    updated_attempt = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.task_id == authority.task_id,
            AttemptModel.flow_id == authority.flow_id,
            AttemptModel.assignment_id == authority.assignment_id,
            AttemptModel.attempt_id == authority.attempt_id,
            AttemptModel.status.in_(("pending", "running")),
            _nullable_equal(
                AttemptModel.latest_checkpoint_id,
                preparation.observed_latest_checkpoint_id,
            ),
            exact_node_operation_authority_exists(authority),
        )
        .values(latest_checkpoint_id=preparation.checkpoint_id)
        .returning(AttemptModel.attempt_id)
    )
    if updated_attempt is None:
        raise _checkpoint_conflict("another checkpoint changed the attempt latest pointer")


async def _advance_artifact_pointer(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
    artifact: ArtifactBodyPreparation,
    *,
    now: datetime,
) -> None:
    if artifact.observed_pointer_id is None:
        table = ArtifactCurrentPointerModel.__table__
        pointer_id = f"artifact-current-pointer.{uuid4().hex}"
        advanced = await session.scalar(
            insert(ArtifactCurrentPointerModel)
            .from_select(
                tuple(column.name for column in table.c),
                select(
                    literal(pointer_id),
                    literal(authority.task_id),
                    literal(authority.flow_id),
                    literal(authority.assignment_id),
                    literal(artifact.slot),
                    literal(artifact.artifact_publication_id),
                    literal(artifact.version),
                    literal(authority.attempt_id),
                    literal(preparation.checkpoint_id),
                    literal(now, type_=table.c.updated_at.type),
                ).where(
                    exact_node_operation_authority_exists(authority),
                    ~exists(
                        select(ArtifactCurrentPointerModel.artifact_current_pointer_id).where(
                            ArtifactCurrentPointerModel.task_id == authority.task_id,
                            ArtifactCurrentPointerModel.assignment_id == authority.assignment_id,
                            ArtifactCurrentPointerModel.slot == artifact.slot,
                        )
                    ),
                ),
            )
            .returning(table.c.artifact_current_pointer_id)
        )
    else:
        advanced = await session.scalar(
            update(ArtifactCurrentPointerModel)
            .where(
                ArtifactCurrentPointerModel.artifact_current_pointer_id
                == artifact.observed_pointer_id,
                ArtifactCurrentPointerModel.task_id == authority.task_id,
                ArtifactCurrentPointerModel.flow_id == authority.flow_id,
                ArtifactCurrentPointerModel.assignment_id == authority.assignment_id,
                ArtifactCurrentPointerModel.slot == artifact.slot,
                ArtifactCurrentPointerModel.current_publication_id
                == artifact.observed_publication_id,
                ArtifactCurrentPointerModel.current_version == artifact.observed_version,
                ArtifactCurrentPointerModel.attempt_id == artifact.observed_attempt_id,
                ArtifactCurrentPointerModel.checkpoint_id == artifact.observed_checkpoint_id,
                exact_node_operation_authority_exists(authority),
            )
            .values(
                current_publication_id=artifact.artifact_publication_id,
                current_version=artifact.version,
                attempt_id=authority.attempt_id,
                checkpoint_id=preparation.checkpoint_id,
                updated_at=now,
            )
            .returning(ArtifactCurrentPointerModel.artifact_current_pointer_id)
        )
    if advanced is None:
        raise _checkpoint_conflict(f"artifact slot '{artifact.slot}' changed before commit")


def _validate_preparation(
    authority: NodeOperationAuthority,
    preparation: CheckpointPreparation,
) -> None:
    if (
        preparation.task_id,
        preparation.flow_id,
        preparation.assignment_id,
        preparation.attempt_id,
        preparation.dispatch_id,
    ) != (
        authority.task_id,
        authority.flow_id,
        authority.assignment_id,
        authority.attempt_id,
        authority.dispatch_id,
    ):
        raise _checkpoint_conflict("prepared checkpoint no longer matches exact dispatch authority")


def _nullable_equal(
    column: InstrumentedAttribute[str | None],
    value: str | None,
) -> ColumnElement[bool]:
    if value is None:
        return column.is_(None)
    return column == value


def _checkpoint_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


def _is_expected_checkpoint_conflict(exc: IntegrityError) -> bool:
    original = exc.orig
    diagnostics = getattr(original, "diag", None)
    constraint_name = getattr(diagnostics, "constraint_name", None)
    if constraint_name in {
        "artifact_current_pointers_task_id_assignment_id_slot_key",
        "artifact_publications_task_id_assignment_id_slot_version_key",
    }:
        return True
    return isinstance(original, sqlite3.IntegrityError) and (
        getattr(original, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE
    )


__all__ = ["commit_checkpoint_preparation"]
