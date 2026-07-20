from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.persistence.models import TaskModel, WorkspaceBindingModel
from autoclaw.runtime.contracts import TaskRootPaths
from autoclaw.runtime.errors import illegal_state_error, missing_resource_error
from autoclaw.runtime.task_root.paths import ensure_task_root_layout


async def load_task_root_paths(session: AsyncSession, task_id: str) -> TaskRootPaths:
    paths = await read_task_root_paths(session, task_id)
    ensure_task_root_layout(paths)
    return paths


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
    runtime_path = task_root / "_runtime"
    outputs_path = task_root / "outputs"
    transfers_path = task_root / "tmp" / "transfers"
    return TaskRootPaths(
        task_root=task_root,
        workspace_path=Path(workspace_binding.normalized_root_path),
        outputs_path=outputs_path,
        artifacts_path=outputs_path / "artifacts",
        tmp_path=task_root / "tmp",
        transfers_path=transfers_path,
        localized_path=transfers_path / "localized",
        runtime_path=runtime_path,
        criteria_path=runtime_path / "criteria",
        attempts_path=runtime_path / "attempts",
        dispatch_path=runtime_path / "dispatch",
    )


__all__ = ["load_task_root_paths", "read_task_root_paths"]
