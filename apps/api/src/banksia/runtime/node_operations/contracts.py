from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banksia.runtime.contracts import (
    AddChildRequest,
    AssignChildPayload,
    CommandRunStartRequest,
    FileReference,
    HumanRequestOpenRequest,
    RemoveChildRequest,
    UpdateChildRequest,
)
from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.prompt import RuntimeReadbackRefs
from banksia.runtime.work_plan import WorkPlanRead


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


class NodeOperationScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: RuntimeSchemaText
    dispatch_id: RuntimeSchemaText
    provider_start_revision: int | None = Field(default=None, ge=0, exclude=True)


class EmptyNodeOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssignmentContextRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assignment_id: RuntimeSchemaText
    node_key: RuntimeSchemaText
    node_kind: NodeKind
    prompt: str
    files: tuple[FileReference, ...] = ()


class AttemptContextRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: RuntimeSchemaText
    assignment_id: RuntimeSchemaText
    retry_of_attempt_id: RuntimeSchemaText | None = None


class CurrentContextTriggerKind(StrEnum):
    ROOT_START = "root_start"
    ACCEPTED_BOUNDARY = "accepted_boundary"
    CHILD_RETURN = "child_return"
    HUMAN_RESULT = "human_result"
    COMMAND_RESULT = "command_result"
    WATCHDOG_RECOVERY = "watchdog_recovery"
    SEMANTIC_RETRY = "semantic_retry"
    STRUCTURAL_REPLAN = "structural_replan"
    OPERATOR_CONTINUE = "operator_continue"


class CurrentContextTriggerRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: CurrentContextTriggerKind
    source_dispatch_id: RuntimeSchemaText | None = None


class WorkflowNeighborRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_key: RuntimeSchemaText
    node_kind: NodeKind
    relationship: RuntimeSchemaText
    assignment_id: RuntimeSchemaText | None = None


class EffectiveValueRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    effective: RuntimeSchemaText
    source: RuntimeSchemaText


class HumanRequestCapabilityRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Literal["allow", "deny"]
    approval: Literal["allow", "deny"]
    input: Literal["allow", "deny"]
    review: Literal["allow", "deny"]


class EffectiveCapabilitySetRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dispatch_id: RuntimeSchemaText
    provider_native_access: EffectiveValueRead
    network_access: EffectiveValueRead
    human_request: HumanRequestCapabilityRead
    command_run: Literal["allow", "deny"]


class GetCurrentContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: RuntimeSchemaText
    dispatch_id: RuntimeSchemaText
    assignment: AssignmentContextRead
    attempt: AttemptContextRead
    trigger: CurrentContextTriggerRead
    plan: WorkPlanRead | None
    workflow_neighborhood: tuple[WorkflowNeighborRead, ...]
    readback_refs: RuntimeReadbackRefs
    capabilities: EffectiveCapabilitySetRead
    allowed_actions: tuple[NodeOperationName, ...]
    continuation: dict[str, object] | None = None


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


__all__ = [
    "AddChildRequest",
    "AssignChildRequest",
    "AssignmentContextRead",
    "AttemptContextRead",
    "CurrentContextTriggerKind",
    "CurrentContextTriggerRead",
    "EffectiveCapabilitySetRead",
    "EffectiveValueRead",
    "EmptyNodeOperationRequest",
    "GetCurrentContextResponse",
    "HumanRequestCapabilityRead",
    "NodeOperationCapability",
    "NodeOperationDescriptor",
    "NodeOperationMutationKind",
    "NodeOperationName",
    "NodeOperationScope",
    "OpenHumanRequestRequest",
    "RemoveChildRequest",
    "ReturnBoundaryRequest",
    "StartCommandRunRequest",
    "StructuralOperationRequest",
    "UpdateChildRequest",
    "WorkflowNeighborRead",
]
