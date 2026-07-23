from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banksia.runtime.contracts import (
    AddChildRequest,
    AssignChildPayload,
    CommandRunStartRequest,
    HumanRequestOpenRequest,
    RemoveChildRequest,
    UpdateChildRequest,
)
from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.prompt import (
    PromptAssignment,
    PromptContinuation,
    PromptCurrentMember,
    PromptDirectMember,
    PromptDispatch,
    PromptTask,
    PromptWorkspace,
)
from banksia.runtime.work_plan import WorkPlanView


class NodeOperationName(StrEnum):
    GET_CURRENT_CONTEXT = "get_current_context"
    SET_WORK_PLAN = "set_work_plan"
    CHECKPOINT = "checkpoint"
    RETURN_BOUNDARY = "return_boundary"
    OPEN_HUMAN_REQUEST = "open_human_request"
    START_COMMAND_RUN = "start_command_run"
    ASSIGN_CHILD = "assign_child"
    ADD_CHILD = "add_child"
    UPDATE_CHILD = "update_child"
    REMOVE_CHILD = "remove_child"


class NodeOperationMutationKind(StrEnum):
    READ = "read"
    MUTATION = "mutation"


class NodeOperationCapability(StrEnum):
    HUMAN_REQUEST = "human_request"
    COMMAND_RUN = "command_run"


class NodeOperationTransferKind(StrEnum):
    STAYS_CURRENT = "stays_current"
    ALWAYS_TRANSFERS = "always_transfers"
    TERMINAL_VARIANT = "terminal_variant"


class NodeOperationScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: RuntimeSchemaText
    dispatch_id: RuntimeSchemaText
    provider_start_revision: int | None = Field(default=None, ge=0, exclude=True)


class EmptyNodeOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GetCurrentContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: PromptTask
    dispatch: PromptDispatch
    current_member: PromptCurrentMember
    assignment: PromptAssignment
    continuation: PromptContinuation | None = None
    direct_team: tuple[PromptDirectMember, ...] = ()
    work_plan: WorkPlanView | None = None
    available_actions: tuple[NodeOperationName, ...]
    workspace: PromptWorkspace
    observed_at: datetime


class ReturnBoundaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    boundary: Literal["yield"]


class OpenHumanRequestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: HumanRequestOpenRequest


class StartCommandRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: CommandRunStartRequest


class StructuralOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_structural_revision_id: RuntimeSchemaText


class AssignChildRequest(StructuralOperationRequest):
    payload: AssignChildPayload


@dataclass(frozen=True)
class NodeOperationDescriptor:
    name: NodeOperationName
    request_model: type[BaseModel]
    success_model: type[BaseModel]
    allowed_node_kinds: frozenset[NodeKind]
    required_capability: NodeOperationCapability | None
    mutation_kind: NodeOperationMutationKind
    title: str
    description: str
    transfer_kind: NodeOperationTransferKind = NodeOperationTransferKind.STAYS_CURRENT


__all__ = [
    "AddChildRequest",
    "AssignChildRequest",
    "EmptyNodeOperationRequest",
    "GetCurrentContextResponse",
    "NodeOperationCapability",
    "NodeOperationDescriptor",
    "NodeOperationMutationKind",
    "NodeOperationName",
    "NodeOperationScope",
    "NodeOperationTransferKind",
    "OpenHumanRequestRequest",
    "RemoveChildRequest",
    "ReturnBoundaryRequest",
    "StartCommandRunRequest",
    "StructuralOperationRequest",
    "UpdateChildRequest",
]
