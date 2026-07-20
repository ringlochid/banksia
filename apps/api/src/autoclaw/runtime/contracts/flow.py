from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.runtime.contracts.capabilities import (
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
)
from autoclaw.runtime.contracts.common import RuntimeSchemaText
from autoclaw.runtime.contracts.primitives import (
    CommandRunState,
    HumanRequestKind,
    HumanRequestStatus,
)
from autoclaw.runtime.contracts.provider_resolution import ProviderSelectionBasis
from autoclaw.runtime.contracts.refs import WorkflowManifestRef

type RuntimeFlowWaitingCause = Literal["human_request", "command_run"]
type RuntimeFlowTerminalOutcome = Literal["green", "blocked"]
type RuntimeFlowPauseReason = Literal[
    "paused_by_operator",
    "runtime_recovery_exhausted",
    "runtime_transition_failed",
]


class RuntimeLifecycleStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


type DispatchRuntimeStatus = Literal["starting", "open"]
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
type ProviderStartRetryKind = Literal[
    "initial",
    "definite_failure",
    "uncertain_acceptance",
]


class WorkPlanStepRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    step: RuntimeSchemaText
    status: Literal["pending", "in_progress", "completed"]


class WorkPlanRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    assignment_id: RuntimeSchemaText
    revision: int = Field(ge=1)
    explanation: RuntimeSchemaText | None = None
    steps: tuple[WorkPlanStepRead, ...] = Field(min_length=1, max_length=9)
    authored_by_dispatch_id: RuntimeSchemaText
    updated_at: datetime


class ProviderStartReadback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    revision: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    next_attempt_at: datetime | None = None
    retry_kind: ProviderStartRetryKind | None = None
    last_error_code: RuntimeSchemaText | None = None


class EffectiveCapabilityReadback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    provider_native_access: EffectiveProviderNativeAccess
    network_access: EffectiveNetworkAccess


class DispatchRuntimeRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    dispatch_id: RuntimeSchemaText
    predecessor_dispatch_id: RuntimeSchemaText | None = None
    assignment_id: RuntimeSchemaText
    attempt_id: RuntimeSchemaText
    status: DispatchRuntimeStatus
    opened_reason: DispatchOpenedReason
    requested_provider: ProviderKind
    resolved_provider: ProviderKind
    selection_basis: ProviderSelectionBasis
    adapter_started_at: datetime | None = None
    last_node_activity_at: datetime | None = None
    node_activity_revision: int = Field(ge=0)
    watchdog_due_at: datetime | None = None
    provider_start: ProviderStartReadback | None = None
    effective_capabilities: EffectiveCapabilityReadback


class HumanRequestSummary(BaseModel):
    """Bounded current-source readback without answers or policy payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    request_id: RuntimeSchemaText
    source_dispatch_id: RuntimeSchemaText
    kind: HumanRequestKind
    status: HumanRequestStatus
    summary: RuntimeSchemaText
    due_at: datetime | None = None
    opened_at: datetime


class CommandRunSummary(BaseModel):
    """Bounded current-source readback without command environment or log content."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    run_id: RuntimeSchemaText
    source_dispatch_id: RuntimeSchemaText
    state: CommandRunState
    summary: RuntimeSchemaText
    due_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None


class RuntimeFlowRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    task_title: RuntimeSchemaText
    task_summary: RuntimeSchemaText
    workflow_key: RuntimeSchemaText | None = None
    status: RuntimeLifecycleStatus
    terminal_outcome: RuntimeFlowTerminalOutcome | None = None
    active_flow_revision_id: RuntimeSchemaText
    control_revision: int = Field(ge=0)
    workflow_manifest_ref: WorkflowManifestRef
    current_node_key: RuntimeSchemaText | None = None
    active_assignment_id: RuntimeSchemaText | None = None
    active_attempt_id: RuntimeSchemaText | None = None
    waiting_cause: RuntimeFlowWaitingCause | None = None
    pause_reason: RuntimeFlowPauseReason | None = None
    current_dispatch: DispatchRuntimeRead | None = None
    latest_dispatch_id: RuntimeSchemaText | None = None
    current_plan: WorkPlanRead | None = None
    watchdog_recovery_count: int | None = Field(default=None, ge=0)
    current_human_request: HumanRequestSummary | None = None
    current_command_run: CommandRunSummary | None = None
    updated_at: datetime


class RuntimeFlowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    task_title: RuntimeSchemaText
    task_summary: RuntimeSchemaText
    workflow_key: RuntimeSchemaText | None = None
    status: RuntimeLifecycleStatus
    terminal_outcome: RuntimeFlowTerminalOutcome | None = None
    active_flow_revision_id: RuntimeSchemaText
    workflow_manifest_ref: WorkflowManifestRef
    current_node_key: RuntimeSchemaText | None = None
    active_assignment_id: RuntimeSchemaText | None = None
    active_attempt_id: RuntimeSchemaText | None = None
    updated_at: datetime


class RuntimeFlowSummaryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    items: tuple[RuntimeFlowSummary, ...]
    next_cursor: RuntimeSchemaText | None = None


class RuntimeFlowPauseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    flow: RuntimeFlowRead


class RuntimeFlowControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_active_flow_revision_id: RuntimeSchemaText
    expected_control_revision: int = Field(ge=0)


class RuntimeTaskListQuery(BaseModel):
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
        "cancelled",
    ] = "any"


__all__ = [
    "CommandRunSummary",
    "DispatchOpenedReason",
    "DispatchRuntimeRead",
    "DispatchRuntimeStatus",
    "EffectiveCapabilityReadback",
    "HumanRequestSummary",
    "ProviderStartReadback",
    "ProviderStartRetryKind",
    "RuntimeFlowControlRequest",
    "RuntimeFlowPauseReason",
    "RuntimeFlowPauseResponse",
    "RuntimeFlowRead",
    "RuntimeFlowSummary",
    "RuntimeFlowSummaryListResponse",
    "RuntimeFlowTerminalOutcome",
    "RuntimeFlowWaitingCause",
    "RuntimeLifecycleStatus",
    "RuntimeTaskListQuery",
    "WorkPlanRead",
    "WorkPlanStepRead",
]
