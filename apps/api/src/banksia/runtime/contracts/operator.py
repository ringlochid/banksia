from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.flow import EffectiveCapabilityReadback, RuntimeFlowRead
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.primitives import CheckpointOutcome, EgressBoundary
from banksia.runtime.contracts.refs import FileReference

type OperatorCurrentPaths = tuple[FileReference, ...]


class TopActionableItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    summary: RuntimeSchemaText
    node_key: RuntimeSchemaText | None = None
    current_paths: OperatorCurrentPaths = ()
    suggested_action: RuntimeSchemaText | None = None


class OperatorFlowSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    flow: RuntimeFlowRead
    top_actionable_items: tuple[TopActionableItem, ...]
    current_paths: OperatorCurrentPaths = ()
    stream_head_event_id: RuntimeSchemaText | None = None


class DispatchHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    dispatch_id: RuntimeSchemaText
    predecessor_dispatch_id: RuntimeSchemaText | None = None
    assignment_id: RuntimeSchemaText
    attempt_id: RuntimeSchemaText
    node_key: RuntimeSchemaText
    status: Literal["starting", "open", "closed"]
    opened_reason: RuntimeSchemaText
    closed_reason: RuntimeSchemaText | None = None
    requested_provider: Literal["codex", "claude", "openclaw"]
    resolved_provider: Literal["codex", "claude", "openclaw"]
    selection_basis: Literal["explicit", "default"]
    adapter_started_at: datetime | None = None
    last_node_activity_at: datetime | None = None
    node_activity_revision: int = Field(ge=0)
    effective_capabilities: EffectiveCapabilityReadback
    created_at: datetime
    closed_at: datetime | None = None


class CheckpointHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    checkpoint_id: RuntimeSchemaText
    attempt_id: RuntimeSchemaText
    outcome: CheckpointOutcome | None = None
    summary: RuntimeSchemaText
    details: str | None = None
    files: tuple[FileReference, ...] = ()
    recorded_at: datetime


class BoundaryHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    source_dispatch_id: RuntimeSchemaText
    node_key: RuntimeSchemaText
    boundary: EgressBoundary
    checkpoint_id: RuntimeSchemaText | None = None
    successor_dispatch_id: RuntimeSchemaText | None = None
    occurred_at: datetime


class TaskGraphNodeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    node_key: RuntimeSchemaText
    parent_node_key: RuntimeSchemaText | None = None
    node_kind: NodeKind
    member_id: RuntimeSchemaText
    member_configuration_id: RuntimeSchemaText
    member_branch_basis_id: RuntimeSchemaText
    member_title: RuntimeSchemaText | None = None
    description: RuntimeSchemaText
    order_index: int
    child_node_keys: tuple[RuntimeSchemaText, ...] = ()


class OperatorFlowTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    scope: Literal["current", "whole"] = "current"
    graph_nodes: tuple[TaskGraphNodeEntry, ...] = ()
    dispatch_history: tuple[DispatchHistoryEntry, ...]
    checkpoint_history: tuple[CheckpointHistoryEntry, ...]
    boundary_history: tuple[BoundaryHistoryEntry, ...]
    current_paths: OperatorCurrentPaths = ()
    next_cursor: RuntimeSchemaText | None = None


class OperatorFlowTraceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Literal["current", "whole"] = "current"
    q: RuntimeSchemaText | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: RuntimeSchemaText | None = None
    sort: Literal["occurred_at_desc", "occurred_at_asc"] = "occurred_at_desc"


__all__ = [
    "BoundaryHistoryEntry",
    "CheckpointHistoryEntry",
    "DispatchHistoryEntry",
    "OperatorFlowSnapshotResponse",
    "OperatorFlowTraceQuery",
    "OperatorFlowTraceResponse",
    "TaskGraphNodeEntry",
    "TopActionableItem",
]
