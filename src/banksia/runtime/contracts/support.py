from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from banksia.runtime.contracts.capabilities import (
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
)
from banksia.runtime.contracts.primitives import CheckpointOutcome
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.task_events import TaskEventRecord
from banksia.runtime.contracts.team_read import MemberBehavior
from banksia.runtime.task_control.contracts import (
    ControllerTaskState,
    ControllerTaskSummary,
)


class _SupportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class SupportEffectiveCapabilityReadback(_SupportModel):
    provider_native_access: EffectiveProviderNativeAccess
    network_access: EffectiveNetworkAccess


class SupportActionableItem(_SupportModel):
    summary: str
    member_id: str | None = None
    current_paths: tuple[FileReference, ...] = ()
    suggested_action: str | None = None


class SupportTaskSearchResponse(_SupportModel):
    items: tuple[ControllerTaskSummary, ...]
    next_cursor: str | None = None


class SupportTaskSnapshot(_SupportModel):
    task: ControllerTaskState
    top_actionable_items: tuple[SupportActionableItem, ...]
    current_paths: tuple[FileReference, ...] = ()
    stream_head_event_id: str | None = None


class SupportDispatchTraceEntry(_SupportModel):
    kind: Literal["dispatch"] = "dispatch"
    dispatch_id: str
    predecessor_dispatch_id: str | None = None
    assignment_id: str
    attempt_id: str
    member_id: str
    status: Literal["starting", "open", "closed"]
    opened_reason: str
    closed_reason: str | None = None
    requested_provider: Literal["codex", "claude", "openclaw"]
    resolved_provider: Literal["codex", "claude", "openclaw"]
    selection_basis: Literal["explicit", "default"]
    adapter_started_at: datetime | None = None
    last_node_activity_at: datetime | None = None
    node_activity_revision: int = Field(ge=0)
    effective_capabilities: SupportEffectiveCapabilityReadback
    created_at: datetime
    closed_at: datetime | None = None


class SupportCheckpointTraceEntry(_SupportModel):
    kind: Literal["checkpoint"] = "checkpoint"
    checkpoint_id: str
    attempt_id: str
    outcome: CheckpointOutcome | None = None
    summary: str
    details: str | None = None
    files: tuple[FileReference, ...] = ()
    recorded_at: datetime


class SupportBoundaryTraceEntry(_SupportModel):
    kind: Literal["boundary"] = "boundary"
    source_dispatch_id: str
    member_id: str
    boundary: CheckpointOutcome
    checkpoint_id: str | None = None
    successor_dispatch_id: str | None = None
    occurred_at: datetime


class SupportTeamMemberEntry(_SupportModel):
    member_id: str
    parent_member_id: str | None = None
    is_task_lead: bool
    behavior: MemberBehavior
    member_configuration_id: str
    member_branch_basis_id: str
    member_title: str | None = None
    description: str | None = None
    preorder_index: int
    child_member_ids: tuple[str, ...] = ()


type SupportTraceEntry = Annotated[
    SupportDispatchTraceEntry | SupportCheckpointTraceEntry | SupportBoundaryTraceEntry,
    Field(discriminator="kind"),
]


class SupportTaskTracePage(_SupportModel):
    task_id: str
    team_members: tuple[SupportTeamMemberEntry, ...] = ()
    entries: tuple[SupportTraceEntry, ...]
    current_paths: tuple[FileReference, ...] = ()
    next_cursor: str | None = None


class SupportTaskTraceQuery(_SupportModel):
    q: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None
    sort: Literal["occurred_at_desc", "occurred_at_asc"] = "occurred_at_desc"


class SupportTaskEventPage(_SupportModel):
    task_id: str
    items: tuple[TaskEventRecord, ...]
    next_cursor: str | None = None


__all__ = [
    "SupportActionableItem",
    "SupportBoundaryTraceEntry",
    "SupportCheckpointTraceEntry",
    "SupportDispatchTraceEntry",
    "SupportEffectiveCapabilityReadback",
    "SupportTaskEventPage",
    "SupportTaskSearchResponse",
    "SupportTaskSnapshot",
    "SupportTaskTracePage",
    "SupportTaskTraceQuery",
    "SupportTeamMemberEntry",
    "SupportTraceEntry",
]
