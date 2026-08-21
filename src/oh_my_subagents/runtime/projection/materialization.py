from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import TaskModel, TeamRevisionModel
from oh_my_subagents.runtime.projection.signals import (
    SupportProjectionSignal,
    WorkflowManifestProjection,
)
from oh_my_subagents.runtime.task_root.reads import read_task_root_paths
from oh_my_subagents.runtime.team import render_current_team_manifest
from oh_my_subagents.runtime.workspace.storage import replace_task_text


async def project_support_signal(
    session: AsyncSession,
    signal: SupportProjectionSignal,
) -> None:
    """Materialize the one retained controller projection from a fresh read."""

    if not isinstance(signal, WorkflowManifestProjection):
        raise TypeError(f"unsupported support projection signal: {type(signal).__name__}")
    await project_workflow_manifest(session, signal)


async def project_workflow_manifest(
    session: AsyncSession,
    signal: WorkflowManifestProjection,
) -> bool:
    task = await session.get(TaskModel, signal.task_id)
    if task is None or task.current_team_revision_id != signal.team_revision_id:
        return False
    revision = await session.get(TeamRevisionModel, signal.team_revision_id)
    if revision is None or revision.task_id != task.task_id:
        return False

    content = await render_current_team_manifest(session, task_id=task.task_id)
    paths = await read_task_root_paths(session, task.task_id)
    replace_task_text(
        paths.workspace_path,
        task.task_id,
        "manifest.md",
        content,
    )
    return True


__all__ = ["project_support_signal", "project_workflow_manifest"]
