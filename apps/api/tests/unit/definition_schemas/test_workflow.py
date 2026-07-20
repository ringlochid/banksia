from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from autoclaw.definitions.contracts import NodeKind, WorkflowDefinitionFile, WorkflowNodeInput
from pydantic import ValidationError

from .support import bounded_workflow_payload


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("inputs", {"legacy": "input"}),
        ("edges", [{"from": "root", "to": "implement_change"}]),
        ("skill_refs", ["legacy-skill"]),
    ],
)
def test_workflow_schema_rejects_removed_top_level_fields(
    field_name: str,
    field_value: Any,
) -> None:
    payload = bounded_workflow_payload()
    payload[field_name] = field_value

    with pytest.raises(ValidationError, match=field_name):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_workflow_schema_rejects_root_consumes() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["consumes"] = {"artifacts": [{"slot": "change_patch"}]}

    with pytest.raises(ValidationError, match="consumes"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_workflow_schema_rejects_duplicate_node_keys() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"].append(
        {
            "node_key": "implement_change",
            "kind": "worker",
            "role_id": "reviewer",
            "policy_id": "standard-worker",
            "description": "Duplicate node key.",
        }
    )

    with pytest.raises(ValidationError, match="duplicate node key"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_workflow_schema_rejects_duplicate_artifact_slots() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"].append(
        {
            "node_key": "review_change",
            "kind": "worker",
            "role_id": "reviewer",
            "policy_id": "standard-worker",
            "description": "Review the implementation evidence.",
            "produces": {
                "artifacts": [
                    {
                        "slot": "change_patch",
                        "description": "Duplicate artifact slot.",
                    }
                ]
            },
        }
    )

    with pytest.raises(ValidationError, match="duplicate artifact slot"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_workflow_schema_rejects_duplicate_criteria_slots() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"][0]["criteria"].append(
        {
            "slot": "implementation_rules",
            "description": "Duplicate criteria slot.",
            "criteria": ["This should fail."],
        }
    )

    with pytest.raises(ValidationError, match="duplicate criteria slot"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_workflow_schema_rejects_missing_consume_selector_targets_even_when_optional() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"][0]["consumes"] = {
        "artifacts": [{"slot": "findings_report", "required": False}],
        "criteria": [{"slot": "missing_criteria", "required": False}],
    }

    with pytest.raises(ValidationError, match="missing artifact consume selector target"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_workflow_schema_rejects_illegal_child_default_criteria_references() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["child_defaults"] = {"criteria": ["missing_root_rule"]}

    with pytest.raises(ValidationError, match=r"child_defaults\.criteria"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_child_defaults_consumes_participate_in_dependency_validation() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"].append(
        {
            "node_key": "review_change",
            "kind": "worker",
            "role_id": "reviewer",
            "policy_id": "standard-worker",
            "description": "Review the change.",
        }
    )
    payload["root"]["child_defaults"] = {"consumes": {"artifacts": [{"slot": "missing_artifact"}]}}

    with pytest.raises(ValidationError, match="missing artifact consume selector target"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_workflow_schema_rejects_cyclic_dependency_graph() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"] = [
        {
            "node_key": "first_child",
            "kind": "worker",
            "role_id": "engineer",
            "policy_id": "standard-worker",
            "description": "First sibling.",
            "consumes": {"artifacts": [{"slot": "second_output"}]},
            "produces": {
                "artifacts": [
                    {
                        "slot": "first_output",
                        "description": "First output.",
                    }
                ]
            },
        },
        {
            "node_key": "second_child",
            "kind": "worker",
            "role_id": "reviewer",
            "policy_id": "standard-worker",
            "description": "Second sibling.",
            "consumes": {"artifacts": [{"slot": "first_output"}]},
            "produces": {
                "artifacts": [
                    {
                        "slot": "second_output",
                        "description": "Second output.",
                    }
                ]
            },
        },
    ]

    with pytest.raises(ValidationError, match="cyclic dependency graph"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_removed_fields_are_rejected_on_nested_nodes() -> None:
    payload = bounded_workflow_payload()
    nested_child = deepcopy(payload["root"]["children"][0])
    nested_child["skill_refs"] = ["legacy-child-skill"]
    payload["root"]["children"][0] = nested_child

    with pytest.raises(ValidationError, match="skill_refs"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_removed_skill_refs_are_rejected_on_root_node() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["skill_refs"] = ["legacy-root-skill"]

    with pytest.raises(ValidationError, match="skill_refs"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


@pytest.mark.parametrize(
    ("target_field", "legacy_field"),
    [
        ("node_key", "id"),
        ("role_id", "role"),
        ("policy_id", "policy"),
    ],
)
@pytest.mark.parametrize("node_path", ["root", "child"])
def test_workflow_definition_rejects_legacy_authored_node_fields(
    target_field: str,
    legacy_field: str,
    node_path: str,
) -> None:
    payload = bounded_workflow_payload()
    node = payload["root"] if node_path == "root" else payload["root"]["children"][0]
    node[legacy_field] = node.pop(target_field)

    with pytest.raises(ValidationError, match=legacy_field):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


@pytest.mark.parametrize("required_field", ["kind", "policy_id"])
def test_workflow_definition_requires_target_node_fields(required_field: str) -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"][0].pop(required_field)

    with pytest.raises(ValidationError, match=required_field):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_workflow_definition_rejects_structural_kind_conflicts() -> None:
    root_kind_conflict = bounded_workflow_payload()
    root_kind_conflict["root"]["kind"] = "parent"
    with pytest.raises(ValidationError, match="kind"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **root_kind_conflict})

    worker_with_children = bounded_workflow_payload()
    child = worker_with_children["root"]["children"][0]
    child["children"] = [
        {
            "node_key": "nested_worker",
            "kind": "worker",
            "role_id": "engineer",
            "policy_id": "standard-worker",
            "description": "Nested worker that makes its parent structurally inconsistent.",
        }
    ]
    with pytest.raises(ValidationError, match="worker workflow nodes must not contain children"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **worker_with_children})


@pytest.mark.parametrize("provider_kind", ["codex", "claude", "openclaw"])
def test_workflow_nodes_accept_strict_portable_provider_selection(
    provider_kind: str,
) -> None:
    payload = bounded_workflow_payload()
    payload["root"]["provider"] = {"kind": provider_kind}
    payload["root"]["children"][0]["provider"] = {"kind": provider_kind}

    workflow = WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})

    assert workflow.root.provider is not None
    assert workflow.root.provider.kind == provider_kind
    assert workflow.root.children is not None
    assert workflow.root.children[0].provider is not None
    assert workflow.root.children[0].provider.kind == provider_kind


def test_workflow_nodes_accept_authored_node_instruction() -> None:
    payload = bounded_workflow_payload()
    payload["root"]["instruction"] = "Coordinate the current task lineage."
    payload["root"]["children"][0]["instruction"] = "Patch only the bounded slice."

    workflow = WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})

    assert workflow.root.instruction == "Coordinate the current task lineage."
    assert workflow.root.children is not None
    assert workflow.root.children[0].instruction == "Patch only the bounded slice."


@pytest.mark.parametrize(
    "provider",
    [
        "codex",
        {},
        {"kind": "local-shell"},
        {"kind": "codex", "model": "gpt-5"},
        {"kind": "claude", "effort": "high"},
        {"kind": "openclaw", "gateway_profile": "default"},
    ],
)
def test_workflow_nodes_reject_non_strict_provider_selection(provider: object) -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"][0]["provider"] = provider

    with pytest.raises(ValidationError, match=r"provider|kind"):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("provider_config", {"model": "gpt-5"}),
        ("transport", {"socket_path": "/tmp/provider.sock"}),
        ("auth_ref", "machine-local-secret"),
    ],
)
def test_workflow_nodes_reject_provider_local_configuration(
    field_name: str,
    field_value: Any,
) -> None:
    payload = bounded_workflow_payload()
    payload["root"]["children"][0][field_name] = field_value

    with pytest.raises(ValidationError, match=field_name):
        WorkflowDefinitionFile.model_validate({"kind": "workflow", **payload})


def test_portable_workflow_node_contract_accepts_authored_execution_intent() -> None:
    node = WorkflowNodeInput[NodeKind].model_validate(
        {
            "node_key": "implement_slice",
            "kind": "worker",
            "title": "Implement slice",
            "role_id": "engineer",
            "policy_id": "standard-worker",
            "provider": {"kind": "codex"},
            "description": "Implement the bounded slice.",
            "instruction": "Read the current criteria before patching.",
        }
    )

    assert node.model_dump(mode="json") == {
        "node_key": "implement_slice",
        "kind": "worker",
        "title": "Implement slice",
        "role_id": "engineer",
        "policy_id": "standard-worker",
        "provider": {"kind": "codex"},
        "description": "Implement the bounded slice.",
        "instruction": "Read the current criteria before patching.",
    }


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("id", "implement_slice"),
        ("role", "engineer"),
        ("policy", "standard-worker"),
        ("provider_preference", "codex"),
        ("transport", {"socket_path": "/tmp/provider.sock"}),
    ],
)
def test_portable_workflow_node_contract_rejects_non_portable_fields(
    field_name: str,
    field_value: Any,
) -> None:
    payload = {
        "node_key": "implement_slice",
        "kind": "worker",
        "role_id": "engineer",
        "policy_id": "standard-worker",
        "description": "Implement the bounded slice.",
    }
    payload[field_name] = field_value

    with pytest.raises(ValidationError, match=field_name):
        WorkflowNodeInput.model_validate(payload)


def test_portable_workflow_node_contract_requires_policy_reference() -> None:
    with pytest.raises(ValidationError, match="policy_id"):
        WorkflowNodeInput.model_validate(
            {
                "node_key": "implement_slice",
                "kind": "worker",
                "role_id": "engineer",
                "description": "Implement the bounded slice.",
            }
        )
