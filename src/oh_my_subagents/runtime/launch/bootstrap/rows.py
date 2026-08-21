from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    TaskEventStreamHeadModel,
    TaskModel,
    WorkspaceBindingModel,
)
from oh_my_subagents.runtime.contracts import RuntimeBootstrapInput, RuntimeBootstrapResult
from oh_my_subagents.runtime.team import materialize_initial_task_team


async def stage_launch_bootstrap_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    result: RuntimeBootstrapResult,
) -> None:
    """Stage Task-owned launch rows and the immutable initial Team."""

    session.add(
        TaskModel(
            task_id=bootstrap_input.task_id,
            workflow_key=bootstrap_input.workflow_revision.workflow_id,
            workflow_revision_no=bootstrap_input.workflow_revision.revision_no,
            workflow_content_hash=bootstrap_input.workflow_revision.content_hash,
            status="running",
            current_team_revision_id=None,
            root_assignment_id=None,
            max_child_assignments_per_assignment=(
                bootstrap_input.max_child_assignments_per_assignment
            ),
            max_retries_per_assignment=bootstrap_input.max_retries_per_assignment,
            max_wave_members=bootstrap_input.max_wave_members,
            task_root_path=str(result.paths.task_root),
        )
    )
    await session.flush()
    materialized = await materialize_initial_task_team(
        session,
        bootstrap_input.workflow_revision,
        task_id=bootstrap_input.task_id,
    )
    if materialized != bootstrap_input.initial_team:
        raise ValueError("initial Team materialization changed its admitted plan")
    session.add(TaskEventStreamHeadModel(task_id=bootstrap_input.task_id))
    session.add(
        WorkspaceBindingModel(
            task_id=bootstrap_input.task_id,
            normalized_root_path=str(bootstrap_input.workspace),
        )
    )
    await session.flush()


__all__ = ["stage_launch_bootstrap_rows"]
