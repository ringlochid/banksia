from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

RuntimeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskIdentifier = RuntimeText


class FlowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


class EgressBoundary(StrEnum):
    YIELD = "yield"
    GREEN = "green"
    RETRY = "retry"
    BLOCKED = "blocked"


class CheckpointOutcome(StrEnum):
    GREEN = "green"
    RETRY = "retry"
    BLOCKED = "blocked"


class CapabilityDecision(StrEnum):
    DENY = "deny"
    ALLOW = "allow"


class HumanRequestKind(StrEnum):
    DIRECTION = "direction"
    APPROVAL = "approval"
    INPUT = "input"
    REVIEW = "review"


class HumanRequestStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class HumanRequestResolutionKind(StrEnum):
    ANSWERED = "answered"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class HumanRequestResolutionSurface(StrEnum):
    CONTROL_API = "control_api"
    CONTROL_UI = "control_ui"
    OPERATOR_MCP = "operator_mcp"
    CONTROLLER = "controller"


class CommandRunState(StrEnum):
    PENDING_START = "pending_start"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class CommandRunTerminalSource(StrEnum):
    CONTROLLER = "controller"
    CONTROL_API = "control_api"
    OPERATOR_MCP = "operator_mcp"
    PROCESS_OWNER = "process_owner"


class TaskEventSource(StrEnum):
    CONTROLLER = "controller"
    CONTROL_API = "control_api"
    OPERATOR_MCP = "operator_mcp"
    NODE = "node"


class TaskEventType(StrEnum):
    TASK_STARTED = "task_started"
    DISPATCH_OPENED = "dispatch_opened"
    DISPATCH_START_UPDATED = "dispatch_start_updated"
    WORK_PLAN_SET = "work_plan_set"
    WORK_PLAN_CLEARED = "work_plan_cleared"
    CHECKPOINT_RECORDED = "checkpoint_recorded"
    BOUNDARY_ACCEPTED = "boundary_accepted"
    CHILD_ASSIGNMENT_STAGED = "child_assignment_staged"
    CHILD_ASSIGNMENT_COMMITTED = "child_assignment_committed"
    STRUCTURAL_REVISION_ADOPTED = "structural_revision_adopted"
    HUMAN_REQUEST_OPENED = "human_request_opened"
    HUMAN_REQUEST_RESOLVED = "human_request_resolved"
    HUMAN_REQUEST_TIMED_OUT = "human_request_timed_out"
    HUMAN_REQUEST_CANCELLED = "human_request_cancelled"
    COMMAND_RUN_OPENED = "command_run_opened"
    COMMAND_RUN_STARTED = "command_run_started"
    COMMAND_RUN_PROGRESSED = "command_run_progressed"
    COMMAND_RUN_CANCEL_REQUESTED = "command_run_cancel_requested"
    COMMAND_RUN_SUCCEEDED = "command_run_succeeded"
    COMMAND_RUN_FAILED = "command_run_failed"
    COMMAND_RUN_TIMED_OUT = "command_run_timed_out"
    COMMAND_RUN_CANCELLED = "command_run_cancelled"
    COMMAND_RUN_ABANDONED = "command_run_abandoned"
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"
    TASK_CANCELLED = "task_cancelled"


class TaskRootPaths(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_root: Path
    workspace_path: Path
    outputs_path: Path
    artifacts_path: Path
    tmp_path: Path
    runtime_path: Path
    dispatch_path: Path


__all__ = [
    "CapabilityDecision",
    "CheckpointOutcome",
    "CommandRunState",
    "CommandRunTerminalSource",
    "EgressBoundary",
    "FlowStatus",
    "HumanRequestKind",
    "HumanRequestResolutionKind",
    "HumanRequestStatus",
    "RuntimeText",
    "TaskEventSource",
    "TaskEventType",
    "TaskIdentifier",
    "TaskRootPaths",
]
