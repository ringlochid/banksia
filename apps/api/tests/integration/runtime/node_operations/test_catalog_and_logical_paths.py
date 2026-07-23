from __future__ import annotations

import pytest
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import (
    NODE_OPERATION_CATALOG,
    get_node_operation_descriptor,
    list_node_operation_descriptors_for_kind,
)
from banksia.runtime.task_root.logical_paths import normalize_logical_task_path
from banksia.runtime.work_plan import SetWorkPlanRequest

EXPECTED_OPERATION_NAMES = (
    "get_current_context",
    "set_work_plan",
    "checkpoint",
    "return_boundary",
    "open_human_request",
    "start_command_run",
    "assign_child",
    "add_child",
    "update_child",
    "remove_child",
)


def test_catalog_has_one_exact_node_kind_narrowed_operation_surface() -> None:
    assert tuple(descriptor.name.value for descriptor in NODE_OPERATION_CATALOG) == (
        EXPECTED_OPERATION_NAMES
    )
    assert len(list_node_operation_descriptors_for_kind(NodeKind.WORKER)) == 7
    assert len(list_node_operation_descriptors_for_kind(NodeKind.PARENT)) == 10
    assert len(list_node_operation_descriptors_for_kind(NodeKind.ROOT)) == 10
    for descriptor in NODE_OPERATION_CATALOG:
        request_properties = descriptor.request_model.model_json_schema().get("properties", {})
        assert "task_id" not in request_properties
        assert "dispatch_id" not in request_properties
        assert descriptor.request_model.model_config.get("extra") == "forbid"


def test_catalog_preserves_terminal_and_child_assignment_teaching() -> None:
    for operation_name in (
        "return_boundary",
        "open_human_request",
        "start_command_run",
    ):
        description = get_node_operation_descriptor(operation_name).description.lower()
        assert "after success" in description
        assert "stop the current outer response" in description
        assert "no further tool calls or prose" in description

    checkpoint_description = get_node_operation_descriptor("checkpoint").description.lower()
    assert "atomically finish" in checkpoint_description
    assert "green, blocked, or retry" in checkpoint_description
    assert "must_stop" in checkpoint_description
    assert "parent/root" in get_node_operation_descriptor("assign_child").description
    assert "staged-child yield" in get_node_operation_descriptor("return_boundary").description


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


@pytest.mark.parametrize(
    "value",
    ("", "/tmp/x", "../x", "workspace/../x", "C:/x", "\\\\server\\x", "workspace\\x"),
)
def test_logical_path_rejects_nonportable_or_traversing_values(value: str) -> None:
    with pytest.raises(RuntimeOperationError):
        normalize_logical_task_path(value)
