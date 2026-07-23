from __future__ import annotations

from functools import partial

from banksia.runtime.contracts import (
    AddChildRequest,
    AssignChildSuccess,
    BoundaryRead,
    CheckpointRequest,
    CheckpointResponse,
    CommandRunStartResponse,
    HumanRequestOpenResponse,
    RemoveChildRequest,
    ReplanSuccess,
    UpdateChildRequest,
)
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.node_operations.contracts import (
    AssignChildRequest,
    EmptyNodeOperationRequest,
    GetCurrentContextResponse,
    NodeOperationCapability,
    NodeOperationDescriptor,
    NodeOperationMutationKind,
    NodeOperationName,
    OpenHumanRequestRequest,
    ReturnBoundaryRequest,
    StartCommandRunRequest,
)
from banksia.runtime.work_plan import SetWorkPlanRequest, SetWorkPlanResponse

_ALL_NODE_KINDS = frozenset(NodeKind)
_PARENT_ROOT_NODE_KINDS = frozenset((NodeKind.PARENT, NodeKind.ROOT))
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
        NodeOperationName.SET_WORK_PLAN,
        SetWorkPlanRequest,
        SetWorkPlanResponse,
        title="Set work plan",
        description="Replace or clear the advisory assignment-owned work plan.",
    ),
    _descriptor(
        NodeOperationName.CHECKPOINT,
        CheckpointRequest,
        CheckpointResponse,
        title="Checkpoint",
        description=(
            "Record teammate-facing progress, or atomically finish the current Dispatch "
            "with green, blocked, or retry. Stop immediately when must_stop is true."
        ),
    ),
    _descriptor(
        NodeOperationName.RETURN_BOUNDARY,
        ReturnBoundaryRequest,
        BoundaryRead,
        title="Yield to staged child",
        description=(
            "Commit the migration-only staged-child yield and synchronously close the "
            "source dispatch. "
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
        NodeOperationName.ASSIGN_CHILD,
        AssignChildRequest,
        AssignChildSuccess,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        title="Assign child",
        description=(
            "Stage one direct-child assignment for a later yield boundary. A ready child "
            "starts its first assignment; a terminal child may receive a fresh assignment "
            "that supersedes its prior assignment. This is legal only for the current "
            "parent/root dispatch and does not close that dispatch."
        ),
    ),
    _descriptor(
        NodeOperationName.ADD_CHILD,
        AddChildRequest,
        ReplanSuccess,
        title="Add child",
        description=(
            "Add one controller-identified direct child and optional recursive subtree. "
            "Success closes this Dispatch; stop immediately and wait for the fresh "
            "same-Attempt continuation."
        ),
    ),
    _descriptor(
        NodeOperationName.UPDATE_CHILD,
        UpdateChildRequest,
        ReplanSuccess,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        title="Update child",
        description=(
            "Update one current descendant and recursively upsert its direct descendants "
            "without changing IDs or order. Success closes this Dispatch; stop immediately."
        ),
    ),
    _descriptor(
        NodeOperationName.REMOVE_CHILD,
        RemoveChildRequest,
        ReplanSuccess,
        allowed_node_kinds=_PARENT_ROOT_NODE_KINDS,
        title="Remove child",
        description=(
            "Remove one current descendant subtree without erasing history. Success closes "
            "this Dispatch; stop immediately."
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
