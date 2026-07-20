from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    AssignmentCriteriaRefModel,
    AssignmentModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import (
    RuntimeOperationError,
    missing_required_publication_error,
    stale_checkpoint_error,
)


async def require_current_assignment_criteria(
    session: AsyncSession,
    assignment: AssignmentModel,
) -> None:
    if not assignment.criteria_json:
        return
    rows = tuple(
        await session.scalars(
            select(AssignmentCriteriaRefModel)
            .where(AssignmentCriteriaRefModel.assignment_id == assignment.assignment_id)
            .order_by(AssignmentCriteriaRefModel.order_index)
        )
    )
    actual = {(row.slot, row.logical_path): row for row in rows}
    for expected in assignment.criteria_json:
        slot = expected.get("slot")
        path = expected.get("path")
        if not isinstance(slot, str) or not isinstance(path, str):
            raise stale_checkpoint_error(
                f"assignment '{assignment.assignment_key}' has invalid criteria truth"
            )
        row = actual.get((slot, path))
        if row is None:
            raise stale_checkpoint_error(
                f"assignment '{assignment.assignment_key}' is missing current criteria '{slot}'"
            )
        version = expected.get("version")
        if isinstance(version, int) and row.version != version:
            raise stale_checkpoint_error(
                f"assignment '{assignment.assignment_key}' has stale criteria '{slot}'"
            )


async def read_required_current_publications(
    session: AsyncSession,
    assignment: AssignmentModel,
) -> tuple[ArtifactPublicationModel, ...]:
    required_slots = _required_produce_slots(assignment)
    if not required_slots:
        return ()

    pointers = tuple(
        await session.scalars(
            select(ArtifactCurrentPointerModel).where(
                ArtifactCurrentPointerModel.task_id == assignment.task_id,
                ArtifactCurrentPointerModel.flow_id == assignment.flow_id,
                ArtifactCurrentPointerModel.assignment_id == assignment.assignment_id,
                ArtifactCurrentPointerModel.slot.in_(required_slots),
            )
        )
    )
    pointers_by_slot = {pointer.slot: pointer for pointer in pointers}
    publications: list[ArtifactPublicationModel] = []
    for slot in required_slots:
        pointer = pointers_by_slot.get(slot)
        if pointer is None:
            raise missing_required_publication_error(
                f"missing current publication '{slot}' for assignment '{assignment.assignment_key}'"
            )
        publication = await session.get(
            ArtifactPublicationModel,
            pointer.current_publication_id,
        )
        if (
            publication is None
            or publication.task_id != assignment.task_id
            or publication.flow_id != assignment.flow_id
            or publication.assignment_id != assignment.assignment_id
            or publication.slot != slot
            or publication.version != pointer.current_version
            or publication.attempt_id != pointer.attempt_id
            or publication.checkpoint_id != pointer.checkpoint_id
        ):
            raise stale_checkpoint_error(f"current publication '{slot}' changed release ownership")
        publications.append(publication)
    return tuple(publications)


def _required_produce_slots(assignment: AssignmentModel) -> tuple[str, ...]:
    slots: list[str] = []
    for requirement in assignment.produces_json:
        slot = requirement.get("slot")
        if not isinstance(slot, str) or not slot:
            raise RuntimeOperationError(
                code=OperationFailureCode.ILLEGAL_STATE,
                summary=(f"assignment '{assignment.assignment_key}' has invalid produce truth"),
                is_retryable=False,
            )
        if slot in slots:
            raise RuntimeOperationError(
                code=OperationFailureCode.ILLEGAL_STATE,
                summary=(f"assignment '{assignment.assignment_key}' repeats produce slot '{slot}'"),
                is_retryable=False,
            )
        slots.append(slot)
    return tuple(slots)


__all__ = [
    "read_required_current_publications",
    "require_current_assignment_criteria",
]
