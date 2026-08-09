from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import TaskEventModel
from banksia.runtime.contracts.primitives import TaskEventType
from banksia.runtime.contracts.prompt import PromptSteer
from banksia.runtime.contracts.task_event_payloads import MemberSteeredEventPayload


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
