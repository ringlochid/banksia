from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from autoclaw.runtime.contracts.primitives import (
    CommandRunState,
    HumanRequestResolutionKind,
    HumanRequestStatus,
    TaskEventSource,
    TaskEventType,
    TaskIdentifier,
)
from autoclaw.runtime.contracts.task_event_payloads import (
    BoundaryAcceptedEventPayload,
    CheckpointRecordedEventPayload,
    ChildAssignmentCommittedEventPayload,
    ChildAssignmentStagedEventPayload,
    CommandRunCancelRequestedEventPayload,
    CommandRunOpenedEventPayload,
    CommandRunProgressedEventPayload,
    CommandRunStartedEventPayload,
    CommandRunTerminalEventPayload,
    DispatchOpenedEventPayload,
    DispatchStartUpdatedEventPayload,
    HumanRequestOpenedEventPayload,
    HumanRequestTerminalEventPayload,
    StructuralRevisionAdoptedEventPayload,
    TaskCancelledEventPayload,
    TaskEventIdentifier,
    TaskEventPayload,
    TaskEventRef,
    TaskPausedEventPayload,
    TaskResumedEventPayload,
    TaskStartedEventPayload,
    WorkPlanClearedEventPayload,
    WorkPlanSetEventPayload,
)


class _TaskEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    event_id: TaskEventIdentifier
    event_seq: int = Field(ge=1)
    task_id: TaskIdentifier
    event_source: TaskEventSource
    occurred_at: datetime
    flow_revision_id: TaskEventIdentifier | None = None
    dispatch_id: TaskEventIdentifier | None = None
    attempt_id: TaskEventIdentifier | None = None
    node_key: TaskEventIdentifier | None = None
    actor_ref: TaskEventIdentifier | None = None
    prev_event_hash: TaskEventRef | None = None
    event_hash: TaskEventRef


class _TaskStartedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.TASK_STARTED]
    payload: TaskStartedEventPayload


class _DispatchOpenedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.DISPATCH_OPENED]
    payload: DispatchOpenedEventPayload


class _DispatchStartUpdatedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.DISPATCH_START_UPDATED]
    payload: DispatchStartUpdatedEventPayload


class _WorkPlanSetEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.WORK_PLAN_SET]
    payload: WorkPlanSetEventPayload


class _WorkPlanClearedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.WORK_PLAN_CLEARED]
    payload: WorkPlanClearedEventPayload


class _CheckpointRecordedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.CHECKPOINT_RECORDED]
    payload: CheckpointRecordedEventPayload


class _BoundaryAcceptedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.BOUNDARY_ACCEPTED]
    payload: BoundaryAcceptedEventPayload


class _ChildAssignmentStagedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.CHILD_ASSIGNMENT_STAGED]
    payload: ChildAssignmentStagedEventPayload


class _ChildAssignmentCommittedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.CHILD_ASSIGNMENT_COMMITTED]
    payload: ChildAssignmentCommittedEventPayload


class _StructuralRevisionAdoptedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.STRUCTURAL_REVISION_ADOPTED]
    payload: StructuralRevisionAdoptedEventPayload


class _HumanRequestOpenedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.HUMAN_REQUEST_OPENED]
    payload: HumanRequestOpenedEventPayload


class _HumanRequestTerminalEvent(_TaskEventEnvelope):
    event_type: Literal[
        TaskEventType.HUMAN_REQUEST_RESOLVED,
        TaskEventType.HUMAN_REQUEST_TIMED_OUT,
        TaskEventType.HUMAN_REQUEST_CANCELLED,
    ]
    payload: HumanRequestTerminalEventPayload

    @model_validator(mode="after")
    def validate_terminal_kind(self) -> _HumanRequestTerminalEvent:
        expected = {
            TaskEventType.HUMAN_REQUEST_RESOLVED: (
                HumanRequestStatus.RESOLVED,
                HumanRequestResolutionKind.ANSWERED,
            ),
            TaskEventType.HUMAN_REQUEST_TIMED_OUT: (
                HumanRequestStatus.TIMED_OUT,
                HumanRequestResolutionKind.TIMED_OUT,
            ),
            TaskEventType.HUMAN_REQUEST_CANCELLED: (
                HumanRequestStatus.CANCELLED,
                HumanRequestResolutionKind.CANCELLED,
            ),
        }[self.event_type]
        if (self.payload.status, self.payload.resolution_kind) != expected:
            raise ValueError("human request event type does not match terminal payload")
        return self


class _CommandRunOpenedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.COMMAND_RUN_OPENED]
    payload: CommandRunOpenedEventPayload


class _CommandRunStartedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.COMMAND_RUN_STARTED]
    payload: CommandRunStartedEventPayload


class _CommandRunProgressedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.COMMAND_RUN_PROGRESSED]
    payload: CommandRunProgressedEventPayload


class _CommandRunCancelRequestedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.COMMAND_RUN_CANCEL_REQUESTED]
    payload: CommandRunCancelRequestedEventPayload


class _CommandRunTerminalEvent(_TaskEventEnvelope):
    event_type: Literal[
        TaskEventType.COMMAND_RUN_SUCCEEDED,
        TaskEventType.COMMAND_RUN_FAILED,
        TaskEventType.COMMAND_RUN_TIMED_OUT,
        TaskEventType.COMMAND_RUN_CANCELLED,
        TaskEventType.COMMAND_RUN_ABANDONED,
    ]
    payload: CommandRunTerminalEventPayload

    @model_validator(mode="after")
    def validate_terminal_state(self) -> _CommandRunTerminalEvent:
        expected = {
            TaskEventType.COMMAND_RUN_SUCCEEDED: CommandRunState.SUCCEEDED,
            TaskEventType.COMMAND_RUN_FAILED: CommandRunState.FAILED,
            TaskEventType.COMMAND_RUN_TIMED_OUT: CommandRunState.TIMED_OUT,
            TaskEventType.COMMAND_RUN_CANCELLED: CommandRunState.CANCELLED,
            TaskEventType.COMMAND_RUN_ABANDONED: CommandRunState.ABANDONED,
        }[self.event_type]
        if self.payload.state != expected:
            raise ValueError("command run event type does not match terminal payload")
        if (
            self.payload.state == CommandRunState.ABANDONED
            and self.payload.failure_code != "command_ownership_lost"
        ):
            raise ValueError("abandoned command events require command_ownership_lost")
        return self


class _TaskPausedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.TASK_PAUSED]
    payload: TaskPausedEventPayload


class _TaskResumedEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.TASK_RESUMED]
    payload: TaskResumedEventPayload


class _TaskCancelledEvent(_TaskEventEnvelope):
    event_type: Literal[TaskEventType.TASK_CANCELLED]
    payload: TaskCancelledEventPayload


type _TaskEventVariant = Annotated[
    _TaskStartedEvent
    | _DispatchOpenedEvent
    | _DispatchStartUpdatedEvent
    | _WorkPlanSetEvent
    | _WorkPlanClearedEvent
    | _CheckpointRecordedEvent
    | _BoundaryAcceptedEvent
    | _ChildAssignmentStagedEvent
    | _ChildAssignmentCommittedEvent
    | _StructuralRevisionAdoptedEvent
    | _HumanRequestOpenedEvent
    | _HumanRequestTerminalEvent
    | _CommandRunOpenedEvent
    | _CommandRunStartedEvent
    | _CommandRunProgressedEvent
    | _CommandRunCancelRequestedEvent
    | _CommandRunTerminalEvent
    | _TaskPausedEvent
    | _TaskResumedEvent
    | _TaskCancelledEvent,
    Field(discriminator="event_type"),
]


class TaskEventRecord(RootModel[_TaskEventVariant]):
    """One bounded chronology event with an event-type-specific payload."""

    model_config = ConfigDict(frozen=True)

    @property
    def event_id(self) -> str:
        return self.root.event_id

    @property
    def event_seq(self) -> int:
        return self.root.event_seq

    @property
    def task_id(self) -> str:
        return self.root.task_id

    @property
    def event_type(self) -> TaskEventType:
        return self.root.event_type

    @property
    def event_source(self) -> TaskEventSource:
        return self.root.event_source

    @property
    def occurred_at(self) -> datetime:
        return self.root.occurred_at

    @property
    def flow_revision_id(self) -> str | None:
        return self.root.flow_revision_id

    @property
    def dispatch_id(self) -> str | None:
        return self.root.dispatch_id

    @property
    def attempt_id(self) -> str | None:
        return self.root.attempt_id

    @property
    def node_key(self) -> str | None:
        return self.root.node_key

    @property
    def actor_ref(self) -> str | None:
        return self.root.actor_ref

    @property
    def payload(self) -> TaskEventPayload:
        return self.root.payload

    @property
    def prev_event_hash(self) -> str | None:
        return self.root.prev_event_hash

    @property
    def event_hash(self) -> str:
        return self.root.event_hash


class TaskEventListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: TaskEventIdentifier | None = None
    limit: int = Field(default=100, ge=1, le=500)
    through_event_id: TaskEventIdentifier | None = None


class TaskEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: TaskIdentifier
    items: tuple[TaskEventRecord, ...]
    next_cursor: TaskEventIdentifier | None = None
    through_event_id: TaskEventIdentifier | None = None


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
    "TaskEventListQuery",
    "TaskEventListResponse",
    "TaskEventRecord",
    "TaskPausedEventPayload",
    "TaskResumedEventPayload",
    "TaskStartedEventPayload",
    "WorkPlanClearedEventPayload",
    "WorkPlanSetEventPayload",
]
