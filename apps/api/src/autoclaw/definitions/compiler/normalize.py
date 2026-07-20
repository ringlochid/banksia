from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import TypeVar

from pydantic import BaseModel

from autoclaw.definitions.compiler.contracts import (
    DependencyKind,
    NormalizedChildDefaults,
    NormalizedCompiledNode,
    NormalizedConsumeBuckets,
    NormalizedConsumeSelector,
    NormalizedCriteriaDeclaration,
    NormalizedDependencyEdge,
    NormalizedProduceBuckets,
    NormalizedProduceSlot,
)
from autoclaw.definitions.compiler.role_policy_lookup import (
    PolicyRevisionDefinition,
    RolePolicyLookup,
    RoleRevisionDefinition,
)
from autoclaw.definitions.contracts.validation import (
    FlattenedNode,
    flatten_workflow,
    validate_acyclic_dependency_graph,
)
from autoclaw.definitions.contracts.workflow import (
    ChildDefaults,
    ConsumeBuckets,
    ConsumeSelector,
    CriteriaDeclaration,
    ProduceBuckets,
    ProduceSlot,
    RootNodeDefinition,
    WorkflowNode,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def flatten_and_index_workflow(
    root: RootNodeDefinition,
) -> tuple[
    tuple[FlattenedNode, ...],
    dict[str, FlattenedNode],
    dict[str, WorkflowNode],
    dict[str, tuple[str, ProduceSlot]],
    dict[str, tuple[str, CriteriaDeclaration]],
]:
    flattened_nodes = flatten_workflow(root)
    return (
        flattened_nodes,
        {node.node_id: node for node in flattened_nodes},
        build_authored_node_map(root),
        build_artifact_slot_map(flattened_nodes),
        build_criteria_slot_map(flattened_nodes),
    )


def build_authored_node_map(root: RootNodeDefinition) -> dict[str, WorkflowNode]:
    authored_nodes_by_key: dict[str, WorkflowNode] = {}

    def visit(node: WorkflowNode) -> None:
        authored_nodes_by_key[node.node_key] = node
        for child in node.children or ():
            visit(child)

    visit(root)
    return authored_nodes_by_key


def normalize_node(
    *,
    flattened_node: FlattenedNode,
    flattened_nodes_by_key: Mapping[str, FlattenedNode],
    authored_nodes_by_key: Mapping[str, WorkflowNode],
    criteria_slots: Mapping[str, tuple[str, CriteriaDeclaration]],
    lookup: RolePolicyLookup,
) -> NormalizedCompiledNode:
    resolved_role = resolve_role(flattened_node=flattened_node, lookup=lookup)
    resolved_policy = resolve_policy(flattened_node=flattened_node, lookup=lookup)
    parent_node = (
        flattened_nodes_by_key[flattened_node.parent_id]
        if flattened_node.parent_id is not None
        else None
    )
    authored_node = authored_nodes_by_key[flattened_node.node_id]

    return model_from_attrs(
        NormalizedCompiledNode,
        SimpleNamespace(
            node_key=flattened_node.node_id,
            parent_node_key=flattened_node.parent_id,
            child_node_keys=flattened_node.child_ids,
            structural_kind=flattened_node.node_kind,
            role=flattened_node.role,
            role_revision_no=resolved_role.revision_no,
            policy=flattened_node.policy,
            policy_revision_no=resolved_policy.revision_no,
            provider=authored_node.provider,
            description=authored_node.description,
            node_instruction=authored_node.instruction,
            consumes=expand_consumes(
                parent_child_defaults=parent_node.child_defaults if parent_node else None,
                local_consumes=flattened_node.consumes,
            ),
            produces=normalize_produces(flattened_node.produces),
            criteria=expand_criteria(
                current_node_key=flattened_node.node_id,
                parent_child_defaults=parent_node.child_defaults if parent_node else None,
                local_criteria=flattened_node.criteria,
                criteria_slots=criteria_slots,
            ),
            child_defaults=normalize_child_defaults(flattened_node.child_defaults),
            order_index=flattened_node.order,
        ),
    )


def build_artifact_slot_map(
    flattened_nodes: Sequence[FlattenedNode],
) -> dict[str, tuple[str, ProduceSlot]]:
    artifact_slots: dict[str, tuple[str, ProduceSlot]] = {}
    for flattened_node in flattened_nodes:
        artifacts = flattened_node.produces.artifacts if flattened_node.produces else ()
        for produce_slot in artifacts or ():
            artifact_slots[produce_slot.slot] = (flattened_node.node_id, produce_slot)
    return artifact_slots


def build_criteria_slot_map(
    flattened_nodes: Sequence[FlattenedNode],
) -> dict[str, tuple[str, CriteriaDeclaration]]:
    criteria_slots: dict[str, tuple[str, CriteriaDeclaration]] = {}
    for flattened_node in flattened_nodes:
        for criteria_declaration in flattened_node.criteria:
            criteria_slots[criteria_declaration.slot] = (
                flattened_node.node_id,
                criteria_declaration,
            )
    return criteria_slots


def expand_consumes(
    *,
    parent_child_defaults: ChildDefaults | None,
    local_consumes: ConsumeBuckets | None,
) -> NormalizedConsumeBuckets | None:
    default_consumes = parent_child_defaults.consumes if parent_child_defaults else None
    artifacts = merge_consume_selectors(
        default_selectors=default_consumes.artifacts if default_consumes else (),
        local_selectors=local_consumes.artifacts if local_consumes else (),
    )
    criteria = merge_consume_selectors(
        default_selectors=default_consumes.criteria if default_consumes else (),
        local_selectors=local_consumes.criteria if local_consumes else (),
    )
    if not artifacts and not criteria:
        return None
    return model_from_attrs(
        NormalizedConsumeBuckets,
        SimpleNamespace(artifacts=artifacts, criteria=criteria),
    )


def merge_consume_selectors(
    *,
    default_selectors: Sequence[ConsumeSelector] | None,
    local_selectors: Sequence[ConsumeSelector] | None,
) -> tuple[NormalizedConsumeSelector, ...]:
    merged: list[ConsumeSelector] = []
    index_by_slot: dict[str, int] = {}

    for selector in default_selectors or ():
        if selector.slot in index_by_slot:
            continue
        index_by_slot[selector.slot] = len(merged)
        merged.append(selector)

    for selector in local_selectors or ():
        existing_index = index_by_slot.get(selector.slot)
        if existing_index is None:
            index_by_slot[selector.slot] = len(merged)
            merged.append(selector)
            continue
        merged[existing_index] = selector

    return tuple(model_from_attrs(NormalizedConsumeSelector, selector) for selector in merged)


def expand_criteria(
    *,
    current_node_key: str,
    parent_child_defaults: ChildDefaults | None,
    local_criteria: Sequence[CriteriaDeclaration],
    criteria_slots: Mapping[str, tuple[str, CriteriaDeclaration]],
) -> tuple[NormalizedCriteriaDeclaration, ...]:
    expanded_criteria: list[SimpleNamespace] = []
    inherited_slots: set[str] = set()

    for slot in (
        parent_child_defaults.criteria
        if parent_child_defaults and parent_child_defaults.criteria
        else ()
    ):
        if slot in inherited_slots:
            continue
        inherited_slots.add(slot)
        owner_node_key, criteria_declaration = criteria_slots[slot]
        expanded_criteria.append(
            SimpleNamespace(
                owner_node_key=owner_node_key,
                slot=criteria_declaration.slot,
                description=criteria_declaration.description,
                criteria=criteria_declaration.criteria,
            )
        )

    expanded_criteria.extend(
        SimpleNamespace(
            owner_node_key=current_node_key,
            slot=criteria_declaration.slot,
            description=criteria_declaration.description,
            criteria=criteria_declaration.criteria,
        )
        for criteria_declaration in local_criteria
    )
    return tuple(
        model_from_attrs(NormalizedCriteriaDeclaration, criteria_source)
        for criteria_source in expanded_criteria
    )


def normalize_child_defaults(
    child_defaults: ChildDefaults | None,
) -> NormalizedChildDefaults | None:
    if child_defaults is None:
        return None

    consumes = normalize_consume_buckets(child_defaults.consumes)
    criteria = tuple(child_defaults.criteria or ())
    if consumes is None and not criteria:
        return None
    return model_from_attrs(
        NormalizedChildDefaults,
        SimpleNamespace(consumes=consumes, criteria=criteria),
    )


def normalize_consume_buckets(consumes: ConsumeBuckets | None) -> NormalizedConsumeBuckets | None:
    if consumes is None:
        return None

    artifacts = tuple(
        model_from_attrs(NormalizedConsumeSelector, selector)
        for selector in consumes.artifacts or ()
    )
    criteria = tuple(
        model_from_attrs(NormalizedConsumeSelector, selector)
        for selector in consumes.criteria or ()
    )
    if not artifacts and not criteria:
        return None
    return model_from_attrs(
        NormalizedConsumeBuckets,
        SimpleNamespace(artifacts=artifacts, criteria=criteria),
    )


def normalize_produces(produces: ProduceBuckets | None) -> NormalizedProduceBuckets | None:
    if produces is None:
        return None

    artifacts = tuple(
        model_from_attrs(NormalizedProduceSlot, produce_slot)
        for produce_slot in produces.artifacts or ()
    )
    if not artifacts:
        return None
    return model_from_attrs(NormalizedProduceBuckets, SimpleNamespace(artifacts=artifacts))


def build_dependency_edges(
    *,
    normalized_nodes: Sequence[NormalizedCompiledNode],
    artifact_slots: Mapping[str, tuple[str, ProduceSlot]],
    criteria_slots: Mapping[str, tuple[str, CriteriaDeclaration]],
) -> tuple[NormalizedDependencyEdge, ...]:
    dependency_edges: list[NormalizedDependencyEdge] = []

    for normalized_node in normalized_nodes:
        if normalized_node.consumes is None:
            continue

        for selector in normalized_node.consumes.artifacts:
            provider_node_key, produce_slot = artifact_slots.get(selector.slot, (None, None))
            if provider_node_key is None or produce_slot is None:
                raise ValueError(f"missing artifact consume selector target '{selector.slot}'")
            dependency_edges.append(
                model_from_attrs(
                    NormalizedDependencyEdge,
                    SimpleNamespace(
                        consumer_node_key=normalized_node.node_key,
                        provider_node_key=provider_node_key,
                        kind=DependencyKind.ARTIFACT,
                        slot=selector.slot,
                        description=produce_slot.description,
                        order_index=len(dependency_edges),
                    ),
                )
            )

        for selector in normalized_node.consumes.criteria:
            provider_node_key, criteria_declaration = criteria_slots.get(
                selector.slot,
                (None, None),
            )
            if provider_node_key is None or criteria_declaration is None:
                raise ValueError(f"missing criteria consume selector target '{selector.slot}'")
            dependency_edges.append(
                model_from_attrs(
                    NormalizedDependencyEdge,
                    SimpleNamespace(
                        consumer_node_key=normalized_node.node_key,
                        provider_node_key=provider_node_key,
                        kind=DependencyKind.CRITERIA,
                        slot=selector.slot,
                        description=criteria_declaration.description,
                        order_index=len(dependency_edges),
                    ),
                )
            )

    return tuple(dependency_edges)


def validate_compiled_dependency_graph(
    *,
    flattened_nodes: Sequence[FlattenedNode],
    dependency_edges: Sequence[NormalizedDependencyEdge],
) -> None:
    adjacency: dict[str, set[str]] = {node.node_id: set() for node in flattened_nodes}
    in_degree: dict[str, int] = {node.node_id: 0 for node in flattened_nodes}

    for dependency_edge in dependency_edges:
        if dependency_edge.consumer_node_key in adjacency[dependency_edge.provider_node_key]:
            continue
        adjacency[dependency_edge.provider_node_key].add(dependency_edge.consumer_node_key)
        in_degree[dependency_edge.consumer_node_key] += 1

    validate_acyclic_dependency_graph(
        flattened_nodes=flattened_nodes,
        adjacency=adjacency,
        in_degree=in_degree,
    )


def model_from_attrs(model_type: type[ModelT], source: object) -> ModelT:
    return model_type.model_validate(source, from_attributes=True)


def resolve_role(
    *,
    flattened_node: FlattenedNode,
    lookup: RolePolicyLookup,
) -> RoleRevisionDefinition:
    resolved_role = lookup.get_role(flattened_node.role)
    if resolved_role is None:
        raise ValueError(
            f"role '{flattened_node.role}' does not resolve for node '{flattened_node.node_id}'"
        )
    if flattened_node.node_kind not in resolved_role.definition.allowed_node_kinds:
        raise ValueError(
            f"role '{flattened_node.role}' is incompatible with node kind "
            f"'{flattened_node.node_kind}' for node '{flattened_node.node_id}'"
        )
    return resolved_role


def resolve_policy(
    *,
    flattened_node: FlattenedNode,
    lookup: RolePolicyLookup,
) -> PolicyRevisionDefinition:
    resolved_policy = lookup.get_policy(flattened_node.policy)
    if resolved_policy is None:
        raise ValueError(
            f"policy '{flattened_node.policy}' does not resolve for node '{flattened_node.node_id}'"
        )
    if flattened_node.node_kind not in resolved_policy.definition.applies_to:
        raise ValueError(
            f"policy '{flattened_node.policy}' is incompatible with node kind "
            f"'{flattened_node.node_kind}' for node '{flattened_node.node_id}'"
        )
    return resolved_policy
