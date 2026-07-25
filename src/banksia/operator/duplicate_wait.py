from __future__ import annotations

import asyncio
from time import monotonic

from sqlalchemy import func, select

from banksia.operator.conversation_reads import OperatorSessionFactory
from banksia.operator.errors import (
    OperatorConversationNotFoundError,
    OperatorTurnInProgressError,
)
from banksia.operator.persistence import OperatorTurnClaim
from banksia.persistence.models import (
    OperatorConversationEntryModel,
    OperatorConversationModel,
)

_DUPLICATE_WAIT_INITIAL_SECONDS = 0.05
_DUPLICATE_WAIT_MAX_SECONDS = 0.25
_DUPLICATE_WAIT_TIMEOUT_SECONDS = 2.0
_monotonic = monotonic
_sleep = asyncio.sleep


async def wait_for_active_duplicate(
    session_factory: OperatorSessionFactory,
    *,
    claim: OperatorTurnClaim,
) -> None:
    duplicate_sequence = claim.active_duplicate_sequence
    if duplicate_sequence is None:
        return

    deadline = _monotonic() + _DUPLICATE_WAIT_TIMEOUT_SECONDS
    delay = _DUPLICATE_WAIT_INITIAL_SECONDS
    latest_sequence_query = (
        select(func.max(OperatorConversationEntryModel.sequence))
        .where(
            OperatorConversationEntryModel.conversation_id
            == OperatorConversationModel.conversation_id
        )
        .scalar_subquery()
    )

    while True:
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(
                        OperatorConversationModel.state,
                        latest_sequence_query,
                    ).where(OperatorConversationModel.conversation_id == claim.conversation_id)
                )
            ).one_or_none()
        if row is None:
            raise OperatorConversationNotFoundError(claim.conversation_id)
        conversation_state, latest_sequence = row
        if conversation_state != "running" or latest_sequence != duplicate_sequence:
            return

        remaining = deadline - _monotonic()
        if remaining <= 0:
            raise OperatorTurnInProgressError(
                "the matching Operator turn is still running; reload the conversation"
            )
        await _sleep(min(delay, remaining))
        delay = min(delay * 2, _DUPLICATE_WAIT_MAX_SECONDS)


__all__ = ["wait_for_active_duplicate"]
