from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TypeVar

from pydantic import BaseModel

from autoclaw.definitions.compiler.contracts import (
    NormalizedChildDefaults,
    NormalizedConsumeBuckets,
    NormalizedCriteriaDeclaration,
    NormalizedDependencyEdge,
    NormalizedProduceBuckets,
)
from autoclaw.definitions.contracts.workflow import NodeKind, ProviderSelection
from autoclaw.persistence.models import FlowNodeModel
from autoclaw.runtime.providers import provider_selection_from_kind
from autoclaw.runtime.task_root import criteria_logical_path

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class StructuralCriteria:
    owner_node_key: str
    slot: str
    description: str
    criteria: tuple[str, ...]
    version: int | None = None
    path: str | None = None

    @property
    def signature(self) -> tuple[str, str, tuple[str, ...]]:
        return (self.slot, self.description, self.criteria)

    def as_normalized(self) -> NormalizedCriteriaDeclaration:
        return NormalizedCriteriaDeclaration(
            owner_node_key=self.owner_node_key,
            slot=self.slot,
            description=self.description,
            criteria=self.criteria,
        )

    def as_json(self) -> dict[str, object]:
        value: dict[str, object] = {
            "owner_node_key": self.owner_node_key,
            "slot": self.slot,
            "description": self.description,
            "criteria": list(self.criteria),
        }
        if self.version is not None:
            value["version"] = self.version
        if self.path is not None:
            value["path"] = self.path
        return value


@dataclass(frozen=True)
class StructuralNodeCandidate:
    node_key: str
    parent_node_key: str | None
    structural_kind: NodeKind
    role_key: str
    role_revision_no: int
    role_description: str
    role_instruction: str | None
    policy_key: str
    policy_revision_no: int
    policy_description: str | None
    policy_instruction: str | None
    provider: ProviderSelection | None
    description: str
    node_instruction: str | None
    local_consumes: NormalizedConsumeBuckets | None
    consumes: NormalizedConsumeBuckets | None
    produces: NormalizedProduceBuckets | None
    own_criteria: tuple[StructuralCriteria, ...]
    criteria: tuple[StructuralCriteria, ...]
    child_defaults: NormalizedChildDefaults | None
    child_node_keys: tuple[str, ...]
    state: str
    current_assignment_id: str | None
    order_index: int

    def with_runtime_projection(
        self,
        *,
        consumes: NormalizedConsumeBuckets | None,
        criteria: tuple[StructuralCriteria, ...],
        child_node_keys: tuple[str, ...],
        order_index: int,
    ) -> StructuralNodeCandidate:
        return replace(
            self,
            consumes=consumes,
            criteria=criteria,
            child_node_keys=child_node_keys,
            order_index=order_index,
        )

    def consumes_json(self) -> dict[str, object] | None:
        return _model_json(self.consumes)

    def produces_json(self) -> dict[str, object] | None:
        return _model_json(self.produces)

    def child_defaults_json(self) -> dict[str, object] | None:
        return _model_json(self.child_defaults)


@dataclass(frozen=True)
class StructuralRevisionCandidate:
    nodes: tuple[StructuralNodeCandidate, ...]
    dependency_edges: tuple[NormalizedDependencyEdge, ...]

    @property
    def nodes_by_key(self) -> dict[str, StructuralNodeCandidate]:
        return {node.node_key: node for node in self.nodes}

    def snapshot_json(self) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_key": node.node_key,
                    "parent_node_key": node.parent_node_key,
                    "node_kind": node.structural_kind.value,
                    "role": node.role_key,
                    "role_revision_no": node.role_revision_no,
                    "policy": node.policy_key,
                    "policy_revision_no": node.policy_revision_no,
                    "provider": (
                        node.provider.model_dump(mode="json") if node.provider is not None else None
                    ),
                    "description": node.description,
                    "instruction": node.node_instruction,
                    "children": list(node.child_node_keys),
                    "consumes": node.consumes_json(),
                    "produces": node.produces_json(),
                    "criteria": [criterion.as_json() for criterion in node.criteria],
                    "child_defaults": node.child_defaults_json(),
                }
                for node in self.nodes
            ],
            "dependency_edges": [edge.model_dump(mode="json") for edge in self.dependency_edges],
        }


def load_structural_nodes(
    rows: list[FlowNodeModel],
) -> dict[str, StructuralNodeCandidate]:
    raw_by_key = _load_raw_nodes(rows)
    return {
        node_key: _derive_local_inputs(node, raw_by_key) for node_key, node in raw_by_key.items()
    }


def relational_subtree(
    nodes: dict[str, StructuralNodeCandidate],
    root_node_key: str,
) -> set[str]:
    children_by_parent: dict[str, list[str]] = {}
    for node in nodes.values():
        if node.parent_node_key is not None:
            children_by_parent.setdefault(node.parent_node_key, []).append(node.node_key)
    owned: set[str] = set()
    pending = [root_node_key]
    while pending:
        node_key = pending.pop()
        if node_key in owned or node_key not in nodes:
            continue
        owned.add(node_key)
        pending.extend(children_by_parent.get(node_key, ()))
    return owned


def criteria_history(
    nodes: dict[str, StructuralNodeCandidate],
) -> dict[str, StructuralCriteria]:
    return {criterion.slot: criterion for node in nodes.values() for criterion in node.own_criteria}


def criteria_version_path(slot: str, version: int) -> str:
    return str(criteria_logical_path(slot=slot, version=version))


def _load_raw_nodes(
    rows: list[FlowNodeModel],
) -> dict[str, StructuralNodeCandidate]:
    nodes: dict[str, StructuralNodeCandidate] = {}
    for row in rows:
        if row.node_key in nodes:
            raise ValueError(f"duplicate node key '{row.node_key}'")
        consumes = _validate_optional(NormalizedConsumeBuckets, row.consumes_json)
        produces = _validate_optional(NormalizedProduceBuckets, row.produces_json)
        child_defaults = _validate_optional(
            NormalizedChildDefaults,
            row.child_defaults_json,
        )
        criteria = tuple(_criteria_from_json(row.node_key, value) for value in row.criteria_json)
        nodes[row.node_key] = StructuralNodeCandidate(
            node_key=row.node_key,
            parent_node_key=row.parent_node_key,
            structural_kind=NodeKind(row.structural_kind),
            role_key=row.role_key,
            role_revision_no=row.role_revision_no,
            role_description=row.role_description,
            role_instruction=row.role_instruction,
            policy_key=row.policy_key,
            policy_revision_no=row.policy_revision_no,
            policy_description=row.policy_description,
            policy_instruction=row.policy_instruction,
            provider=provider_selection_from_kind(row.provider_kind),
            description=row.description,
            node_instruction=row.node_instruction,
            local_consumes=consumes,
            consumes=consumes,
            produces=produces,
            own_criteria=criteria,
            criteria=criteria,
            child_defaults=child_defaults,
            child_node_keys=(),
            state=row.state,
            current_assignment_id=row.current_assignment_id,
            order_index=row.order_index,
        )
    return nodes


def _derive_local_inputs(
    node: StructuralNodeCandidate,
    nodes: dict[str, StructuralNodeCandidate],
) -> StructuralNodeCandidate:
    parent = nodes.get(node.parent_node_key) if node.parent_node_key is not None else None
    local_consumes = _remove_parent_consume_defaults(node.consumes, parent)
    own_criteria = tuple(
        criterion
        for criterion in node.criteria
        if _criterion_is_local(criterion, node=node, parent=parent)
    )
    return replace(
        node,
        local_consumes=local_consumes,
        own_criteria=own_criteria,
    )


def _criterion_is_local(
    criterion: StructuralCriteria,
    *,
    node: StructuralNodeCandidate,
    parent: StructuralNodeCandidate | None,
) -> bool:
    if criterion.owner_node_key != node.node_key:
        return False
    if parent is None or parent.child_defaults is None:
        return True
    if criterion.slot not in parent.child_defaults.criteria:
        return True
    return not any(
        parent_criterion.slot == criterion.slot
        and parent_criterion.signature == criterion.signature
        for parent_criterion in parent.criteria
    )


def _remove_parent_consume_defaults(
    consumes: NormalizedConsumeBuckets | None,
    parent: StructuralNodeCandidate | None,
) -> NormalizedConsumeBuckets | None:
    if consumes is None or parent is None or parent.child_defaults is None:
        return consumes
    defaults = parent.child_defaults.consumes
    if defaults is None:
        return consumes
    artifact_defaults = {selector.slot: selector for selector in defaults.artifacts}
    criteria_defaults = {selector.slot: selector for selector in defaults.criteria}
    artifacts = tuple(
        selector
        for selector in consumes.artifacts
        if artifact_defaults.get(selector.slot) != selector
    )
    criteria = tuple(
        selector
        for selector in consumes.criteria
        if criteria_defaults.get(selector.slot) != selector
    )
    if not artifacts and not criteria:
        return None
    return NormalizedConsumeBuckets(artifacts=artifacts, criteria=criteria)


def _criteria_from_json(
    fallback_owner_node_key: str,
    value: dict[str, object],
) -> StructuralCriteria:
    owner = value.get("owner_node_key")
    criteria = value.get("criteria")
    if not isinstance(criteria, list):
        raise ValueError("criteria projection must contain a criteria list")
    version = value.get("version")
    path = value.get("path")
    return StructuralCriteria(
        owner_node_key=owner if isinstance(owner, str) else fallback_owner_node_key,
        slot=str(value["slot"]),
        description=str(value["description"]),
        criteria=tuple(str(item) for item in criteria),
        version=version if isinstance(version, int) else None,
        path=path if isinstance(path, str) else None,
    )


def _validate_optional(
    model_type: type[ModelT],
    value: object | None,
) -> ModelT | None:
    if value is None:
        return None
    return model_type.model_validate(value)


def _model_json(model: BaseModel | None) -> dict[str, object] | None:
    if model is None:
        return None
    return model.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )


__all__ = [
    "StructuralCriteria",
    "StructuralNodeCandidate",
    "StructuralRevisionCandidate",
    "criteria_history",
    "criteria_version_path",
    "load_structural_nodes",
    "relational_subtree",
]
