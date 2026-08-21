from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import AcceptedBoundaryModel, DispatchTurnModel

type ParticipationBasis = tuple[str, str, str, str]


async def read_accepted_green_participation(
    session: AsyncSession,
    *,
    task_id: str,
    member_id: str,
    member_configuration_id: str,
    member_branch_basis_id: str,
) -> bool:
    """Return whether exact current Member basis has an accepted green return."""

    basis = (task_id, member_id, member_configuration_id, member_branch_basis_id)
    return basis in await read_accepted_green_participation_bases(
        session,
        bases=(basis,),
    )


async def read_accepted_green_participation_bases(
    session: AsyncSession,
    *,
    bases: Collection[ParticipationBasis],
) -> frozenset[ParticipationBasis]:
    """Return exact Member bases with an accepted green return in one query."""

    if not bases:
        return frozenset()
    rows = await session.execute(
        select(
            DispatchTurnModel.task_id,
            DispatchTurnModel.member_id,
            DispatchTurnModel.member_configuration_id,
            DispatchTurnModel.member_branch_basis_id,
        )
        .select_from(AcceptedBoundaryModel)
        .join(
            DispatchTurnModel,
            DispatchTurnModel.dispatch_id == AcceptedBoundaryModel.source_dispatch_id,
        )
        .where(
            AcceptedBoundaryModel.outcome == "green",
            tuple_(
                DispatchTurnModel.task_id,
                DispatchTurnModel.member_id,
                DispatchTurnModel.member_configuration_id,
                DispatchTurnModel.member_branch_basis_id,
            ).in_(tuple(bases)),
        )
    )
    return frozenset(
        (task_id, member_id, configuration_id, branch_basis_id)
        for task_id, member_id, configuration_id, branch_basis_id in rows
    )


__all__ = [
    "ParticipationBasis",
    "read_accepted_green_participation",
    "read_accepted_green_participation_bases",
]
