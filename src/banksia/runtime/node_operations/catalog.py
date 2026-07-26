from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from functools import partial

from banksia.runtime.contracts import (
    AddChildRequest,
    CheckpointRequest,
    CheckpointResponse,
    CommandRunStartResponse,
    DelegateRequest,
    DelegateSuccess,
    HumanRequestOpenResponse,
    RemoveChildRequest,
    ReplanSuccess,
    UpdateChildRequest,
)
from banksia.runtime.node_operations.contracts import (
    EmptyNodeOperationRequest,
    GetCurrentContextResponse,
    NodeOperationCapability,
    NodeOperationDescriptor,
    NodeOperationMutationKind,
    NodeOperationName,
    NodeOperationTransferKind,
    OpenHumanRequestRequest,
    StartCommandRunRequest,
)
from banksia.runtime.work_plan import SetWorkPlanRequest, SetWorkPlanResponse

_descriptor = partial(
    NodeOperationDescriptor,
    requires_direct_team=False,
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
        transfer_kind=NodeOperationTransferKind.TERMINAL_VARIANT,
    ),
    _descriptor(
        NodeOperationName.DELEGATE,
        DelegateRequest,
        DelegateSuccess,
        requires_direct_team=True,
        title="Delegate",
        description=(
            "Atomically start one to eight fresh Assignments for unique available direct "
            "children, close this Dispatch, and wait for the complete Wave. After success, "
            "stop immediately; make no further tool calls or prose."
        ),
        transfer_kind=NodeOperationTransferKind.ALWAYS_TRANSFERS,
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
        transfer_kind=NodeOperationTransferKind.ALWAYS_TRANSFERS,
    ),
    _descriptor(
        NodeOperationName.UPDATE_CHILD,
        UpdateChildRequest,
        ReplanSuccess,
        requires_direct_team=True,
        title="Update child",
        description=(
            "Update one current descendant and recursively upsert its direct descendants "
            "without changing IDs or order. Success closes this Dispatch; stop immediately."
        ),
        transfer_kind=NodeOperationTransferKind.ALWAYS_TRANSFERS,
    ),
    _descriptor(
        NodeOperationName.REMOVE_CHILD,
        RemoveChildRequest,
        ReplanSuccess,
        requires_direct_team=True,
        title="Remove child",
        description=(
            "Remove one current descendant subtree without erasing history. Success closes "
            "this Dispatch; stop immediately."
        ),
        transfer_kind=NodeOperationTransferKind.ALWAYS_TRANSFERS,
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
        transfer_kind=NodeOperationTransferKind.ALWAYS_TRANSFERS,
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
        transfer_kind=NodeOperationTransferKind.ALWAYS_TRANSFERS,
    ),
)

_DESCRIPTORS_BY_NAME = {descriptor.name: descriptor for descriptor in NODE_OPERATION_CATALOG}


@dataclass(frozen=True, slots=True)
class NodeOperationSelection:
    """Exact controller facts used to select one ordered operation ceiling."""

    has_direct_team: bool
    is_human_request_allowed: bool
    is_command_run_allowed: bool
    legal_operations: Collection[NodeOperationName] | None = None


def get_node_operation_descriptor(
    name: str | NodeOperationName,
) -> NodeOperationDescriptor:
    return _DESCRIPTORS_BY_NAME[NodeOperationName(name)]


def select_node_operation_descriptors(
    selection: NodeOperationSelection | None = None,
) -> tuple[NodeOperationDescriptor, ...]:
    """Select from the canonical catalog without changing its order."""

    if selection is None:
        return NODE_OPERATION_CATALOG
    legal_operations = (
        frozenset(selection.legal_operations) if selection.legal_operations is not None else None
    )
    return tuple(
        descriptor
        for descriptor in NODE_OPERATION_CATALOG
        if (not descriptor.requires_direct_team or selection.has_direct_team)
        and (legal_operations is None or descriptor.name in legal_operations)
        and _selection_allows_capability(descriptor, selection)
    )


def _selection_allows_capability(
    descriptor: NodeOperationDescriptor,
    selection: NodeOperationSelection,
) -> bool:
    if descriptor.required_capability is NodeOperationCapability.HUMAN_REQUEST:
        return selection.is_human_request_allowed
    if descriptor.required_capability is NodeOperationCapability.COMMAND_RUN:
        return selection.is_command_run_allowed
    return True


__all__ = [
    "NODE_OPERATION_CATALOG",
    "NodeOperationSelection",
    "get_node_operation_descriptor",
    "select_node_operation_descriptors",
]
