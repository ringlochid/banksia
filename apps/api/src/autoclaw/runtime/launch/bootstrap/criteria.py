from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.compiler import NormalizedCompiledNode
from autoclaw.persistence.models import AssignmentCriteriaRefModel, AssignmentModel
from autoclaw.runtime.ids import assignment_criteria_ref_id
from autoclaw.runtime.projection.signals import CriteriaProjection
from autoclaw.runtime.task_root import criteria_logical_path


def build_node_criteria_json(
    *,
    node: NormalizedCompiledNode,
) -> list[dict[str, Any]]:
    return [
        criteria.model_dump(mode="json")
        | {
            "version": 1,
            "path": str(criteria_logical_path(slot=criteria.slot, version=1)),
        }
        for criteria in node.criteria
    ]


def stage_assignment_criteria_refs(
    session: AsyncSession,
    assignment: AssignmentModel,
) -> None:
    for index, criteria in enumerate(assignment.criteria_json, start=1):
        slot = str(criteria["slot"])
        session.add(
            AssignmentCriteriaRefModel(
                assignment_criteria_ref_id=assignment_criteria_ref_id(
                    assignment.assignment_id,
                    slot,
                ),
                assignment_id=assignment.assignment_id,
                slot=slot,
                logical_path=str(criteria["path"]),
                description=str(criteria["description"]),
                version=criteria.get("version"),
                order_index=index,
            )
        )


def build_launch_criteria_projection_signals(
    *,
    flow_revision_id: str,
    nodes: tuple[NormalizedCompiledNode, ...],
) -> tuple[CriteriaProjection, ...]:
    """Expose the exact initial criteria generations without writing support files."""

    signals: dict[tuple[str, str], CriteriaProjection] = {}
    for node in nodes:
        for criterion in node.criteria:
            key = (criterion.owner_node_key, criterion.slot)
            signals[key] = CriteriaProjection(
                flow_revision_id=flow_revision_id,
                owner_node_key=criterion.owner_node_key,
                slot=criterion.slot,
                version=1,
            )
    return tuple(signals.values())


__all__ = [
    "build_launch_criteria_projection_signals",
    "build_node_criteria_json",
    "stage_assignment_criteria_refs",
]
