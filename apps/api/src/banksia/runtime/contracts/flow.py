from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banksia.runtime.contracts.capabilities import (
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
)
from banksia.runtime.contracts.checkpoint import TaskResult
from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.refs import WorkflowManifestRef

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


type DispatchOpenedReason = Literal[
    "root",
    "delegation",
    "delegation_wave",
    "human_result",
    "command_result",
    "watchdog_recovery",
    "semantic_retry",
    "operator_continue",
    "structural_replan",
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


class EffectiveCapabilityReadback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    provider_native_access: EffectiveProviderNativeAccess
    network_access: EffectiveNetworkAccess


class RuntimeFlowRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    task_title: RuntimeSchemaText
    task_summary: RuntimeSchemaText
    workflow_key: RuntimeSchemaText | None = None
    status: RuntimeLifecycleStatus
    terminal_outcome: RuntimeFlowTerminalOutcome | None = None
    result: TaskResult | None = None
    active_flow_revision_id: RuntimeSchemaText
    control_revision: int = Field(ge=0)
    workflow_manifest_ref: WorkflowManifestRef
    pause_reason: RuntimeFlowPauseReason | None = None
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
        "blocked",
        "cancelled",
    ] = "any"


__all__ = [
    "DispatchOpenedReason",
    "EffectiveCapabilityReadback",
    "ProviderStartRetryKind",
    "RuntimeFlowControlRequest",
    "RuntimeFlowPauseReason",
    "RuntimeFlowPauseResponse",
    "RuntimeFlowRead",
    "RuntimeFlowSummary",
    "RuntimeFlowSummaryListResponse",
    "RuntimeFlowTerminalOutcome",
    "RuntimeLifecycleStatus",
    "RuntimeTaskListQuery",
    "WorkPlanRead",
    "WorkPlanStepRead",
]
