from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from oh_my_subagents.persistence.models import DispatchTurnModel, ReplanTransitionModel
from oh_my_subagents.runtime.contracts import ReplanSuccess

_REPLAN_OPERATION_NAMES = frozenset(("add_child", "update_child", "remove_child"))


async def read_committed_replan_replay(
    session: AsyncSession,
    *,
    task_id: str,
    dispatch_id: str,
    provider_start_revision: int | None,
    operation_name: str,
    request: BaseModel,
) -> ReplanSuccess | None:
    """Return an exact committed replan readback for duplicate transport delivery."""

    if operation_name not in _REPLAN_OPERATION_NAMES:
        return None
    if provider_start_revision is None:
        return None
    transition = await session.scalar(
        select(ReplanTransitionModel)
        .join(
            DispatchTurnModel,
            DispatchTurnModel.dispatch_id == ReplanTransitionModel.source_dispatch_id,
        )
        .options(raiseload("*"))
        .where(
            ReplanTransitionModel.task_id == task_id,
            ReplanTransitionModel.source_dispatch_id == dispatch_id,
            ReplanTransitionModel.operation == operation_name,
            DispatchTurnModel.provider_start_revision == provider_start_revision,
        )
    )
    if transition is None:
        return None
    normalized_request = request.model_dump(mode="json", exclude_unset=True)
    if transition.normalized_request_json != normalized_request:
        return None
    return ReplanSuccess.model_validate(transition.committed_result_json)


__all__ = ["read_committed_replan_replay"]
