"""Controller-owned Task lifecycle operations."""

from __future__ import annotations

from oh_my_subagents.runtime.task_control.continuation import continue_paused_task
from oh_my_subagents.runtime.task_control.service import (
    cancel_runtime_task,
    continue_runtime_task,
    list_runtime_tasks,
    pause_runtime_task,
    runtime_task_read,
)

WORKFLOW_MANIFEST_REF_DESCRIPTION = "Whole-workflow visible contract for the current task."

__all__ = [
    "WORKFLOW_MANIFEST_REF_DESCRIPTION",
    "cancel_runtime_task",
    "continue_paused_task",
    "continue_runtime_task",
    "list_runtime_tasks",
    "pause_runtime_task",
    "runtime_task_read",
]
