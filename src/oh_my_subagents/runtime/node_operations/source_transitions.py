from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.dispatch.authority import NodeOperationAuthority
from oh_my_subagents.runtime.dispatch.currentness import (
    AttemptDispatchIdentity,
    close_current_attempt_dispatch,
)
from oh_my_subagents.runtime.errors import RuntimeOperationError


async def close_source_dispatch(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    now: datetime,
    closed_reason: str,
) -> None:
    closed = await close_current_attempt_dispatch(
        session,
        identity=AttemptDispatchIdentity(
            task_id=authority.task_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            dispatch_id=authority.dispatch_id,
        ),
        expected_team_revision_id=authority.team_revision_id,
        closed_at=now,
        closed_reason=closed_reason,
    )
    if not closed:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition already changed current Attempt authority",
            is_retryable=False,
        )


__all__ = ["close_source_dispatch"]
