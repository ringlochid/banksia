from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    DispatchTurnModel,
    MemberConfigurationModel,
)
from banksia.runtime.contracts.task import TaskMemberReference


async def read_source_member_reference(
    session: AsyncSession,
    *,
    task_id: str,
    source_dispatch_id: str,
) -> TaskMemberReference | None:
    return (
        await read_source_member_references(
            session,
            task_id=task_id,
            source_dispatch_ids=(source_dispatch_id,),
        )
    ).get(source_dispatch_id)


async def read_source_member_references(
    session: AsyncSession,
    *,
    task_id: str,
    source_dispatch_ids: Iterable[str],
) -> dict[str, TaskMemberReference]:
    dispatch_ids = tuple(dict.fromkeys(source_dispatch_ids))
    if not dispatch_ids:
        return {}
    rows = await session.execute(
        select(
            DispatchTurnModel.dispatch_id,
            DispatchTurnModel.member_id,
            MemberConfigurationModel.title,
            MemberConfigurationModel.description,
        )
        .join(
            MemberConfigurationModel,
            (
                MemberConfigurationModel.member_configuration_id
                == DispatchTurnModel.member_configuration_id
            )
            & (MemberConfigurationModel.task_id == DispatchTurnModel.task_id)
            & (MemberConfigurationModel.member_id == DispatchTurnModel.member_id),
        )
        .where(
            DispatchTurnModel.task_id == task_id,
            DispatchTurnModel.dispatch_id.in_(dispatch_ids),
        )
    )
    return {
        dispatch_id: TaskMemberReference(
            id=member_id,
            name=title or description or "Team member",
        )
        for dispatch_id, member_id, title, description in rows
    }


__all__ = [
    "read_source_member_reference",
    "read_source_member_references",
]
