from __future__ import annotations

import errno
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import TaskModel
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.contracts import TaskEventSource, TaskEventType
from oh_my_subagents.runtime.control_transitions import close_current_task_dispatches
from oh_my_subagents.runtime.task_events import append_task_event
from oh_my_subagents.runtime.workspace.storage import open_banksia_root, open_task_root

_UNAVAILABLE_ERRNOS = frozenset(
    {
        errno.EACCES,
        errno.ENOENT,
        errno.ENOTDIR,
        errno.EPERM,
        errno.ESTALE,
        errno.ELOOP,
    }
)


def normalized_workspace_root(workspace: Path | str) -> Path:
    """Return one absolute, expanded workspace root without requiring it to exist."""

    return Path(os.path.abspath(os.fspath(Path(workspace).expanduser())))


def task_workspace_is_available(task_root_path: Path, *, task_id: str) -> bool:
    """Probe an existing Task root without creating or repairing workspace files."""

    workspace = task_workspace_root(task_root_path, task_id=task_id)
    try:
        with open_banksia_root(workspace, should_create=False) as banksia_root:
            if banksia_root is None:
                return False
            with open_task_root(banksia_root, task_id):
                return True
    except OSError as exc:
        if is_workspace_unavailable_error(exc):
            return False
        raise


def task_workspace_root(task_root_path: Path, *, task_id: str) -> Path:
    """Return the persisted workspace root after proving the Task path shape."""

    if (
        not task_root_path.is_absolute()
        or task_root_path.name != task_id
        or task_root_path.parent.name != ".banksia"
    ):
        raise RuntimeError(f"Task {task_id!r} has an inconsistent persisted Task root")
    return task_root_path.parent.parent


async def pause_task_for_unavailable_workspace(
    session: AsyncSession,
    *,
    task_id: str,
    workspace: Path,
    paused_at: datetime | None = None,
) -> bool:
    """Atomically pause one running Task whose existing workspace cannot be opened."""

    transition_time = paused_at or utc_now()
    row = (
        await session.execute(
            update(TaskModel)
            .where(
                TaskModel.task_id == task_id,
                TaskModel.status == "running",
            )
            .values(
                status="paused",
                pause_reason="workspace_unavailable",
                pause_details={
                    "failure_code": "workspace_unavailable",
                    "workspace": str(workspace),
                },
                paused_at=transition_time,
                paused_by_actor_ref="controller.runtime",
                control_revision=TaskModel.control_revision + 1,
                updated_at=transition_time,
            )
            .returning(
                TaskModel.current_team_revision_id,
                TaskModel.control_revision,
            )
        )
    ).one_or_none()
    if row is None:
        await session.rollback()
        return False

    team_revision_id, control_revision = row
    if team_revision_id is None:
        await session.rollback()
        raise RuntimeError(f"running Task {task_id!r} has no current Team revision")
    try:
        await close_current_task_dispatches(
            session,
            task_id=task_id,
            closed_reason="paused",
            closed_at=transition_time,
        )
        await append_task_event(
            session,
            task_id=task_id,
            event_type=TaskEventType.TASK_PAUSED,
            event_source=TaskEventSource.CONTROLLER,
            occurred_at=transition_time,
            team_revision_id=team_revision_id,
            actor_ref="controller.runtime",
            payload={
                "pause_reason": "workspace_unavailable",
                "control_revision": control_revision,
                "actor_ref": "controller.runtime",
                "summary": "Paused because the Task workspace is unavailable.",
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return True


def is_workspace_unavailable_error(error: OSError) -> bool:
    """Return whether one filesystem error means the Task workspace is unavailable."""

    return isinstance(error, (FileNotFoundError, NotADirectoryError, PermissionError)) or (
        error.errno in _UNAVAILABLE_ERRNOS
    )


__all__ = [
    "is_workspace_unavailable_error",
    "normalized_workspace_root",
    "pause_task_for_unavailable_workspace",
    "task_workspace_is_available",
    "task_workspace_root",
]
