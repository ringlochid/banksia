from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts.capabilities import EffectiveCapabilitySet
from autoclaw.runtime.contracts.command_runs import CommandRunStartRequest
from autoclaw.runtime.contracts.human_requests import (
    HumanRequestResolution,
    PendingHumanRequest,
)
from autoclaw.runtime.contracts.primitives import (
    CheckpointOutcome,
    EgressBoundary,
    HumanRequestResolutionKind,
    HumanRequestStatus,
)
from autoclaw.runtime.work_plan.contracts import WorkPlanRead

PromptText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8_192),
]
PromptIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class PromptLogicalPathValidator:
    def __call__(self, logical_path: str) -> str:
        if "\x00" in logical_path or "\\" in logical_path:
            raise ValueError("prompt refs require a task-relative POSIX logical path")
        path = PurePosixPath(logical_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("prompt refs require a contained task-relative path")
        if not path.parts or path.parts[0] not in {
            "workspace",
            "outputs",
            "tmp",
            "_runtime",
        }:
            raise ValueError("prompt refs require a declared logical task root")
        return logical_path


PromptLogicalPath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
    AfterValidator(PromptLogicalPathValidator()),
]
PromptDocumentText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=131_072),
]

PROMPT_DYNAMIC_INPUT_KEYS = (
    "assignment",
    "trigger",
    "plan",
    "context",
    "dispatch",
    "next",
)
PARENT_ROOT_ACTIONS = frozenset(
    {
        "assign_child",
        "add_child",
        "get_definition",
        "remove_child",
        "release_blocked",
        "release_green",
        "search_definitions",
        "update_child",
    }
)


class PromptContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PromptFamily(StrEnum):
    WORKER = "worker"
    PARENT_ROOT = "parent_root"


class PromptRefKind(StrEnum):
    ARTIFACT = "artifact"
    CRITERIA = "criteria"
    CHECKPOINT = "checkpoint"
    TRANSIENT = "transient"
    WORKSPACE = "workspace"


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


class PromptInstructionGuidance(PromptContract):
    workflow: tuple[PromptText, ...] = ()
    role: tuple[PromptText, ...] = ()
    node: tuple[PromptText, ...] = ()
    policy: tuple[PromptText, ...] = ()


class PromptLogicalRef(PromptContract):
    kind: PromptRefKind
    logical_path: PromptLogicalPath
    purpose: PromptText
    description: PromptText
    slot: PromptIdentifier | None = None
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_ref_metadata(self) -> PromptLogicalRef:
        if self.kind == PromptRefKind.ARTIFACT:
            if self.slot is None or self.version is None:
                raise ValueError("artifact refs require slot and version")
            return self
        if self.version is not None:
            raise ValueError("only artifact refs may carry a version")
        return self


class PromptCriterion(PromptContract):
    slot: PromptIdentifier
    description: PromptText
    checks: tuple[PromptText, ...] = Field(min_length=1, max_length=32)
    logical_path: PromptLogicalPath | None = None


class PromptSlot(PromptContract):
    slot: PromptIdentifier
    kind: PromptRefKind
    description: PromptText
    logical_path: PromptLogicalPath | None = None
    version: int | None = Field(default=None, ge=1)


class PromptAssignmentBudget(PromptContract):
    child_assignment_limit: int | None = Field(default=None, ge=0)
    child_assignments_remaining: int | None = Field(default=None, ge=0)
    retry_limit: int | None = Field(default=None, ge=0)
    retries_remaining: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_remaining_budget(self) -> PromptAssignmentBudget:
        _validate_remaining_limit(
            name="child assignments",
            remaining=self.child_assignments_remaining,
            limit=self.child_assignment_limit,
        )
        _validate_remaining_limit(
            name="retries",
            remaining=self.retries_remaining,
            limit=self.retry_limit,
        )
        return self


class PromptAssignment(PromptContract):
    assignment_id: PromptIdentifier
    role_id: PromptIdentifier
    role_description: PromptText
    node_kind: NodeKind
    summary: PromptText
    instruction: PromptText | None = None
    criteria: tuple[PromptCriterion, ...] = ()
    consume_slots: tuple[PromptSlot, ...] = ()
    produce_slots: tuple[PromptSlot, ...] = ()
    budget: PromptAssignmentBudget | None = None


class PromptCheckpointSummary(PromptContract):
    checkpoint_id: PromptIdentifier
    logical_path: PromptLogicalPath
    summary: PromptText
    outcome: CheckpointOutcome
    refs: tuple[PromptLogicalRef, ...] = ()


class RootStartTrigger(PromptContract):
    kind: Literal["root_start"] = "root_start"
    flow_id: PromptIdentifier


class AcceptedBoundaryTrigger(PromptContract):
    kind: Literal["accepted_boundary"] = "accepted_boundary"
    accepted_boundary_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier
    outcome: Literal[EgressBoundary.YIELD]


class ChildReturnTrigger(PromptContract):
    kind: Literal["child_return"] = "child_return"
    child_assignment_id: PromptIdentifier
    child_attempt_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier
    accepted_boundary_id: PromptIdentifier
    outcome: Literal[EgressBoundary.GREEN, EgressBoundary.BLOCKED]
    checkpoint: PromptCheckpointSummary

    @model_validator(mode="after")
    def validate_checkpoint_outcome(self) -> ChildReturnTrigger:
        if self.checkpoint.outcome.value != self.outcome.value:
            raise ValueError("child-return checkpoint outcome must match the accepted outcome")
        return self


class HumanResultTrigger(PromptContract):
    kind: Literal["human_result"] = "human_result"
    request: PendingHumanRequest
    resolution: HumanRequestResolution

    @model_validator(mode="after")
    def validate_request_resolution_identity(self) -> HumanResultTrigger:
        if self.request.request_id != self.resolution.request_id:
            raise ValueError("human-result request and resolution IDs must match")
        if self.request.task_id != self.resolution.task_id:
            raise ValueError("human-result request and resolution tasks must match")
        if self.request.status == HumanRequestStatus.OPEN:
            raise ValueError("human-result trigger requires a terminal request")
        expected_status = {
            HumanRequestResolutionKind.ANSWERED: HumanRequestStatus.RESOLVED,
            HumanRequestResolutionKind.TIMED_OUT: HumanRequestStatus.TIMED_OUT,
            HumanRequestResolutionKind.CANCELLED: HumanRequestStatus.CANCELLED,
        }[self.resolution.resolution_kind]
        if self.request.status != expected_status:
            raise ValueError("human-result request status and resolution kind must match")
        return self


class PromptCommandResult(PromptContract):
    state: PromptCommandOutcome
    exit_code: int | None = None
    summary: PromptText
    started_at: datetime | None = None
    ended_at: datetime
    stdout_log_ref: PromptLogicalPath | None = None
    stderr_log_ref: PromptLogicalPath | None = None
    failure_code: PromptIdentifier | None = None
    terminal_event_source: PromptCommandTerminalSource
    terminal_actor_ref: PromptIdentifier | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> PromptCommandResult:
        if self.started_at is not None and self.ended_at < self.started_at:
            raise ValueError("command result cannot end before it starts")
        if (
            self.state == PromptCommandOutcome.ABANDONED
            and self.failure_code != "command_ownership_lost"
        ):
            raise ValueError("abandoned command results require command_ownership_lost")
        return self


class CommandResultTrigger(PromptContract):
    kind: Literal["command_result"] = "command_result"
    run_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier
    request: CommandRunStartRequest
    result: PromptCommandResult
    refs: tuple[PromptLogicalRef, ...] = ()


class WatchdogRecoveryTrigger(PromptContract):
    kind: Literal["watchdog_recovery"] = "watchdog_recovery"
    source_dispatch_id: PromptIdentifier
    recovery_count: int = Field(ge=1)


class SemanticRetryTrigger(PromptContract):
    kind: Literal["semantic_retry"] = "semantic_retry"
    accepted_boundary_id: PromptIdentifier
    source_dispatch_id: PromptIdentifier
    previous_attempt_id: PromptIdentifier
    checkpoint: PromptCheckpointSummary

    @model_validator(mode="after")
    def validate_retry_checkpoint(self) -> SemanticRetryTrigger:
        if self.checkpoint.outcome != CheckpointOutcome.RETRY:
            raise ValueError("semantic-retry trigger requires a retry checkpoint")
        return self


class OperatorContinueTrigger(PromptContract):
    kind: Literal["operator_continue"] = "operator_continue"
    source_dispatch_id: PromptIdentifier | None = None
    source_flow_id: PromptIdentifier | None = None
    control_revision: int = Field(ge=0)
    pause_reason: PromptText

    @model_validator(mode="after")
    def validate_exact_source(self) -> OperatorContinueTrigger:
        if (self.source_dispatch_id is None) == (self.source_flow_id is None):
            raise ValueError(
                "operator-continue trigger requires exactly one dispatch or flow-start source"
            )
        return self


type PromptTrigger = Annotated[
    RootStartTrigger
    | AcceptedBoundaryTrigger
    | ChildReturnTrigger
    | HumanResultTrigger
    | CommandResultTrigger
    | WatchdogRecoveryTrigger
    | SemanticRetryTrigger
    | OperatorContinueTrigger,
    Field(discriminator="kind"),
]

PROMPT_TRIGGER_KINDS = (
    "root_start",
    "accepted_boundary",
    "child_return",
    "human_result",
    "command_result",
    "watchdog_recovery",
    "semantic_retry",
    "operator_continue",
)


class PromptWorkflowNeighbor(PromptContract):
    node_key: PromptIdentifier
    node_kind: NodeKind
    relationship: PromptText
    assignment_id: PromptIdentifier | None = None


class RuntimeReadbackRefs(PromptContract):
    instructions: PromptLogicalPath
    input: PromptLogicalPath
    workflow_manifest: PromptLogicalPath


class PromptContext(PromptContract):
    capabilities: EffectiveCapabilitySet
    allowed_actions: tuple[PromptIdentifier, ...]
    workflow_neighborhood: tuple[PromptWorkflowNeighbor, ...] = ()
    readback_refs: RuntimeReadbackRefs
    refs: tuple[PromptLogicalRef, ...] = ()
    checkpoint_to_resume_from: PromptLogicalRef | None = None
    constraints: tuple[PromptText, ...] = ()


class PromptDispatch(PromptContract):
    task_id: PromptIdentifier
    flow_id: PromptIdentifier
    flow_revision_id: PromptIdentifier
    dispatch_id: PromptIdentifier
    assignment_id: PromptIdentifier
    attempt_id: PromptIdentifier
    node_key: PromptIdentifier
    node_kind: NodeKind
    parent_assignment_id: PromptIdentifier | None = None
    retry_of_attempt_id: PromptIdentifier | None = None
    predecessor_dispatch_id: PromptIdentifier | None = None


class PromptNext(PromptContract):
    instruction: PromptText
    inspect_refs: tuple[PromptLogicalRef, ...] = ()


class PromptDynamicInput(PromptContract):
    assignment: PromptAssignment
    trigger: PromptTrigger
    plan: WorkPlanRead | None
    context: PromptContext
    dispatch: PromptDispatch
    next: PromptNext

    @model_validator(mode="after")
    def validate_identity_and_role_ceiling(self) -> PromptDynamicInput:
        if self.assignment.assignment_id != self.dispatch.assignment_id:
            raise ValueError("assignment and dispatch IDs must match")
        if self.assignment.node_kind != self.dispatch.node_kind:
            raise ValueError("assignment and dispatch node kinds must match")
        if self.plan is not None and self.plan.assignment_id != self.assignment.assignment_id:
            raise ValueError("work plan must belong to the current assignment")
        if self.dispatch.node_kind == NodeKind.WORKER:
            illegal_actions = PARENT_ROOT_ACTIONS.intersection(self.context.allowed_actions)
            if illegal_actions:
                names = ", ".join(sorted(illegal_actions))
                raise ValueError(f"worker prompt exposes parent/root actions: {names}")
        return self


class DispatchRequestRenderInput(PromptContract):
    family: PromptFamily
    guidance: PromptInstructionGuidance
    dynamic_input: PromptDynamicInput

    @model_validator(mode="after")
    def validate_family(self) -> DispatchRequestRenderInput:
        expected = prompt_family_for_node_kind(self.dynamic_input.dispatch.node_kind)
        if self.family != expected:
            raise ValueError(
                f"prompt family '{self.family.value}' is invalid for "
                f"node kind '{self.dynamic_input.dispatch.node_kind.value}'"
            )
        return self


class RenderedDispatchRequest(PromptContract):
    instructions_text: PromptDocumentText
    input_text: PromptDocumentText


def prompt_family_for_node_kind(node_kind: NodeKind) -> PromptFamily:
    if node_kind == NodeKind.WORKER:
        return PromptFamily.WORKER
    return PromptFamily.PARENT_ROOT


def _validate_remaining_limit(*, name: str, remaining: int | None, limit: int | None) -> None:
    if limit is None and remaining is not None:
        raise ValueError(f"{name} remaining requires a limit")
    if limit is not None and remaining is not None and remaining > limit:
        raise ValueError(f"{name} remaining cannot exceed its limit")


__all__ = [
    "PROMPT_DYNAMIC_INPUT_KEYS",
    "PROMPT_TRIGGER_KINDS",
    "AcceptedBoundaryTrigger",
    "ChildReturnTrigger",
    "CommandResultTrigger",
    "DispatchRequestRenderInput",
    "HumanResultTrigger",
    "OperatorContinueTrigger",
    "PromptAssignment",
    "PromptAssignmentBudget",
    "PromptCheckpointSummary",
    "PromptCommandOutcome",
    "PromptCommandResult",
    "PromptCommandTerminalSource",
    "PromptContext",
    "PromptCriterion",
    "PromptDispatch",
    "PromptDynamicInput",
    "PromptFamily",
    "PromptInstructionGuidance",
    "PromptLogicalRef",
    "PromptNext",
    "PromptRefKind",
    "PromptSlot",
    "PromptTrigger",
    "PromptWorkflowNeighbor",
    "RenderedDispatchRequest",
    "RootStartTrigger",
    "RuntimeReadbackRefs",
    "SemanticRetryTrigger",
    "WatchdogRecoveryTrigger",
    "prompt_family_for_node_kind",
]
