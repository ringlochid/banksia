from __future__ import annotations

from types import SimpleNamespace

from autoclaw.definitions.compiler.contracts import NormalizedCompiledPlan, WorkflowRevisionMetadata
from autoclaw.definitions.compiler.normalize import (
    build_dependency_edges,
    flatten_and_index_workflow,
    model_from_attrs,
    normalize_node,
    validate_compiled_dependency_graph,
)
from autoclaw.definitions.compiler.role_policy_lookup import RolePolicyLookup
from autoclaw.definitions.contracts.workflow import WorkflowDefinitionInput


def compile_workflow(
    *,
    workflow: WorkflowDefinitionInput,
    workflow_revision: WorkflowRevisionMetadata,
    compiler_version: str,
    lookup: RolePolicyLookup,
) -> NormalizedCompiledPlan:
    if workflow_revision.workflow_key != workflow.id:
        raise ValueError(
            "workflow revision metadata key "
            f"'{workflow_revision.workflow_key}' does not match workflow id '{workflow.id}'"
        )

    normalized_compiler_version = compiler_version.strip()
    if not normalized_compiler_version:
        raise ValueError("compiler_version must not be blank")

    (
        flattened_nodes,
        flattened_nodes_by_key,
        authored_nodes_by_key,
        artifact_slots,
        criteria_slots,
    ) = flatten_and_index_workflow(workflow.root)

    normalized_nodes = tuple(
        normalize_node(
            flattened_node=flattened_node,
            flattened_nodes_by_key=flattened_nodes_by_key,
            authored_nodes_by_key=authored_nodes_by_key,
            criteria_slots=criteria_slots,
            lookup=lookup,
        )
        for flattened_node in flattened_nodes
    )
    dependency_edges = build_dependency_edges(
        normalized_nodes=normalized_nodes,
        artifact_slots=artifact_slots,
        criteria_slots=criteria_slots,
    )
    validate_compiled_dependency_graph(
        flattened_nodes=flattened_nodes,
        dependency_edges=dependency_edges,
    )

    return model_from_attrs(
        NormalizedCompiledPlan,
        SimpleNamespace(
            workflow_key=workflow_revision.workflow_key,
            definition_revision_no=workflow_revision.definition_revision_no,
            compiler_version=normalized_compiler_version,
            nodes=normalized_nodes,
            dependency_edges=dependency_edges,
        ),
    )
