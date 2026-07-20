from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import AttemptCheckpointModel, AttemptModel
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority


async def read_exact_latest_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> AttemptCheckpointModel | None:
    return cast(
        AttemptCheckpointModel | None,
        await session.scalar(
            select(AttemptCheckpointModel)
            .join(
                AttemptModel,
                (
                    (AttemptModel.task_id == AttemptCheckpointModel.task_id)
                    & (AttemptModel.flow_id == AttemptCheckpointModel.flow_id)
                    & (AttemptModel.assignment_id == AttemptCheckpointModel.assignment_id)
                    & (AttemptModel.attempt_id == AttemptCheckpointModel.attempt_id)
                    & (AttemptModel.latest_checkpoint_id == AttemptCheckpointModel.checkpoint_id)
                ),
            )
            .where(
                AttemptModel.task_id == authority.task_id,
                AttemptModel.flow_id == authority.flow_id,
                AttemptModel.assignment_id == authority.assignment_id,
                AttemptModel.attempt_id == authority.attempt_id,
                AttemptCheckpointModel.authoring_dispatch_id == authority.dispatch_id,
            )
        ),
    )


__all__ = ["read_exact_latest_checkpoint"]
