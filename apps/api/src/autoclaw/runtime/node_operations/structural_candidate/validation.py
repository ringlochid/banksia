from __future__ import annotations

from dataclasses import replace

from autoclaw.definitions.compiler.contracts import (
    NormalizedCompiledNode,
    NormalizedConsumeBuckets,
    NormalizedConsumeSelector,
    NormalizedProduceBuckets,
)
from autoclaw.definitions.compiler.normalize import (
    build_dependency_edges,
    validate_compiled_dependency_graph,
)
from autoclaw.definitions.contracts.validation import FlattenedNode
from autoclaw.definitions.contracts.workflow import (
    ChildDefaults,
    ConsumeBuckets,
    CriteriaDeclaration,
    NodeKind,
    ProduceBuckets,
    ProduceSlot,
)
from autoclaw.runtime.node_operations.structural_candidate.models import (
    StructuralCriteria,
    StructuralNodeCandidate,
    StructuralRevisionCandidate,
    criteria_version_path,
)


def build_structural_revision_candidate(
    nodes: dict[str, StructuralNodeCandidate],
    *,
    previous_criteria: dict[str, StructuralCriteria],
) -> StructuralRevisionCandidate:
    ordered = _validate_and_order_tree(nodes)
    versioned = _assign_criteria_versions(ordered, previous_criteria=previous_criteria)
    projected = _project_children_defaults(versioned)
    _validate_global_slots(projected)
    normalized_nodes = tuple(_normalized_compiler_node(node) for node in projected)
    artifact_slots = _artifact_slot_map(projected)
    criteria_slots = _criteria_slot_map(projected)
    edges = build_dependency_edges(
        normalized_nodes=normalized_nodes,
        artifact_slots=artifact_slots,
        criteria_slots=criteria_slots,
    )
    validate_compiled_dependency_graph(
        flattened_nodes=tuple(_flattened_node(node) for node in projected),
        dependency_edges=edges,
    )
    return StructuralRevisionCandidate(nodes=projected, dependency_edges=edges)


def _validate_and_order_tree(
    nodes: dict[str, StructuralNodeCandidate],
) -> tuple[StructuralNodeCandidate, ...]:
    if not nodes:
        raise ValueError("candidate structural graph must contain a root node")
    roots = [node for node in nodes.values() if node.parent_node_key is None]
    if len(roots) != 1:
        raise ValueError("candidate structural graph must contain exactly one root")
    root = roots[0]
    if root.structural_kind != NodeKind.ROOT:
        raise ValueError("candidate structural root must use root kind")

    children_by_parent: dict[str, list[StructuralNodeCandidate]] = {}
    for node in nodes.values():
        if node is root:
            continue
        if node.structural_kind == NodeKind.ROOT:
            raise ValueError(f"non-root node '{node.node_key}' cannot use root kind")
        if node.parent_node_key is None or node.parent_node_key not in nodes:
            raise ValueError(f"node '{node.node_key}' is missing its relational parent")
        if node.parent_node_key == node.node_key:
            raise ValueError(f"node '{node.node_key}' cannot parent itself")
        children_by_parent.setdefault(node.parent_node_key, []).append(node)

    for parent_key, children in children_by_parent.items():
        parent = nodes[parent_key]
        if parent.structural_kind == NodeKind.WORKER and children:
            raise ValueError(f"worker node '{parent_key}' cannot own structural children")
        children.sort(key=lambda child: (child.order_index, child.node_key))

    ordered: list[StructuralNodeCandidate] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: StructuralNodeCandidate) -> None:
        if node.node_key in visiting:
            raise ValueError("candidate structural parent graph is cyclic")
        if node.node_key in visited:
            return
        visiting.add(node.node_key)
        child_nodes = children_by_parent.get(node.node_key, [])
        next_node = replace(
            node,
            child_node_keys=tuple(child.node_key for child in child_nodes),
            order_index=len(ordered),
        )
        ordered.append(next_node)
        for child in child_nodes:
            visit(child)
        visiting.remove(node.node_key)
        visited.add(node.node_key)

    visit(root)
    if len(visited) != len(nodes):
        missing = sorted(set(nodes) - visited)
        raise ValueError(
            "candidate structural graph contains disconnected or cyclic nodes: "
            + ", ".join(missing)
        )
    return tuple(ordered)


def _assign_criteria_versions(
    nodes: tuple[StructuralNodeCandidate, ...],
    *,
    previous_criteria: dict[str, StructuralCriteria],
) -> tuple[StructuralNodeCandidate, ...]:
    result: list[StructuralNodeCandidate] = []
    for node in nodes:
        versioned: list[StructuralCriteria] = []
        for criterion in node.own_criteria:
            previous = previous_criteria.get(criterion.slot)
            if previous is not None and previous.signature == criterion.signature:
                version = previous.version or 1
                path = previous.path or criteria_version_path(criterion.slot, version)
            else:
                version = (previous.version if previous is not None else 0) or 0
                version += 1
                path = criteria_version_path(criterion.slot, version)
            versioned.append(replace(criterion, version=version, path=path))
        result.append(replace(node, own_criteria=tuple(versioned)))
    return tuple(result)


def _project_children_defaults(
    nodes: tuple[StructuralNodeCandidate, ...],
) -> tuple[StructuralNodeCandidate, ...]:
    nodes_by_key = {node.node_key: node for node in nodes}
    projected: list[StructuralNodeCandidate] = []
    for node in nodes:
        parent = nodes_by_key.get(node.parent_node_key) if node.parent_node_key else None
        consumes = _merge_parent_consumes(parent, node.local_consumes)
        inherited_criteria = _inherited_criteria(parent)
        projected.append(
            node.with_runtime_projection(
                consumes=consumes,
                criteria=(*inherited_criteria, *node.own_criteria),
                child_node_keys=node.child_node_keys,
                order_index=node.order_index,
            )
        )
    return tuple(projected)


def _merge_parent_consumes(
    parent: StructuralNodeCandidate | None,
    local: NormalizedConsumeBuckets | None,
) -> NormalizedConsumeBuckets | None:
    defaults = (
        parent.child_defaults.consumes
        if parent is not None and parent.child_defaults is not None
        else None
    )
    artifacts = _merge_selectors(
        defaults.artifacts if defaults is not None else (),
        local.artifacts if local is not None else (),
    )
    criteria = _merge_selectors(
        defaults.criteria if defaults is not None else (),
        local.criteria if local is not None else (),
    )
    if not artifacts and not criteria:
        return None
    return NormalizedConsumeBuckets(artifacts=artifacts, criteria=criteria)


def _merge_selectors(
    defaults: tuple[NormalizedConsumeSelector, ...],
    local: tuple[NormalizedConsumeSelector, ...],
) -> tuple[NormalizedConsumeSelector, ...]:
    _require_distinct_selectors(defaults)
    _require_distinct_selectors(local)
    merged = list(defaults)
    index_by_slot = {selector.slot: index for index, selector in enumerate(merged)}
    for selector in local:
        index = index_by_slot.get(selector.slot)
        if index is None:
            index_by_slot[selector.slot] = len(merged)
            merged.append(selector)
        else:
            merged[index] = selector
    return tuple(merged)


def _require_distinct_selectors(
    selectors: tuple[NormalizedConsumeSelector, ...],
) -> None:
    seen: set[str] = set()
    for selector in selectors:
        if selector.slot in seen:
            raise ValueError(f"duplicate consume selector '{selector.slot}'")
        seen.add(selector.slot)


def _inherited_criteria(
    parent: StructuralNodeCandidate | None,
) -> tuple[StructuralCriteria, ...]:
    if parent is None or parent.child_defaults is None:
        return ()
    own_by_slot = {criterion.slot: criterion for criterion in parent.own_criteria}
    inherited: list[StructuralCriteria] = []
    seen: set[str] = set()
    for slot in parent.child_defaults.criteria:
        if slot in seen:
            continue
        criterion = own_by_slot.get(slot)
        if criterion is None:
            raise ValueError(
                f"child_defaults.criteria on node '{parent.node_key}' references "
                f"unknown local criteria slot '{slot}'"
            )
        seen.add(slot)
        inherited.append(criterion)
    return tuple(inherited)


def _validate_global_slots(nodes: tuple[StructuralNodeCandidate, ...]) -> None:
    artifact_owners: dict[str, str] = {}
    criteria_owners: dict[str, str] = {}
    for node in nodes:
        _require_distinct_consumes(node)
        for artifact in node.produces.artifacts if node.produces else ():
            owner = artifact_owners.get(artifact.slot)
            if owner is not None:
                raise ValueError(
                    f"duplicate artifact slot '{artifact.slot}' on nodes "
                    f"'{owner}' and '{node.node_key}'"
                )
            artifact_owners[artifact.slot] = node.node_key
        for criterion in node.own_criteria:
            owner = criteria_owners.get(criterion.slot)
            if owner is not None:
                raise ValueError(
                    f"duplicate criteria slot '{criterion.slot}' on nodes "
                    f"'{owner}' and '{node.node_key}'"
                )
            criteria_owners[criterion.slot] = node.node_key


def _require_distinct_consumes(node: StructuralNodeCandidate) -> None:
    if node.consumes is None:
        return
    _require_distinct_selectors(node.consumes.artifacts)
    _require_distinct_selectors(node.consumes.criteria)


def _artifact_slot_map(
    nodes: tuple[StructuralNodeCandidate, ...],
) -> dict[str, tuple[str, ProduceSlot]]:
    return {
        artifact.slot: (
            node.node_key,
            ProduceSlot.model_validate(artifact.model_dump(mode="json")),
        )
        for node in nodes
        for artifact in (node.produces.artifacts if node.produces else ())
    }


def _criteria_slot_map(
    nodes: tuple[StructuralNodeCandidate, ...],
) -> dict[str, tuple[str, CriteriaDeclaration]]:
    return {
        criterion.slot: (
            node.node_key,
            CriteriaDeclaration(
                slot=criterion.slot,
                description=criterion.description,
                criteria=list(criterion.criteria),
            ),
        )
        for node in nodes
        for criterion in node.own_criteria
    }


def _normalized_compiler_node(node: StructuralNodeCandidate) -> NormalizedCompiledNode:
    return NormalizedCompiledNode(
        node_key=node.node_key,
        parent_node_key=node.parent_node_key,
        child_node_keys=node.child_node_keys,
        structural_kind=node.structural_kind,
        role=node.role_key,
        role_revision_no=node.role_revision_no,
        policy=node.policy_key,
        policy_revision_no=node.policy_revision_no,
        provider=node.provider,
        description=node.description,
        node_instruction=node.node_instruction,
        consumes=node.consumes,
        produces=node.produces,
        criteria=tuple(criterion.as_normalized() for criterion in node.criteria),
        child_defaults=node.child_defaults,
        order_index=node.order_index,
    )


def _flattened_node(node: StructuralNodeCandidate) -> FlattenedNode:
    return FlattenedNode(
        node_id=node.node_key,
        parent_id=node.parent_node_key,
        node_kind=node.structural_kind,
        role=node.role_key,
        policy=node.policy_key,
        consumes=_authored_consumes(node.consumes),
        produces=_authored_produces(node.produces),
        criteria=tuple(
            CriteriaDeclaration(
                slot=criterion.slot,
                description=criterion.description,
                criteria=list(criterion.criteria),
            )
            for criterion in node.own_criteria
        ),
        child_defaults=_authored_child_defaults(node),
        child_ids=node.child_node_keys,
        order=node.order_index,
    )


def _authored_consumes(value: NormalizedConsumeBuckets | None) -> ConsumeBuckets | None:
    if value is None:
        return None
    return ConsumeBuckets.model_validate(value.model_dump(mode="json", by_alias=True))


def _authored_produces(value: NormalizedProduceBuckets | None) -> ProduceBuckets | None:
    if value is None:
        return None
    return ProduceBuckets.model_validate(value.model_dump(mode="json"))


def _authored_child_defaults(node: StructuralNodeCandidate) -> ChildDefaults | None:
    if node.child_defaults is None:
        return None
    return ChildDefaults.model_validate(node.child_defaults.model_dump(mode="json", by_alias=True))


__all__ = ["build_structural_revision_candidate"]
