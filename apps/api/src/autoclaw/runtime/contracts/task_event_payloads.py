from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.runtime.contracts.primitives import (
    CheckpointKind,
    CheckpointOutcome,
    CommandRunState,
    EgressBoundary,
    HumanRequestKind,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestStatus,
)
from autoclaw.runtime.contracts.provider_resolution import ProviderSelectionBasis

type TaskEventIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
type TaskEventRef = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
]
type TaskEventSummary = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_096),
]
type TaskEventStepText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
type DispatchOpenedReason = Literal[
    "root",
    "boundary",
    "child_return",
    "human_result",
    "command_result",
    "watchdog_recovery",
    "semantic_retry",
    "operator_continue",
]
type ProviderStartState = Literal["retry_scheduled", "accepted"]
type ProviderStartRetryKind = Literal[
    "initial",
    "definite_failure",
    "uncertain_acceptance",
]
type WorkPlanStepStatusValue = Literal["pending", "in_progress", "completed"]


class _TaskEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskStartedEventPayload(_TaskEventPayload):
    flow_id: TaskEventIdentifier
    compiled_plan_id: TaskEventIdentifier
    workflow_key: TaskEventIdentifier
    workflow_revision_no: int = Field(ge=1)
    manifest_ref: TaskEventRef


class DispatchOpenedEventPayload(_TaskEventPayload):
    dispatch_id: TaskEventIdentifier
    predecessor_dispatch_id: TaskEventIdentifier | None = None
    assignment_id: TaskEventIdentifier
    attempt_id: TaskEventIdentifier
    node_key: TaskEventIdentifier
    status: Literal["starting"] = "starting"
    opened_reason: DispatchOpenedReason
    requested_provider: ProviderKind
    resolved_provider: ProviderKind
    selection_basis: ProviderSelectionBasis
    instructions_ref: TaskEventRef
    input_ref: TaskEventRef


class DispatchStartUpdatedEventPayload(_TaskEventPayload):
    dispatch_id: TaskEventIdentifier
    state: ProviderStartState
    attempt_count: int = Field(ge=1)
    provider_start_revision: int = Field(ge=0)
    next_attempt_at: datetime | None = None
    retry_kind: ProviderStartRetryKind | None = None
    last_error_code: TaskEventIdentifier | None = None

    @model_validator(mode="after")
    def validate_state(self) -> DispatchStartUpdatedEventPayload:
        if self.state == "accepted":
            if any(
                value is not None
                for value in (
                    self.next_attempt_at,
                    self.retry_kind,
                    self.last_error_code,
                )
            ):
                raise ValueError("accepted provider starts must clear retry state")
            return self
        if self.next_attempt_at is None or self.retry_kind is None or self.last_error_code is None:
            raise ValueError("scheduled provider retries require due, kind, and error code")
        return self


class TaskEventWorkPlanStep(_TaskEventPayload):
    step: TaskEventStepText
    status: WorkPlanStepStatusValue


class WorkPlanSetEventPayload(_TaskEventPayload):
    assignment_id: TaskEventIdentifier
    revision: int = Field(ge=1)
    explanation: TaskEventSummary | None = None
    steps: tuple[TaskEventWorkPlanStep, ...] = Field(min_length=1, max_length=9)
    authored_by_dispatch_id: TaskEventIdentifier
    updated_at: datetime


class WorkPlanClearedEventPayload(_TaskEventPayload):
    assignment_id: TaskEventIdentifier
    revision: int = Field(ge=1)
    explanation: TaskEventSummary | None = None
    authored_by_dispatch_id: TaskEventIdentifier
    updated_at: datetime


class TaskEventArtifactRef(_TaskEventPayload):
    publication_id: TaskEventIdentifier
    slot: TaskEventIdentifier
    path: TaskEventRef
    version: int = Field(ge=1)


class TaskEventTransientRef(_TaskEventPayload):
    localization_id: TaskEventIdentifier
    path: TaskEventRef
    description: TaskEventSummary


class CheckpointRecordedEventPayload(_TaskEventPayload):
    checkpoint_id: TaskEventIdentifier
    assignment_id: TaskEventIdentifier
    attempt_id: TaskEventIdentifier
    checkpoint_kind: CheckpointKind
    outcome: CheckpointOutcome | None = None
    summary: TaskEventSummary
    checkpoint_ref: TaskEventRef
    produced_artifacts: tuple[TaskEventArtifactRef, ...] = Field(default=(), max_length=32)
    transient_surfaces: tuple[TaskEventTransientRef, ...] = Field(default=(), max_length=32)
    authored_by_dispatch_id: TaskEventIdentifier

    @model_validator(mode="after")
    def validate_checkpoint_kind(self) -> CheckpointRecordedEventPayload:
        if self.checkpoint_kind == CheckpointKind.PROGRESS and self.outcome is not None:
            raise ValueError("progress checkpoint events cannot declare an outcome")
        if self.checkpoint_kind == CheckpointKind.TERMINAL and self.outcome is None:
            raise ValueError("terminal checkpoint events require an outcome")
        return self


class BoundaryAcceptedEventPayload(_TaskEventPayload):
    source_dispatch_id: TaskEventIdentifier
    assignment_id: TaskEventIdentifier
    attempt_id: TaskEventIdentifier
    outcome: EgressBoundary
    checkpoint_id: TaskEventIdentifier | None = None
    checkpoint_ref: TaskEventRef | None = None
    assignment_decision_id: TaskEventIdentifier | None = None
    resulting_flow_status: Literal["running", "completed"]


class ChildAssignmentStagedEventPayload(_TaskEventPayload):
    source_dispatch_id: TaskEventIdentifier
    parent_assignment_id: TaskEventIdentifier
    child_assignment_id: TaskEventIdentifier
    child_attempt_id: TaskEventIdentifier
    child_node_key: TaskEventIdentifier
    flow_revision_id: TaskEventIdentifier


class ChildAssignmentCommittedEventPayload(_TaskEventPayload):
    source_dispatch_id: TaskEventIdentifier
    parent_assignment_id: TaskEventIdentifier
    child_assignment_id: TaskEventIdentifier
    child_attempt_id: TaskEventIdentifier
    child_node_key: TaskEventIdentifier
    flow_revision_id: TaskEventIdentifier


class StructuralRevisionAdoptedEventPayload(_TaskEventPayload):
    source_flow_revision_id: TaskEventIdentifier
    adopted_flow_revision_id: TaskEventIdentifier
    operation: Literal["add_child", "update_child", "remove_child"]
    target_node_key: TaskEventIdentifier
    cause: TaskEventSummary
    adopted_by_dispatch_id: TaskEventIdentifier


class HumanRequestOpenedEventPayload(_TaskEventPayload):
    request_id: TaskEventIdentifier
    kind: HumanRequestKind
    summary: TaskEventSummary
    source_dispatch_id: TaskEventIdentifier
    due_at: datetime | None = None
    opened_at: datetime


class HumanRequestTerminalEventPayload(_TaskEventPayload):
    request_id: TaskEventIdentifier
    kind: HumanRequestKind
    summary: TaskEventSummary
    source_dispatch_id: TaskEventIdentifier
    due_at: datetime | None = None
    status: Literal[
        HumanRequestStatus.RESOLVED,
        HumanRequestStatus.TIMED_OUT,
        HumanRequestStatus.CANCELLED,
    ]
    resolution_kind: HumanRequestResolutionKind
    resolution_summary: TaskEventSummary
    resolved_at: datetime
    resolved_by_surface: HumanRequestResolutionSurface
    resolved_by_actor_ref: TaskEventIdentifier | None = None


class CommandRunOpenedEventPayload(_TaskEventPayload):
    run_id: TaskEventIdentifier
    source_dispatch_id: TaskEventIdentifier
    state: Literal[CommandRunState.PENDING_START]
    command: TaskEventSummary
    description: TaskEventSummary
    workdir: TaskEventRef | None = None
    created_at: datetime
    timeout_seconds: int | None = Field(default=None, ge=1)
    ownership_revision: Literal[0] = 0


class CommandRunStartedEventPayload(_TaskEventPayload):
    run_id: TaskEventIdentifier
    source_dispatch_id: TaskEventIdentifier
    state: Literal[CommandRunState.RUNNING]
    command: TaskEventSummary
    description: TaskEventSummary
    workdir: TaskEventRef | None = None
    started_at: datetime
    due_at: datetime | None = None
    ownership_revision: int = Field(ge=1)
    log_refs: tuple[TaskEventRef, ...] = Field(default=(), max_length=2)


class CommandRunProgressedEventPayload(_TaskEventPayload):
    run_id: TaskEventIdentifier
    source_dispatch_id: TaskEventIdentifier
    state: Literal[CommandRunState.RUNNING, CommandRunState.CANCELLATION_REQUESTED]
    summary: TaskEventSummary
    occurred_at: datetime
    ownership_revision: int = Field(ge=1)
    log_ref: TaskEventRef | None = None


class CommandRunCancelRequestedEventPayload(_TaskEventPayload):
    run_id: TaskEventIdentifier
    source_dispatch_id: TaskEventIdentifier
    state: Literal[CommandRunState.CANCELLATION_REQUESTED]
    requested_at: datetime
    ownership_revision: int = Field(ge=0)


class CommandRunTerminalEventPayload(_TaskEventPayload):
    run_id: TaskEventIdentifier
    source_dispatch_id: TaskEventIdentifier
    state: Literal[
        CommandRunState.SUCCEEDED,
        CommandRunState.FAILED,
        CommandRunState.TIMED_OUT,
        CommandRunState.CANCELLED,
        CommandRunState.ABANDONED,
    ]
    summary: TaskEventSummary
    started_at: datetime | None = None
    ended_at: datetime
    exit_code: int | None = None
    failure_code: TaskEventIdentifier | None = None
    ownership_revision: int = Field(ge=0)
    log_refs: tuple[TaskEventRef, ...] = Field(default=(), max_length=2)


class TaskPausedEventPayload(_TaskEventPayload):
    pause_reason: Literal[
        "paused_by_operator",
        "runtime_recovery_exhausted",
        "runtime_transition_failed",
    ]
    control_revision: int = Field(ge=1)
    actor_ref: TaskEventIdentifier | None = None
    summary: TaskEventSummary


class TaskResumedEventPayload(_TaskEventPayload):
    control_revision: int = Field(ge=1)
    actor_ref: TaskEventIdentifier | None = None
    summary: TaskEventSummary


class TaskCancelledEventPayload(_TaskEventPayload):
    control_revision: int = Field(ge=1)
    actor_ref: TaskEventIdentifier | None = None
    summary: TaskEventSummary


type TaskEventPayload = (
    TaskStartedEventPayload
    | DispatchOpenedEventPayload
    | DispatchStartUpdatedEventPayload
    | WorkPlanSetEventPayload
    | WorkPlanClearedEventPayload
    | CheckpointRecordedEventPayload
    | BoundaryAcceptedEventPayload
    | ChildAssignmentStagedEventPayload
    | ChildAssignmentCommittedEventPayload
    | StructuralRevisionAdoptedEventPayload
    | HumanRequestOpenedEventPayload
    | HumanRequestTerminalEventPayload
    | CommandRunOpenedEventPayload
    | CommandRunStartedEventPayload
    | CommandRunProgressedEventPayload
    | CommandRunCancelRequestedEventPayload
    | CommandRunTerminalEventPayload
    | TaskPausedEventPayload
    | TaskResumedEventPayload
    | TaskCancelledEventPayload
)


__all__ = [
    "BoundaryAcceptedEventPayload",
    "CheckpointRecordedEventPayload",
    "ChildAssignmentCommittedEventPayload",
    "ChildAssignmentStagedEventPayload",
    "CommandRunCancelRequestedEventPayload",
    "CommandRunOpenedEventPayload",
    "CommandRunProgressedEventPayload",
    "CommandRunStartedEventPayload",
    "CommandRunTerminalEventPayload",
    "DispatchOpenedEventPayload",
    "DispatchStartUpdatedEventPayload",
    "HumanRequestOpenedEventPayload",
    "HumanRequestTerminalEventPayload",
    "StructuralRevisionAdoptedEventPayload",
    "TaskCancelledEventPayload",
    "TaskEventArtifactRef",
    "TaskEventIdentifier",
    "TaskEventPayload",
    "TaskEventRef",
    "TaskEventTransientRef",
    "TaskPausedEventPayload",
    "TaskResumedEventPayload",
    "TaskStartedEventPayload",
    "WorkPlanClearedEventPayload",
    "WorkPlanSetEventPayload",
]
