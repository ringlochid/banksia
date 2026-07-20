from __future__ import annotations

from collections.abc import Mapping, Sequence
from heapq import heappop, heappush
from types import SimpleNamespace
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, ValidationInfo

from autoclaw.definitions.contracts.workflow import (
    ChildDefaults,
    ConsumeBuckets,
    CriteriaDeclaration,
    NodeKind,
    ProduceBuckets,
    RootNodeDefinition,
    WorkflowDefinitionInput,
    WorkflowNode,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
WorkflowModelT = TypeVar("WorkflowModelT", bound=WorkflowDefinitionInput)


class FlattenedNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    node_id: str
    parent_id: str | None
    node_kind: NodeKind
    role: str
    policy: str
    consumes: ConsumeBuckets | None
    produces: ProduceBuckets | None
    criteria: tuple[CriteriaDeclaration, ...]
    child_defaults: ChildDefaults | None
    child_ids: tuple[str, ...]
    order: int


def validate_workflow_definition(
    workflow: WorkflowModelT,
    info: ValidationInfo,
) -> WorkflowModelT:
    flattened_nodes = flatten_workflow(workflow.root)

    node_ids: set[str] = set()
    artifact_slots: dict[str, str] = {}
    criteria_slots: dict[str, str] = {}

    for flattened_node in flattened_nodes:
        if flattened_node.node_id in node_ids:
            raise ValueError(f"duplicate node key '{flattened_node.node_id}'")
        node_ids.add(flattened_node.node_id)

        local_criteria_slots: set[str] = set()
        for criteria_declaration in flattened_node.criteria:
            if criteria_declaration.slot in criteria_slots:
                owner = criteria_slots[criteria_declaration.slot]
                raise ValueError(
                    "duplicate criteria slot "
                    f"'{criteria_declaration.slot}' on nodes '{owner}' and "
                    f"'{flattened_node.node_id}'"
                )
            criteria_slots[criteria_declaration.slot] = flattened_node.node_id
            local_criteria_slots.add(criteria_declaration.slot)

        for produce_slot in (
            flattened_node.produces.artifacts
            if flattened_node.produces and flattened_node.produces.artifacts
            else []
        ):
            if produce_slot.slot in artifact_slots:
                owner = artifact_slots[produce_slot.slot]
                raise ValueError(
                    "duplicate artifact slot "
                    f"'{produce_slot.slot}' on nodes '{owner}' and "
                    f"'{flattened_node.node_id}'"
                )
            artifact_slots[produce_slot.slot] = flattened_node.node_id

        if flattened_node.child_defaults and flattened_node.child_defaults.criteria:
            for slot in flattened_node.child_defaults.criteria:
                if slot not in local_criteria_slots:
                    raise ValueError(
                        "child_defaults.criteria on node "
                        f"'{flattened_node.node_id}' references unknown local criteria slot "
                        f"'{slot}'"
                    )

    adjacency, in_degree = build_dependency_graph(
        flattened_nodes=flattened_nodes,
        artifact_slots=artifact_slots,
        criteria_slots=criteria_slots,
    )
    validate_acyclic_dependency_graph(
        flattened_nodes=flattened_nodes,
        adjacency=adjacency,
        in_degree=in_degree,
    )
    _validate_registry_compatibility(flattened_nodes=flattened_nodes, info=info)

    return workflow


def flatten_workflow(root: RootNodeDefinition) -> tuple[FlattenedNode, ...]:
    flattened_nodes: list[FlattenedNode] = []

    def visit(node: WorkflowNode, parent_id: str | None) -> None:
        flattened_nodes.append(
            _model_from_attrs(
                FlattenedNode,
                _build_flattened_node_source(
                    node=node,
                    parent_id=parent_id,
                    order=len(flattened_nodes),
                ),
            )
        )
        for child in node.children or ():
            visit(child, node.node_key)

    visit(root, parent_id=None)
    return tuple(flattened_nodes)


def build_dependency_graph(
    *,
    flattened_nodes: Sequence[FlattenedNode],
    artifact_slots: Mapping[str, str],
    criteria_slots: Mapping[str, str],
) -> tuple[dict[str, set[str]], dict[str, int]]:
    adjacency: dict[str, set[str]] = {node.node_id: set() for node in flattened_nodes}
    in_degree: dict[str, int] = {node.node_id: 0 for node in flattened_nodes}

    for flattened_node in flattened_nodes:
        _resolve_consume_buckets(
            consumer_node_id=flattened_node.node_id,
            consumes=flattened_node.consumes,
            artifact_slots=artifact_slots,
            criteria_slots=criteria_slots,
            adjacency=adjacency,
            in_degree=in_degree,
        )

        if flattened_node.child_defaults and flattened_node.child_defaults.consumes:
            for child_id in flattened_node.child_ids:
                _resolve_consume_buckets(
                    consumer_node_id=child_id,
                    consumes=flattened_node.child_defaults.consumes,
                    artifact_slots=artifact_slots,
                    criteria_slots=criteria_slots,
                    adjacency=adjacency,
                    in_degree=in_degree,
                )

    return adjacency, in_degree


def validate_acyclic_dependency_graph(
    *,
    flattened_nodes: Sequence[FlattenedNode],
    adjacency: Mapping[str, set[str]],
    in_degree: Mapping[str, int],
) -> None:
    canonical_order = {node.node_id: node.order for node in flattened_nodes}
    queue: list[tuple[int, str]] = []
    remaining_in_degree = dict(in_degree)

    for node in flattened_nodes:
        if remaining_in_degree[node.node_id] == 0:
            heappush(queue, (canonical_order[node.node_id], node.node_id))

    emitted_count = 0
    while queue:
        _, node_id = heappop(queue)
        emitted_count += 1
        for successor_node_id in sorted(
            adjacency[node_id],
            key=lambda candidate: (canonical_order[candidate], candidate),
        ):
            remaining_in_degree[successor_node_id] -= 1
            if remaining_in_degree[successor_node_id] == 0:
                heappush(queue, (canonical_order[successor_node_id], successor_node_id))

    if emitted_count != len(flattened_nodes):
        raise ValueError("cyclic dependency graph")


def _resolve_consume_buckets(
    *,
    consumer_node_id: str,
    consumes: ConsumeBuckets | None,
    artifact_slots: Mapping[str, str],
    criteria_slots: Mapping[str, str],
    adjacency: dict[str, set[str]],
    in_degree: dict[str, int],
) -> None:
    if consumes is None:
        return

    for selector in consumes.artifacts or []:
        producer_node_id = artifact_slots.get(selector.slot)
        if producer_node_id is None:
            raise ValueError(f"missing artifact consume selector target '{selector.slot}'")
        _add_dependency_edge(
            producer_node_id=producer_node_id,
            consumer_node_id=consumer_node_id,
            adjacency=adjacency,
            in_degree=in_degree,
        )

    for selector in consumes.criteria or []:
        producer_node_id = criteria_slots.get(selector.slot)
        if producer_node_id is None:
            raise ValueError(f"missing criteria consume selector target '{selector.slot}'")
        _add_dependency_edge(
            producer_node_id=producer_node_id,
            consumer_node_id=consumer_node_id,
            adjacency=adjacency,
            in_degree=in_degree,
        )


def _add_dependency_edge(
    *,
    producer_node_id: str,
    consumer_node_id: str,
    adjacency: dict[str, set[str]],
    in_degree: dict[str, int],
) -> None:
    if consumer_node_id in adjacency[producer_node_id]:
        return
    adjacency[producer_node_id].add(consumer_node_id)
    in_degree[consumer_node_id] += 1


def _model_from_attrs(model_type: type[ModelT], source: object) -> ModelT:
    return model_type.model_validate(source, from_attributes=True)


def _build_flattened_node_source(
    *,
    node: WorkflowNode,
    parent_id: str | None,
    order: int,
) -> SimpleNamespace:
    children = node.children or []
    return SimpleNamespace(
        node_id=node.node_key,
        parent_id=parent_id,
        node_kind=node.kind,
        role=node.role_id,
        policy=node.policy_id,
        consumes=getattr(node, "consumes", None),
        produces=node.produces,
        criteria=tuple(node.criteria or []),
        child_defaults=node.child_defaults,
        child_ids=tuple(child.node_key for child in children),
        order=order,
    )


def _validate_registry_compatibility(
    *,
    flattened_nodes: Sequence[FlattenedNode],
    info: ValidationInfo,
) -> None:
    if info.context is None:
        return

    roles = info.context.get("roles")
    policies = info.context.get("policies")
    if not isinstance(roles, Mapping) or not isinstance(policies, Mapping):
        return

    for flattened_node in flattened_nodes:
        role = roles.get(flattened_node.role)
        if role is None:
            raise ValueError(
                f"role '{flattened_node.role}' does not resolve for node '{flattened_node.node_id}'"
            )
        if flattened_node.node_kind not in role.allowed_node_kinds:
            raise ValueError(
                f"role '{flattened_node.role}' is incompatible with node kind "
                f"'{flattened_node.node_kind}' for node '{flattened_node.node_id}'"
            )

        policy = policies.get(flattened_node.policy)
        if policy is None:
            raise ValueError(
                f"policy '{flattened_node.policy}' does not resolve for node "
                f"'{flattened_node.node_id}'"
            )
        if flattened_node.node_kind not in policy.applies_to:
            raise ValueError(
                f"policy '{flattened_node.policy}' is incompatible with node kind "
                f"'{flattened_node.node_kind}' for node '{flattened_node.node_id}'"
            )


__all__ = [
    "FlattenedNode",
    "build_dependency_graph",
    "flatten_workflow",
    "validate_acyclic_dependency_graph",
    "validate_workflow_definition",
]
