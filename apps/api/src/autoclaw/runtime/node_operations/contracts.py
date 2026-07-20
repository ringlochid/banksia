from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autoclaw.definitions.contracts import (
    DefinitionKind,
    DefinitionListSort,
)
from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts import (
    AddChildPayload,
    AssignChildPayload,
    CheckpointWriteBody,
    CommandRunStartRequest,
    EgressBoundary,
    HumanRequestOpenRequest,
    RemoveChildPayload,
    UpdateChildPayload,
)
from autoclaw.runtime.contracts.common import RuntimeSchemaText
from autoclaw.runtime.contracts.prompt import RuntimeReadbackRefs
from autoclaw.runtime.work_plan import WorkPlanRead


class NodeOperationName(StrEnum):
    GET_CURRENT_CONTEXT = "get_current_context"
    LIST_FILES = "list_files"
    READ_FILE = "read_file"
    SET_WORK_PLAN = "set_work_plan"
    RECORD_CHECKPOINT = "record_checkpoint"
    RETURN_BOUNDARY = "return_boundary"
    OPEN_HUMAN_REQUEST = "open_human_request"
    START_COMMAND_RUN = "start_command_run"
    SEARCH_DEFINITIONS = "search_definitions"
    GET_DEFINITION = "get_definition"
    ASSIGN_CHILD = "assign_child"
    ADD_CHILD = "add_child"
    UPDATE_CHILD = "update_child"
    REMOVE_CHILD = "remove_child"
    RELEASE_GREEN = "release_green"
    RELEASE_BLOCKED = "release_blocked"


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
    summary: RuntimeSchemaText
    instruction: RuntimeSchemaText | None = None
    criteria: tuple[dict[str, object], ...] = ()


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


class SlotContextRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: RuntimeSchemaText
    kind: Literal["artifact", "criteria", "checkpoint", "transient", "workspace"]
    description: RuntimeSchemaText
    path: RuntimeSchemaText | None = None
    version: int | None = Field(default=None, ge=1)


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
    consume_slots: tuple[SlotContextRead, ...]
    produce_slots: tuple[SlotContextRead, ...]
    continuation: dict[str, object] | None = None
    checkpoint_to_resume_from: RuntimeSchemaText | None = None


class ListFilesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory: str = "."


class FileEntryRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: RuntimeSchemaText
    path: RuntimeSchemaText
    kind: Literal["file", "directory", "symlink", "other"]
    size_bytes: int | None = Field(default=None, ge=0)


class ListFilesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory: RuntimeSchemaText
    entries: tuple[FileEntryRead, ...]


class ReadFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: RuntimeSchemaText
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=400, ge=1)


class ReadFileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: RuntimeSchemaText
    start_line: int = Field(ge=1)
    max_lines: int = Field(ge=1)
    content: str
    lines_returned: int = Field(ge=0)
    has_more: bool
    next_start_line: int | None = Field(default=None, ge=1)


class RecordCheckpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint: CheckpointWriteBody


class ReturnBoundaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    boundary: EgressBoundary


class OpenHumanRequestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: HumanRequestOpenRequest


class StartCommandRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: CommandRunStartRequest


class SearchDefinitionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[DefinitionKind.ROLE, DefinitionKind.POLICY]
    query: RuntimeSchemaText | None = None
    limit: int = Field(default=50, ge=1, le=100)
    cursor: RuntimeSchemaText | None = None
    sort: DefinitionListSort = DefinitionListSort.UPDATED_AT_DESC
    allowed_node_kind: NodeKind | None = None
    applies_to: NodeKind | None = None


class GetDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[DefinitionKind.ROLE, DefinitionKind.POLICY]
    key: RuntimeSchemaText


class StructuralOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_structural_revision_id: RuntimeSchemaText


class AssignChildRequest(StructuralOperationRequest):
    payload: AssignChildPayload


class AddChildRequest(StructuralOperationRequest):
    payload: AddChildPayload


class UpdateChildRequest(StructuralOperationRequest):
    payload: UpdateChildPayload


class RemoveChildRequest(StructuralOperationRequest):
    payload: RemoveChildPayload


class ReleaseRequest(StructuralOperationRequest):
    pass


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
    "FileEntryRead",
    "GetCurrentContextResponse",
    "GetDefinitionRequest",
    "HumanRequestCapabilityRead",
    "ListFilesRequest",
    "ListFilesResponse",
    "NodeOperationCapability",
    "NodeOperationDescriptor",
    "NodeOperationMutationKind",
    "NodeOperationName",
    "NodeOperationScope",
    "OpenHumanRequestRequest",
    "ReadFileRequest",
    "ReadFileResponse",
    "RecordCheckpointRequest",
    "ReleaseRequest",
    "RemoveChildRequest",
    "ReturnBoundaryRequest",
    "SearchDefinitionsRequest",
    "SlotContextRead",
    "StartCommandRunRequest",
    "StructuralOperationRequest",
    "UpdateChildRequest",
    "WorkflowNeighborRead",
]
