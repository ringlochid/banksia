from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banksia.runtime.contracts.checkpoint import TaskResult
from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.refs import WorkflowManifestRef

type ControllerTaskTerminalOutcome = Literal["green", "blocked"]
type ControllerTaskPauseReason = Literal[
    "paused_by_operator",
    "runtime_recovery_exhausted",
    "runtime_transition_failed",
]


class ControllerTaskLifecycleStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ControllerTaskState(BaseModel):
    """Internal controller lifecycle read used by runtime and support presenters."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    task_title: RuntimeSchemaText
    task_summary: RuntimeSchemaText
    workflow_key: RuntimeSchemaText | None = None
    status: ControllerTaskLifecycleStatus
    terminal_outcome: ControllerTaskTerminalOutcome | None = None
    result: TaskResult | None = None
    current_team_revision_id: RuntimeSchemaText
    control_revision: int = Field(ge=0)
    workflow_manifest_ref: WorkflowManifestRef
    pause_reason: ControllerTaskPauseReason | None = None
    created_at: datetime
    updated_at: datetime


class ControllerTaskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    task_title: RuntimeSchemaText
    task_summary: RuntimeSchemaText
    workflow_key: RuntimeSchemaText | None = None
    status: ControllerTaskLifecycleStatus
    terminal_outcome: ControllerTaskTerminalOutcome | None = None
    current_team_revision_id: RuntimeSchemaText
    workflow_manifest_ref: WorkflowManifestRef
    created_at: datetime
    updated_at: datetime


class ControllerTaskSummaryPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    items: tuple[ControllerTaskSummary, ...]
    next_cursor: RuntimeSchemaText | None = None


class ControllerTaskPauseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task: ControllerTaskState


class ControllerTaskControlGuard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_team_revision_id: RuntimeSchemaText
    expected_control_revision: int = Field(ge=0)


class ControllerTaskListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    q: RuntimeSchemaText | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: RuntimeSchemaText | None = None
    sort: Literal[
        "updated_at_desc",
        "updated_at_asc",
        "task_title_asc",
        "task_title_desc",
    ] = "updated_at_desc"
    status: Literal[
        "any",
        "pending",
        "running",
        "paused",
        "completed",
        "blocked",
        "cancelled",
    ] = "any"


__all__ = [
    "ControllerTaskControlGuard",
    "ControllerTaskLifecycleStatus",
    "ControllerTaskListQuery",
    "ControllerTaskPauseReason",
    "ControllerTaskPauseResult",
    "ControllerTaskState",
    "ControllerTaskSummary",
    "ControllerTaskSummaryPage",
    "ControllerTaskTerminalOutcome",
]
