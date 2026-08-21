from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from oh_my_subagents.runtime.node_operations.activity import (
    NodeActivitySignal,
    NodeActivitySignalPublisher,
    create_watchdog_activity_publisher,
)
from oh_my_subagents.runtime.node_operations.catalog import (
    NODE_OPERATION_CATALOG,
    NodeOperationSelection,
    get_node_operation_descriptor,
    select_node_operation_descriptors,
)
from oh_my_subagents.runtime.node_operations.contracts import (
    DelegateRequest,
    EmptyNodeOperationRequest,
    GetCurrentContextResponse,
    NodeOperationCapability,
    NodeOperationDescriptor,
    NodeOperationMutationKind,
    NodeOperationName,
    NodeOperationScope,
    NodeOperationTransferKind,
    OpenHumanRequestRequest,
    StartCommandRunRequest,
)

if TYPE_CHECKING:
    from oh_my_subagents.runtime.node_operations.executor import NodeOperationExecutor

_LAZY_EXPORTS = {
    "NodeOperationExecutor": (
        "oh_my_subagents.runtime.node_operations.executor",
        "NodeOperationExecutor",
    ),
}


def __getattr__(name: str) -> Any:
    module_name, attribute_name = _LAZY_EXPORTS.get(name, (None, None))
    if module_name is None or attribute_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "NODE_OPERATION_CATALOG",
    "DelegateRequest",
    "EmptyNodeOperationRequest",
    "GetCurrentContextResponse",
    "NodeActivitySignal",
    "NodeActivitySignalPublisher",
    "NodeOperationCapability",
    "NodeOperationDescriptor",
    "NodeOperationExecutor",
    "NodeOperationMutationKind",
    "NodeOperationName",
    "NodeOperationScope",
    "NodeOperationSelection",
    "NodeOperationTransferKind",
    "OpenHumanRequestRequest",
    "StartCommandRunRequest",
    "create_watchdog_activity_publisher",
    "get_node_operation_descriptor",
    "select_node_operation_descriptors",
]
