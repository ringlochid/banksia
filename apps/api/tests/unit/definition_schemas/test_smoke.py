from __future__ import annotations

import autoclaw.definitions.contracts as definition_schemas
from autoclaw.definitions.contracts import WorkflowDefinitionFile

from .support import (
    bounded_workflow_payload,
    resolve_committed_seed_definitions_root,
    workflow_validation_context,
)


def test_bounded_workflow_fixture_validates_against_packaged_catalog() -> None:
    with resolve_committed_seed_definitions_root() as definitions_root:
        context = workflow_validation_context(definitions_root)

    validated = WorkflowDefinitionFile.model_validate(
        {"kind": "workflow", **bounded_workflow_payload()},
        context=context,
    )

    assert validated.id == "bounded-change"
    assert validated.root.node_key == "root"
    assert validated.root.children is not None
    assert [child.node_key for child in validated.root.children] == ["implement_change"]


def test_definitions_package_does_not_export_private_validation_helpers() -> None:
    assert not hasattr(definition_schemas, "_build_dependency_graph")
    assert not hasattr(definition_schemas, "_flatten_workflow")
    assert not hasattr(definition_schemas, "_infer_node_kind")
    assert not hasattr(definition_schemas, "_validate_acyclic_dependency_graph")
