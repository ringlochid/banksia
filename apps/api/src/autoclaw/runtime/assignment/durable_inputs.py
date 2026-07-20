from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.definitions.compiler import NormalizedConsumeBuckets
from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    FlowEdgeModel,
    FlowNodeModel,
)
from autoclaw.runtime.errors import (
    illegal_state_error,
    missing_required_publication_error,
)


@dataclass(frozen=True, slots=True)
class AssignmentDurableInputs:
    criteria: tuple[dict[str, object], ...]
    consumes: tuple[dict[str, object], ...]


async def resolve_child_assignment_durable_inputs(
    session: AsyncSession,
    *,
    task_id: str,
    flow_id: str,
    flow_revision_id: str,
    target: FlowNodeModel,
) -> AssignmentDurableInputs:
    """Resolve authored child selectors to exact assignment-time refs."""

    selectors = NormalizedConsumeBuckets.model_validate(target.consumes_json or {})
    edges = await _read_target_edges(
        session,
        flow_revision_id=flow_revision_id,
        target_node_key=target.node_key,
    )
    criteria = [_compact_criterion(row) for row in target.criteria_json]
    consumes: list[dict[str, object]] = []

    for selector in selectors.criteria:
        edge = _require_edge(edges, kind="criteria", slot=selector.slot)
        provider = await _read_provider_node(
            session,
            flow_revision_id=flow_revision_id,
            provider_node_key=edge.provider_node_key,
        )
        criterion = _read_node_criterion(provider, slot=selector.slot)
        _append_unique_criterion(criteria, criterion)

    for selector in selectors.artifacts:
        edge = _require_edge(edges, kind="artifact", slot=selector.slot)
        provider = await _read_provider_node(
            session,
            flow_revision_id=flow_revision_id,
            provider_node_key=edge.provider_node_key,
        )
        publication = await _read_current_artifact_publication(
            session,
            task_id=task_id,
            flow_id=flow_id,
            provider=provider,
            slot=selector.slot,
            is_required=selector.required,
        )
        if publication is not None:
            consumes.append(_artifact_ref(publication))

    return AssignmentDurableInputs(
        criteria=tuple(criteria),
        consumes=tuple(consumes),
    )


async def read_assignment_prompt_criteria(
    session: AsyncSession,
    *,
    flow_revision_id: str,
    criteria_refs: list[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    """Expand compact assignment refs with immutable checks for prompt rendering."""

    if not criteria_refs:
        return ()
    unresolved_slots = {
        _required_text(row, "slot") for row in criteria_refs if not _has_nonempty_checks(row)
    }
    declarations = (
        await _read_criteria_declarations(
            session,
            flow_revision_id=flow_revision_id,
            slots=unresolved_slots,
        )
        if unresolved_slots
        else {}
    )
    expanded: list[dict[str, object]] = []
    for ref in criteria_refs:
        if _has_nonempty_checks(ref):
            expanded.append(dict(ref))
            continue
        slot = _required_text(ref, "slot")
        path = _required_text(ref, "path")
        declaration = declarations.get((slot, path))
        if declaration is None:
            raise ValueError(f"assignment criterion '{slot}' has no matching immutable generation")
        expanded.append(
            {
                "slot": slot,
                "path": path,
                "description": _required_text(ref, "description"),
                "version": ref.get("version", declaration.get("version")),
                "criteria": list(_required_checks(declaration)),
            }
        )
    return tuple(expanded)


async def _read_target_edges(
    session: AsyncSession,
    *,
    flow_revision_id: str,
    target_node_key: str,
) -> dict[tuple[str, str], FlowEdgeModel]:
    rows = tuple(
        await session.scalars(
            select(FlowEdgeModel)
            .options(raiseload("*"))
            .where(
                FlowEdgeModel.flow_revision_id == flow_revision_id,
                FlowEdgeModel.consumer_node_key == target_node_key,
            )
            .order_by(FlowEdgeModel.order_index)
        )
    )
    return {(row.kind, row.slot): row for row in rows}


def _require_edge(
    edges: dict[tuple[str, str], FlowEdgeModel],
    *,
    kind: str,
    slot: str,
) -> FlowEdgeModel:
    edge = edges.get((kind, slot))
    if edge is None:
        raise illegal_state_error(
            f"child assignment selector '{kind}:{slot}' has no compiled dependency edge"
        )
    return edge


async def _read_provider_node(
    session: AsyncSession,
    *,
    flow_revision_id: str,
    provider_node_key: str,
) -> FlowNodeModel:
    provider = await session.scalar(
        select(FlowNodeModel)
        .options(raiseload("*"))
        .where(
            FlowNodeModel.flow_revision_id == flow_revision_id,
            FlowNodeModel.node_key == provider_node_key,
        )
    )
    if provider is None:
        raise illegal_state_error(f"compiled dependency provider '{provider_node_key}' is missing")
    return provider


def _read_node_criterion(
    provider: FlowNodeModel,
    *,
    slot: str,
) -> dict[str, object]:
    matches = [_compact_criterion(row) for row in provider.criteria_json if row.get("slot") == slot]
    if len(matches) != 1:
        raise illegal_state_error(f"criteria dependency '{slot}' has no exact immutable generation")
    return matches[0]


def _append_unique_criterion(
    criteria: list[dict[str, object]],
    criterion: dict[str, object],
) -> None:
    slot = criterion["slot"]
    existing = next((row for row in criteria if row.get("slot") == slot), None)
    if existing is None:
        criteria.append(criterion)
        return
    if existing != criterion:
        raise illegal_state_error(f"assignment criteria slot '{slot}' is ambiguous")


async def _read_current_artifact_publication(
    session: AsyncSession,
    *,
    task_id: str,
    flow_id: str,
    provider: FlowNodeModel,
    slot: str,
    is_required: bool,
) -> ArtifactPublicationModel | None:
    assignment_id = provider.current_assignment_id
    if assignment_id is None:
        _reject_missing_required_artifact(slot=slot, is_required=is_required)
        return None
    pointer = await session.scalar(
        select(ArtifactCurrentPointerModel)
        .options(raiseload("*"))
        .where(
            ArtifactCurrentPointerModel.task_id == task_id,
            ArtifactCurrentPointerModel.flow_id == flow_id,
            ArtifactCurrentPointerModel.assignment_id == assignment_id,
            ArtifactCurrentPointerModel.slot == slot,
        )
    )
    if pointer is None:
        _reject_missing_required_artifact(slot=slot, is_required=is_required)
        return None
    publication = await session.get(
        ArtifactPublicationModel,
        pointer.current_publication_id,
        options=(raiseload("*"),),
    )
    if (
        publication is None
        or publication.task_id != task_id
        or publication.flow_id != flow_id
        or publication.assignment_id != assignment_id
        or publication.attempt_id != pointer.attempt_id
        or publication.checkpoint_id != pointer.checkpoint_id
        or publication.slot != slot
        or publication.version != pointer.current_version
    ):
        raise illegal_state_error(
            f"current artifact publication '{slot}' has inconsistent ownership"
        )
    return publication


def _reject_missing_required_artifact(
    *,
    slot: str,
    is_required: bool,
) -> None:
    if is_required:
        raise missing_required_publication_error(
            f"required child input '{slot}' has no current artifact publication"
        )
    return None


def _artifact_ref(publication: ArtifactPublicationModel) -> dict[str, object]:
    return {
        "kind": "artifact",
        "slot": publication.slot,
        "version": publication.version,
        "path": publication.logical_path,
        "description": publication.description,
    }


def _compact_criterion(row: dict[str, object]) -> dict[str, object]:
    criterion: dict[str, object] = {
        "slot": _required_text(row, "slot"),
        "path": _required_text(row, "path"),
        "description": _required_text(row, "description"),
    }
    version = row.get("version")
    if version is not None:
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise illegal_state_error("assignment criterion has an invalid version")
        criterion["version"] = version
    return criterion


async def _read_criteria_declarations(
    session: AsyncSession,
    *,
    flow_revision_id: str,
    slots: set[str],
) -> dict[tuple[str, str], dict[str, object]]:
    nodes = tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(FlowNodeModel.flow_revision_id == flow_revision_id)
            .order_by(FlowNodeModel.order_index)
        )
    )
    declarations: dict[tuple[str, str], dict[str, object]] = {}
    for node in nodes:
        for row in node.criteria_json:
            if row.get("slot") not in slots:
                continue
            key = (_required_text(row, "slot"), _required_text(row, "path"))
            previous = declarations.get(key)
            if previous is not None and _required_checks(previous) != _required_checks(row):
                raise ValueError(f"criterion '{key[0]}' has conflicting immutable checks")
            declarations[key] = row
    return declarations


def _has_nonempty_checks(row: dict[str, object]) -> bool:
    checks = row.get("criteria")
    return isinstance(checks, list) and bool(checks)


def _required_checks(row: dict[str, object]) -> tuple[str, ...]:
    checks = row.get("criteria")
    if not isinstance(checks, list) or not checks:
        raise ValueError("criterion generation requires nonempty checks")
    normalized = tuple(
        value.strip() for value in checks if isinstance(value, str) and value.strip()
    )
    if len(normalized) != len(checks):
        raise ValueError("criterion generation checks must be nonempty text")
    return normalized


def _required_text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise illegal_state_error(f"assignment criterion requires nonempty '{key}'")
    return value.strip()


__all__ = [
    "AssignmentDurableInputs",
    "read_assignment_prompt_criteria",
    "resolve_child_assignment_durable_inputs",
]
