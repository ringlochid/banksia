from __future__ import annotations

import pytest

from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.node_operations import (
    NODE_OPERATION_CATALOG,
    NodeOperationTransferKind,
    get_node_operation_descriptor,
    list_node_operation_descriptors_for_kind,
)
from banksia.runtime.node_operations.catalog import (
    NodeOperationSelection,
    select_node_operation_descriptors,
)
from banksia.runtime.node_operations.contracts import NodeOperationName
from banksia.runtime.work_plan import SetWorkPlanRequest

EXPECTED_OPERATION_NAMES = (
    "get_current_context",
    "set_work_plan",
    "checkpoint",
    "delegate",
    "add_child",
    "update_child",
    "remove_child",
    "open_human_request",
    "start_command_run",
)


def test_catalog_has_one_exact_node_kind_narrowed_operation_surface() -> None:
    assert tuple(descriptor.name.value for descriptor in NODE_OPERATION_CATALOG) == (
        EXPECTED_OPERATION_NAMES
    )
    assert len(list_node_operation_descriptors_for_kind(NodeKind.WORKER)) == 6
    assert len(list_node_operation_descriptors_for_kind(NodeKind.PARENT)) == 9
    assert len(list_node_operation_descriptors_for_kind(NodeKind.ROOT)) == 9
    for descriptor in NODE_OPERATION_CATALOG:
        request_properties = descriptor.request_model.model_json_schema().get("properties", {})
        assert "task_id" not in request_properties
        assert "dispatch_id" not in request_properties
        assert descriptor.request_model.model_config.get("extra") == "forbid"


def test_catalog_marks_every_control_transfer_and_terminal_checkpoint() -> None:
    for operation_name in (
        "delegate",
        "add_child",
        "update_child",
        "remove_child",
        "open_human_request",
        "start_command_run",
    ):
        descriptor = get_node_operation_descriptor(operation_name)
        assert descriptor.transfer_kind is NodeOperationTransferKind.ALWAYS_TRANSFERS
        description = descriptor.description.lower()
        assert "stop" in description and "immediately" in description

    checkpoint = get_node_operation_descriptor("checkpoint")
    assert checkpoint.transfer_kind is NodeOperationTransferKind.TERMINAL_VARIANT
    checkpoint_description = checkpoint.description.lower()
    assert "atomically finish" in checkpoint_description
    assert "green, blocked, or retry" in checkpoint_description
    assert "must_stop" in checkpoint_description
    assert "one to eight" in get_node_operation_descriptor("delegate").description


def test_catalog_selector_narrows_facts_without_changing_canonical_order() -> None:
    selected = select_node_operation_descriptors(
        NodeOperationSelection(
            node_kind=NodeKind.WORKER,
            is_human_request_allowed=False,
            is_command_run_allowed=False,
            legal_operations=(
                NodeOperationName.ADD_CHILD,
                NodeOperationName.CHECKPOINT,
                NodeOperationName.DELEGATE,
                NodeOperationName.GET_CURRENT_CONTEXT,
                NodeOperationName.OPEN_HUMAN_REQUEST,
            ),
        )
    )

    assert tuple(descriptor.name for descriptor in selected) == (
        NodeOperationName.GET_CURRENT_CONTEXT,
        NodeOperationName.CHECKPOINT,
        NodeOperationName.ADD_CHILD,
    )


def test_work_plan_contract_rejects_duplicate_and_multiple_active_steps() -> None:
    with pytest.raises(ValueError, match="distinct"):
        SetWorkPlanRequest.model_validate(
            {
                "steps": [
                    {"step": "Inspect", "status": "pending"},
                    {"step": "inspect", "status": "completed"},
                ]
            }
        )
    with pytest.raises(ValueError, match="at most one"):
        SetWorkPlanRequest.model_validate(
            {
                "steps": [
                    {"step": "Inspect", "status": "in_progress"},
                    {"step": "Patch", "status": "in_progress"},
                ]
            }
        )
