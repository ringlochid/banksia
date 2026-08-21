from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import AssignmentFileReferenceModel
from oh_my_subagents.runtime.contracts import FileReference


def stage_assignment_file_references(
    session: AsyncSession,
    *,
    assignment_id: str,
    files: tuple[FileReference, ...],
) -> None:
    """Stage immutable ordered values owned only by one Assignment."""

    session.add_all(
        AssignmentFileReferenceModel(
            assignment_id=assignment_id,
            order_index=order_index,
            path=file.path,
            description=file.description,
        )
        for order_index, file in enumerate(files)
    )


async def read_assignment_file_references(
    session: AsyncSession,
    *,
    assignment_id: str,
) -> tuple[FileReference, ...]:
    rows = tuple(
        await session.scalars(
            select(AssignmentFileReferenceModel)
            .where(AssignmentFileReferenceModel.assignment_id == assignment_id)
            .order_by(AssignmentFileReferenceModel.order_index)
        )
    )
    return tuple(FileReference(path=row.path, description=row.description) for row in rows)


__all__ = [
    "read_assignment_file_references",
    "stage_assignment_file_references",
]
