from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import TaskModel, TaskStartSourceModel
from oh_my_subagents.runtime.contracts import RuntimeBootstrapInput, RuntimeBootstrapResult
from oh_my_subagents.runtime.launch.bootstrap.projection import build_launch_bootstrap_result
from oh_my_subagents.runtime.launch.bootstrap.rows import stage_launch_bootstrap_rows
from oh_my_subagents.runtime.launch.persistence.attempts import stage_launch_attempt_rows


async def persist_bootstrap_runtime_from_precomputed(
    session: AsyncSession,
    bootstrap_input: RuntimeBootstrapInput,
    *,
    should_commit: bool = True,
) -> RuntimeBootstrapResult:
    result = build_launch_bootstrap_result(bootstrap_input)
    await stage_launch_bootstrap_rows(
        session,
        bootstrap_input=bootstrap_input,
        result=result,
    )
    assignment = await stage_launch_attempt_rows(
        session,
        bootstrap_input=bootstrap_input,
        result=result,
    )
    session.add(
        TaskStartSourceModel(
            task_id=bootstrap_input.task_id,
            root_assignment_id=assignment.assignment_id,
            root_attempt_id=bootstrap_input.attempt_id,
            successor_dispatch_id=None,
        )
    )
    await session.execute(
        update(TaskModel)
        .where(TaskModel.task_id == bootstrap_input.task_id)
        .values(
            current_team_revision_id=bootstrap_input.initial_team.team_revision_id,
            root_assignment_id=assignment.assignment_id,
        )
    )
    await session.flush()
    if should_commit:
        await session.commit()
    return result
