from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import CommandRunModel
from autoclaw.runtime.command_run.transitions import terminalize_command_run
from autoclaw.runtime.contracts import CommandRunState


async def abandon_unowned_command_run(
    session: AsyncSession,
    source: CommandRunModel,
    *,
    ended_at: datetime,
) -> bool:
    """Terminalize one live source whose local process ownership is unprovable."""

    state = CommandRunState(source.state)
    if state not in {
        CommandRunState.PENDING_START,
        CommandRunState.RUNNING,
        CommandRunState.CANCELLATION_REQUESTED,
    }:
        return False
    return await terminalize_command_run(
        session,
        task_id=source.task_id,
        run_id=source.run_id,
        expected_ownership_revision=source.ownership_revision,
        expected_states=(state,),
        terminal_state=CommandRunState.ABANDONED,
        summary="The controller restarted without provable ownership of the command process.",
        failure_code="command_ownership_lost",
        ended_at=ended_at,
    )


__all__ = ["abandon_unowned_command_run"]
