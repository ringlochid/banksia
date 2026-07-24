from __future__ import annotations

from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AttemptCheckpointModel,
    CheckpointFileReferenceModel,
    TaskModel,
)
from banksia.runtime.contracts import FileReference, TaskResult
from banksia.runtime.errors import illegal_state_error


async def read_task_result(
    session: AsyncSession,
    *,
    task_id: str,
) -> TaskResult | None:
    row = (
        await session.execute(
            select(AcceptedBoundaryModel, AttemptCheckpointModel)
            .join(
                TaskModel,
                (TaskModel.task_id == task_id)
                & (TaskModel.result_boundary_id == AcceptedBoundaryModel.accepted_boundary_id),
            )
            .join(
                AttemptCheckpointModel,
                (AttemptCheckpointModel.task_id == AcceptedBoundaryModel.task_id)
                & (AttemptCheckpointModel.assignment_id == AcceptedBoundaryModel.assignment_id)
                & (AttemptCheckpointModel.attempt_id == AcceptedBoundaryModel.attempt_id)
                & (AttemptCheckpointModel.checkpoint_id == AcceptedBoundaryModel.checkpoint_id),
            )
            .where(AcceptedBoundaryModel.task_id == task_id)
        )
    ).one_or_none()
    if row is None:
        return None
    boundary, checkpoint = row
    if boundary.outcome not in {"green", "blocked"}:
        raise illegal_state_error("Task Result selected a non-result boundary")
    files = await read_checkpoint_file_references(
        session,
        checkpoint_id=checkpoint.checkpoint_id,
    )
    return TaskResult(
        outcome=cast("Literal['green', 'blocked']", boundary.outcome),
        summary=checkpoint.summary,
        details=checkpoint.details,
        files=files,
        completed_at=boundary.committed_at,
    )


async def read_checkpoint_file_references(
    session: AsyncSession,
    *,
    checkpoint_id: str,
) -> tuple[FileReference, ...]:
    rows = tuple(
        await session.scalars(
            select(CheckpointFileReferenceModel)
            .where(CheckpointFileReferenceModel.checkpoint_id == checkpoint_id)
            .order_by(CheckpointFileReferenceModel.order_index)
        )
    )
    return tuple(FileReference(path=row.path, description=row.description) for row in rows)


__all__ = [
    "read_checkpoint_file_references",
    "read_task_result",
]
