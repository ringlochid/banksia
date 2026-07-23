from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from banksia.runtime.contracts.command_runs import CommandRunStartRequest
from banksia.runtime.contracts.human_requests import (
    HumanRequestOpenRequest,
    HumanRequestResolution,
)
from banksia.runtime.contracts.primitives import (
    CheckpointOutcome,
    EgressBoundary,
    HumanRequestKind,
)
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.replan import ReplanSuccess
from banksia.runtime.contracts.text import normalize_exact_text
from banksia.runtime.work_plan.contracts import WorkPlanView

PromptIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
PromptShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8_192),
]
PromptDocumentText = Annotated[
    str,
    StringConstraints(min_length=1),
]

PROMPT_DYNAMIC_INPUT_KEYS = (
    "task",
    "dispatch",
    "current_member",
    "assignment",
    "continuation",
    "direct_team",
    "work_plan",
    "available_actions",
    "workspace",
)


class PromptContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PromptBehavior(StrEnum):
    MANAGER = "manager"
    CONTRIBUTOR = "contributor"


class PromptParticipation(StrEnum):
    REQUIRED = "required"
    SATISFIED = "satisfied"


class PromptAvailability(StrEnum):
    AVAILABLE = "available"
    BUSY = "busy"


class PromptCommandOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class PromptCommandTerminalSource(StrEnum):
    CONTROLLER = "controller"
    CONTROL_API = "control_api"
    OPERATOR_MCP = "operator_mcp"
    PROCESS_OWNER = "process_owner"


class PromptTask(PromptContract):
    id: PromptIdentifier
    workflow_id: PromptIdentifier


class PromptDispatch(PromptContract):
    id: PromptIdentifier
    attempt_id: PromptIdentifier
    assignment_id: PromptIdentifier


class PromptSandbox(PromptContract):
    mode: PromptIdentifier
    network: PromptIdentifier


class PromptProvider(PromptContract):
    name: PromptIdentifier
    model: PromptIdentifier | None = None
    effort: PromptIdentifier | None = None
    gateway_profile: PromptIdentifier | None = None
    sandbox: PromptSandbox | None = None


class PromptEffectiveCapabilities(PromptContract):
    human_request: tuple[HumanRequestKind, ...] = ()
    command_run: Literal["allow", "deny"] = "deny"


class PromptCurrentMember(PromptContract):
    id: PromptIdentifier
    title: str | None = None
    description: str | None = None
    instruction: str | None = None
    position: Literal["task_lead"] | None = None
    behavior: PromptBehavior
    provider: PromptProvider
    effective_capabilities: PromptEffectiveCapabilities


class PromptAssignment(PromptContract):
    id: PromptIdentifier
    prompt: str
    files: tuple[FileReference, ...] = ()

    @field_validator("prompt", mode="before")
    @classmethod
    def normalize_prompt(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="Assignment prompt",
            is_nonblank_required=True,
        )


class PromptCheckpointSummary(PromptContract):
    id: PromptIdentifier
    summary: str
    details: str | None = None
    files: tuple[FileReference, ...] = ()
    outcome: CheckpointOutcome


class PromptDirectMember(PromptContract):
    id: PromptIdentifier
    title: str | None = None
    description: str | None = None
    instruction: str | None = None
    provider: PromptProvider | None = None
    capabilities: PromptEffectiveCapabilities
    participation: PromptParticipation
    availability: PromptAvailability


class PromptWorkspace(PromptContract):
    root: str
    task_directory: str
    manifest: str
    workflow_note: str | None = None
    notes: str
    artifacts: str
    command_runs: str


class AcceptedBoundarySource(PromptContract):
    accepted_boundary_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier


class AcceptedBoundaryResult(PromptContract):
    outcome: Literal[EgressBoundary.YIELD]


class AcceptedBoundaryTrigger(PromptContract):
    kind: Literal["accepted_boundary"] = "accepted_boundary"
    source: AcceptedBoundarySource
    result: AcceptedBoundaryResult


class ChildReturnSource(PromptContract):
    accepted_boundary_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier
    child_assignment_id: PromptIdentifier
    child_attempt_id: PromptIdentifier


class ChildReturnResult(PromptContract):
    assignment: PromptAssignment
    outcome: Literal[EgressBoundary.GREEN, EgressBoundary.BLOCKED]
    checkpoint: PromptCheckpointSummary

    @model_validator(mode="after")
    def validate_checkpoint_outcome(self) -> ChildReturnResult:
        if self.checkpoint.outcome.value != self.outcome.value:
            raise ValueError("child-return checkpoint outcome must match the accepted outcome")
        return self


class ChildReturnTrigger(PromptContract):
    kind: Literal["child_return"] = "child_return"
    source: ChildReturnSource
    result: ChildReturnResult


class HumanResultSource(PromptContract):
    request_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier


class HumanResult(PromptContract):
    request: HumanRequestOpenRequest
    resolution: HumanRequestResolution


class HumanResultTrigger(PromptContract):
    kind: Literal["human_result"] = "human_result"
    source: HumanResultSource
    result: HumanResult

    @model_validator(mode="after")
    def validate_request_resolution_identity(self) -> HumanResultTrigger:
        if self.source.request_id != self.result.resolution.request_id:
            raise ValueError("human-result request and resolution IDs must match")
        return self


class PromptCommandResult(PromptContract):
    state: PromptCommandOutcome
    exit_code: int | None = None
    summary: PromptShortText
    started_at: datetime | None = None
    ended_at: datetime
    output_path: str
    output_observed_bytes: int = Field(ge=0)
    output_written_bytes: int = Field(ge=0)
    output_complete: bool
    output_encoding: Literal["raw_bytes"]
    failure_code: PromptIdentifier | None = None
    terminal_event_source: PromptCommandTerminalSource
    terminal_actor_ref: PromptIdentifier | None = None

    @model_validator(mode="after")
    def validate_result(self) -> PromptCommandResult:
        if self.started_at is not None and self.ended_at < self.started_at:
            raise ValueError("command result cannot end before it starts")
        if (
            self.state == PromptCommandOutcome.ABANDONED
            and self.failure_code != "command_ownership_lost"
        ):
            raise ValueError("abandoned command results require command_ownership_lost")
        if self.output_written_bytes > self.output_observed_bytes:
            raise ValueError("command output written bytes cannot exceed observed bytes")
        if self.output_complete and self.output_written_bytes != self.output_observed_bytes:
            raise ValueError("complete command output requires every observed byte to be written")
        return self


class CommandResultSource(PromptContract):
    command_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier


class CommandResult(PromptContract):
    request: CommandRunStartRequest
    terminal: PromptCommandResult


class CommandResultTrigger(PromptContract):
    kind: Literal["command_result"] = "command_result"
    source: CommandResultSource
    result: CommandResult


class WatchdogRecoverySource(PromptContract):
    source_dispatch_id: PromptIdentifier


class WatchdogRecoveryResult(PromptContract):
    recovery_count: int = Field(ge=1)


class WatchdogRecoveryTrigger(PromptContract):
    kind: Literal["watchdog_recovery"] = "watchdog_recovery"
    source: WatchdogRecoverySource
    result: WatchdogRecoveryResult


class SemanticRetrySource(PromptContract):
    accepted_boundary_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier
    previous_attempt_id: PromptIdentifier


class SemanticRetryResult(PromptContract):
    checkpoint: PromptCheckpointSummary

    @model_validator(mode="after")
    def validate_retry_checkpoint(self) -> SemanticRetryResult:
        if self.checkpoint.outcome != CheckpointOutcome.RETRY:
            raise ValueError("semantic-retry trigger requires a retry checkpoint")
        return self


class SemanticRetryTrigger(PromptContract):
    kind: Literal["semantic_retry"] = "semantic_retry"
    source: SemanticRetrySource
    result: SemanticRetryResult


class OperatorContinueSource(PromptContract):
    source_dispatch_id: PromptIdentifier | None = None
    source_task_id: PromptIdentifier | None = None

    @model_validator(mode="after")
    def validate_exact_source(self) -> OperatorContinueSource:
        if (self.source_dispatch_id is None) == (self.source_task_id is None):
            raise ValueError(
                "operator-continue trigger requires exactly one dispatch or Task source"
            )
        return self


class OperatorContinueResult(PromptContract):
    control_revision: int = Field(ge=0)
    pause_reason: PromptShortText


class OperatorContinueTrigger(PromptContract):
    kind: Literal["operator_continue"] = "operator_continue"
    source: OperatorContinueSource
    result: OperatorContinueResult


class StructuralReplanSource(PromptContract):
    source_dispatch_id: PromptIdentifier
    operation: Literal["add_child", "update_child", "remove_child"]


class StructuralReplanResult(PromptContract):
    replan: ReplanSuccess


class StructuralReplanTrigger(PromptContract):
    kind: Literal["structural_replan"] = "structural_replan"
    source: StructuralReplanSource
    result: StructuralReplanResult


type PromptTrigger = Annotated[
    AcceptedBoundaryTrigger
    | ChildReturnTrigger
    | HumanResultTrigger
    | CommandResultTrigger
    | WatchdogRecoveryTrigger
    | SemanticRetryTrigger
    | OperatorContinueTrigger
    | StructuralReplanTrigger,
    Field(discriminator="kind"),
]

PROMPT_TRIGGER_KINDS = (
    "accepted_boundary",
    "child_return",
    "human_result",
    "command_result",
    "watchdog_recovery",
    "semantic_retry",
    "operator_continue",
    "structural_replan",
)


class PromptContinuation(PromptContract):
    trigger: PromptTrigger


class PromptDynamicInput(PromptContract):
    task: PromptTask
    dispatch: PromptDispatch
    current_member: PromptCurrentMember
    assignment: PromptAssignment
    continuation: PromptContinuation | None = None
    direct_team: tuple[PromptDirectMember, ...] = ()
    work_plan: WorkPlanView | None = None
    available_actions: tuple[PromptIdentifier, ...]
    workspace: PromptWorkspace

    @model_validator(mode="after")
    def validate_identity_and_behavior(self) -> PromptDynamicInput:
        if self.assignment.id != self.dispatch.assignment_id:
            raise ValueError("assignment and dispatch IDs must match")
        expected_behavior = (
            PromptBehavior.MANAGER if self.direct_team else PromptBehavior.CONTRIBUTOR
        )
        if self.current_member.behavior != expected_behavior:
            raise ValueError("current Member behavior must match the direct-team shape")
        if tuple(dict.fromkeys(self.available_actions)) != self.available_actions:
            raise ValueError("available actions must be unique")
        return self


class DispatchRequestRenderInput(PromptContract):
    dynamic_input: PromptDynamicInput
    member_instruction: str | None = None
    workflow_note: str | None = None


class RenderedDispatchRequest(PromptContract):
    instructions_text: PromptDocumentText
    input_text: PromptDocumentText

    @field_validator("instructions_text", "input_text", mode="before")
    @classmethod
    def normalize_request_text(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="rendered dispatch request",
            is_nonblank_required=True,
        )


__all__ = [
    "PROMPT_DYNAMIC_INPUT_KEYS",
    "PROMPT_TRIGGER_KINDS",
    "AcceptedBoundaryResult",
    "AcceptedBoundarySource",
    "AcceptedBoundaryTrigger",
    "ChildReturnResult",
    "ChildReturnSource",
    "ChildReturnTrigger",
    "CommandResult",
    "CommandResultSource",
    "CommandResultTrigger",
    "DispatchRequestRenderInput",
    "HumanResult",
    "HumanResultSource",
    "HumanResultTrigger",
    "OperatorContinueResult",
    "OperatorContinueSource",
    "OperatorContinueTrigger",
    "PromptAssignment",
    "PromptAvailability",
    "PromptBehavior",
    "PromptCheckpointSummary",
    "PromptCommandOutcome",
    "PromptCommandResult",
    "PromptCommandTerminalSource",
    "PromptContinuation",
    "PromptCurrentMember",
    "PromptDirectMember",
    "PromptDispatch",
    "PromptDynamicInput",
    "PromptEffectiveCapabilities",
    "PromptParticipation",
    "PromptProvider",
    "PromptSandbox",
    "PromptTask",
    "PromptTrigger",
    "PromptWorkspace",
    "RenderedDispatchRequest",
    "SemanticRetryResult",
    "SemanticRetrySource",
    "SemanticRetryTrigger",
    "StructuralReplanResult",
    "StructuralReplanSource",
    "StructuralReplanTrigger",
    "WatchdogRecoveryResult",
    "WatchdogRecoverySource",
    "WatchdogRecoveryTrigger",
]
