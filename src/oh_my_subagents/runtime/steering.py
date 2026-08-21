from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import TaskEventModel
from oh_my_subagents.runtime.contracts.primitives import TaskEventType
from oh_my_subagents.runtime.contracts.prompt import PromptSteer
from oh_my_subagents.runtime.contracts.task_event_payloads import MemberSteeredEventPayload


async def read_assignment_prompt_steers(
    session: AsyncSession,
    *,
    assignment_id: str,
) -> tuple[PromptSteer, ...]:
    rows = tuple(
        await session.scalars(
            select(TaskEventModel)
            .where(
                TaskEventModel.event_type == TaskEventType.MEMBER_STEERED.value,
                TaskEventModel.payload["assignment_id"].as_string() == assignment_id,
            )
            .order_by(TaskEventModel.event_seq)
        )
    )
    return tuple(
        PromptSteer(
            message=MemberSteeredEventPayload.model_validate(row.payload).message,
            occurred_at=row.occurred_at,
        )
        for row in rows
    )


__all__ = ["read_assignment_prompt_steers"]
