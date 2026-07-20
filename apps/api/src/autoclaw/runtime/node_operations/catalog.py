from __future__ import annotations

from functools import partial

from autoclaw.definitions.contracts import (
    DefinitionRevisionDetailResponse,
    DefinitionSummaryListResponse,
)
from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts import (
    AddChildSuccess,
    AssignChildSuccess,
    BoundaryRead,
    CheckpointRead,
    CommandRunStartResponse,
    HumanRequestOpenResponse,
    ReleaseBlockedSuccess,
    ReleaseGreenSuccess,
    RemoveChildSuccess,
    UpdateChildSuccess,
)
from autoclaw.runtime.node_operations.contracts import (
    AddChildRequest,
    AssignChildRequest,
    EmptyNodeOperationRequest,
    GetCurrentContextResponse,
    GetDefinitionRequest,
    ListFilesRequest,
    ListFilesResponse,
    NodeOperationCapability,
    NodeOperationDescriptor,
    NodeOperationMutationKind,
    NodeOperationName,
    OpenHumanRequestRequest,
    ReadFileRequest,
    ReadFileResponse,
    RecordCheckpointRequest,
    ReleaseRequest,
    RemoveChildRequest,
    ReturnBoundaryRequest,
    SearchDefinitionsRequest,
    StartCommandRunRequest,
    UpdateChildRequest,
)
from autoclaw.runtime.work_plan import SetWorkPlanRequest, SetWorkPlanResponse

_ALL_NODE_KINDS = frozenset(NodeKind)
_PARENT_ROOT_NODE_KINDS = frozenset((NodeKind.PARENT, NodeKind.ROOT))
_ROOT_NODE_KIND = frozenset((NodeKind.ROOT,))
_descriptor = partial(
    NodeOperationDescriptor,
    allowed_node_kinds=_ALL_NODE_KINDS,
    required_capability=None,
    mutation_kind=NodeOperationMutationKind.MUTATION,
)


NODE_OPERATION_CATALOG: tuple[NodeOperationDescriptor, ...] = (
    _descriptor(
        NodeOperationName.GET_CURRENT_CONTEXT,
        EmptyNodeOperationRequest,
        GetCurrentContextResponse,
        mutation_kind=NodeOperationMutationKind.READ,
        title="Get current context",
        description="Read one coherent controller-owned context for the current dispatch.",
    ),
    _descriptor(
        NodeOperationName.LIST_FILES,
        ListFilesRequest,
        ListFilesResponse,
        mutation_kind=NodeOperationMutationKind.READ,
        title="List task files",
        description="List one contained logical task directory level.",
    ),
    _descriptor(
        NodeOperationName.READ_FILE,
        ReadFileRequest,
        ReadFileResponse,
        mutation_kind=NodeOperationMutationKind.READ,
        title="Read task file",
        description="Read a bounded UTF-8 range from a contained logical task file.",
    ),
    _descriptor(
        NodeOperationName.SET_WORK_PLAN,
        SetWorkPlanRequest,
        SetWorkPlanResponse,
        title="Set work plan",
        description="Replace or clear the advisory assignment-owned work plan.",
    ),
    _descriptor(
        NodeOperationName.RECORD_CHECKPOINT,
        RecordCheckpointRequest,
        CheckpointRead,
        title="Record checkpoint",
        description="Record durable progress or a terminal checkpoint on the current attempt.",
    ),
    _descriptor(
        NodeOperationName.RETURN_BOUNDARY,
        ReturnBoundaryRequest,
        BoundaryRead,
        title="Return boundary",
        description=(
            "Accept one semantic boundary and synchronously close the source dispatch. "
            "After success, stop the current outer response immediately; make no further "
            "tool calls or prose."
        ),
    ),
    _descriptor(
        NodeOperationName.OPEN_HUMAN_REQUEST,
        OpenHumanRequestRequest,
        HumanRequestOpenResponse,
        required_capability=NodeOperationCapability.HUMAN_REQUEST,
        title="Open human request",
        description=(
            "Commit one typed human wait and close the source dispatch. This is not a "
            "workflow boundary or task-continue action. After success, stop the current "
            "outer response immediately; make no further tool calls or prose."
        ),
    ),
    _descriptor(
        NodeOperationName.START_COMMAND_RUN,
        StartCommandRunRequest,
        CommandRunStartResponse,
        required_capability=NodeOperationCapability.COMMAND_RUN,
        title="Start command run",
        description=(
            "Commit one controller-managed command wait and close the source dispatch. "
            "Process launch happens after commit. After success, stop the current outer "
            "response immediately; make no further tool calls or prose."
        ),
    ),
    _descriptor(
        NodeOperationName.SEARCH_DEFINITIONS,
        SearchDefinitionsRequest,
        DefinitionSummaryListResponse,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        mutation_kind=NodeOperationMutationKind.READ,
        title="Search definitions",
        description="Search current role or policy definitions for structural planning.",
    ),
    _descriptor(
        NodeOperationName.GET_DEFINITION,
        GetDefinitionRequest,
        DefinitionRevisionDetailResponse,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        mutation_kind=NodeOperationMutationKind.READ,
        title="Get definition",
        description="Read one current role or policy definition.",
    ),
    _descriptor(
        NodeOperationName.ASSIGN_CHILD,
        AssignChildRequest,
        AssignChildSuccess,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        title="Assign child",
        description=(
            "Stage one direct-child assignment for a later yield boundary. This is legal "
            "only for the current parent/root dispatch and does not close that dispatch."
        ),
    ),
    _descriptor(
        NodeOperationName.ADD_CHILD,
        AddChildRequest,
        AddChildSuccess,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        title="Add child",
        description=(
            "Adopt a revision-safe structural child addition in the owned subtree. Reread "
            "current context and the regenerated manifest before staging later work."
        ),
    ),
    _descriptor(
        NodeOperationName.UPDATE_CHILD,
        UpdateChildRequest,
        UpdateChildSuccess,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        title="Update child",
        description=(
            "Adopt a revision-safe structural child update in the owned subtree. Reread "
            "current context and the regenerated manifest before staging later work."
        ),
    ),
    _descriptor(
        NodeOperationName.REMOVE_CHILD,
        RemoveChildRequest,
        RemoveChildSuccess,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        title="Remove child",
        description=(
            "Adopt a revision-safe structural child removal in the owned subtree. Reread "
            "current context and the regenerated manifest before staging later work."
        ),
    ),
    _descriptor(
        NodeOperationName.RELEASE_GREEN,
        ReleaseRequest,
        ReleaseGreenSuccess,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        title="Release green",
        description=(
            "Record evidence-backed green release readiness for the current parent/root "
            "dispatch without closing it; use only after required evidence is current."
        ),
    ),
    _descriptor(
        NodeOperationName.RELEASE_BLOCKED,
        ReleaseRequest,
        ReleaseBlockedSuccess,
        allowed_node_kinds=_ROOT_NODE_KIND,
        title="Release blocked",
        description=(
            "Record root-only whole-flow blocked release readiness without closing the "
            "dispatch; use only after required blocked evidence is current."
        ),
    ),
)

_DESCRIPTORS_BY_NAME = {descriptor.name: descriptor for descriptor in NODE_OPERATION_CATALOG}


def get_node_operation_descriptor(
    name: str | NodeOperationName,
) -> NodeOperationDescriptor:
    return _DESCRIPTORS_BY_NAME[NodeOperationName(name)]


def list_node_operation_descriptors_for_kind(
    node_kind: NodeKind,
) -> tuple[NodeOperationDescriptor, ...]:
    return tuple(
        descriptor
        for descriptor in NODE_OPERATION_CATALOG
        if node_kind in descriptor.allowed_node_kinds
    )


__all__ = [
    "NODE_OPERATION_CATALOG",
    "get_node_operation_descriptor",
    "list_node_operation_descriptors_for_kind",
]
