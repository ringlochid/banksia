from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import AcceptedBoundaryModel, DispatchTurnModel


async def read_accepted_green_participation(
    session: AsyncSession,
    *,
    task_id: str,
    member_id: str,
    member_configuration_id: str,
    member_branch_basis_id: str,
) -> bool:
    """Return whether exact current Member basis has an accepted green return."""

    boundary_id = await session.scalar(
        select(AcceptedBoundaryModel.accepted_boundary_id)
        .join(
            DispatchTurnModel,
            DispatchTurnModel.dispatch_id == AcceptedBoundaryModel.source_dispatch_id,
        )
        .where(
            AcceptedBoundaryModel.task_id == task_id,
            AcceptedBoundaryModel.outcome == "green",
            DispatchTurnModel.task_id == task_id,
            DispatchTurnModel.member_id == member_id,
            DispatchTurnModel.member_configuration_id == member_configuration_id,
            DispatchTurnModel.member_branch_basis_id == member_branch_basis_id,
        )
        .limit(1)
    )
    return boundary_id is not None


__all__ = ["read_accepted_green_participation"]
