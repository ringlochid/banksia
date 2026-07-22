from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

RuntimeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskIdentifier = RuntimeText
SlotIdentifier = RuntimeText


class TaskRootMode(StrEnum):
    ENSURE_TASK_DEFAULT = "ensure_task_default"
    ENSURE_HOST_PATH = "ensure_host_path"
    USE_EXISTING_HOST = "use_existing_host"


class FlowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


class EvidenceKind(StrEnum):
    ARTIFACT = "artifact"
    CRITERIA = "criteria"
    DOC = "doc"
    WIKI = "wiki"
    TRANSIENT = "transient"


class NodeRuntimeFileKind(StrEnum):
    MANIFEST = "manifest"
    ASSIGNMENT = "assignment"
    CHECKPOINT = "checkpoint"
    ARTIFACT_INDEX = "artifact_index"
    TRANSIENT_INDEX = "transient_index"


class CheckpointKind(StrEnum):
    PROGRESS = "progress"
    TERMINAL = "terminal"


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


class TaskComposeTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: RuntimeText
    title: RuntimeText
    summary: RuntimeText
    instruction: RuntimeText | None = None


class TaskComposeWorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: RuntimeText


class TaskRootBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: TaskRootMode = TaskRootMode.ENSURE_TASK_DEFAULT
    host_path: Path | None = None

    @model_validator(mode="after")
    def validate_host_path(self) -> TaskRootBindingInput:
        if self.mode == TaskRootMode.ENSURE_TASK_DEFAULT and self.host_path is not None:
            raise ValueError("host_path is invalid with ensure_task_default")
        if self.mode != TaskRootMode.ENSURE_TASK_DEFAULT and self.host_path is None:
            raise ValueError(f"host_path is required with {self.mode.value}")
        return self


class TaskComposeRootsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: TaskRootBindingInput | None = None


class TaskComposeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskComposeTaskInput
    workflow: TaskComposeWorkflowInput
    roots: TaskComposeRootsInput | None = None


class TaskRootPaths(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_root: Path
    workspace_path: Path
    outputs_path: Path
    artifacts_path: Path
    tmp_path: Path
    transfers_path: Path
    localized_path: Path
    runtime_path: Path
    criteria_path: Path
    attempts_path: Path
    dispatch_path: Path


class NodeRuntimeFileRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: NodeRuntimeFileKind
    path: Path
    description: RuntimeText


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EvidenceKind
    slot: SlotIdentifier | None = None
    version: int | None = Field(default=None, ge=1)
    path: Path
    description: RuntimeText

    @model_validator(mode="after")
    def validate_shape(self) -> EvidenceRef:
        if self.kind == EvidenceKind.ARTIFACT:
            if self.slot is None or self.version is None:
                raise ValueError("artifact refs require slot and version")
            return self
        if self.kind == EvidenceKind.CRITERIA:
            if self.slot is None:
                raise ValueError("criteria refs require slot")
            if self.version is not None:
                raise ValueError("criteria refs must not set version")
            return self
        if self.version is not None:
            raise ValueError("only artifact refs may set version")
        if self.kind == EvidenceKind.TRANSIENT and self.slot is not None:
            raise ValueError("transient refs must not set slot")
        return self


type RuntimeContextRef = NodeRuntimeFileRef | EvidenceRef
type AssignmentConsumeRef = NodeRuntimeFileRef | EvidenceRef


__all__ = [
    "AssignmentConsumeRef",
    "CapabilityDecision",
    "CheckpointKind",
    "CheckpointOutcome",
    "CommandRunState",
    "CommandRunTerminalSource",
    "EgressBoundary",
    "EvidenceKind",
    "EvidenceRef",
    "FlowStatus",
    "HumanRequestKind",
    "HumanRequestResolutionKind",
    "HumanRequestStatus",
    "NodeRuntimeFileKind",
    "NodeRuntimeFileRef",
    "RuntimeContextRef",
    "RuntimeText",
    "SlotIdentifier",
    "TaskComposeInput",
    "TaskComposeRootsInput",
    "TaskComposeTaskInput",
    "TaskComposeWorkflowInput",
    "TaskEventSource",
    "TaskEventType",
    "TaskIdentifier",
    "TaskRootBindingInput",
    "TaskRootMode",
    "TaskRootPaths",
]
