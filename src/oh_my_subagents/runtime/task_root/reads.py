from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from oh_my_subagents.persistence.models import TaskModel, WorkspaceBindingModel
from oh_my_subagents.runtime.contracts import TaskRootPaths
from oh_my_subagents.runtime.errors import illegal_state_error, missing_resource_error


async def read_task_root_paths(session: AsyncSession, task_id: str) -> TaskRootPaths:
    row = cast(
        tuple[TaskModel, WorkspaceBindingModel | None] | None,
        (
            await session.execute(
                select(TaskModel, WorkspaceBindingModel)
                .options(raiseload("*"))
                .outerjoin(
                    WorkspaceBindingModel,
                    WorkspaceBindingModel.task_id == TaskModel.task_id,
                )
                .where(TaskModel.task_id == task_id)
            )
        ).one_or_none(),
    )
    if row is None:
        raise missing_resource_error(f"unknown task_id '{task_id}'")

    task, workspace_binding = row
    if workspace_binding is None:
        raise illegal_state_error(f"task '{task_id}' is missing its workspace binding")
    return _task_root_paths(task, workspace_binding)


def _task_root_paths(
    task: TaskModel,
    workspace_binding: WorkspaceBindingModel,
) -> TaskRootPaths:
    task_root = Path(task.task_root_path)
    return TaskRootPaths(
        task_root=task_root,
        workspace_path=Path(workspace_binding.normalized_root_path),
    )


__all__ = ["read_task_root_paths"]
