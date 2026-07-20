from __future__ import annotations

from pathlib import Path

from autoclaw.persistence.models import FlowModel, FlowNodeModel
from autoclaw.runtime.projection.signals import (
    CriteriaProjection,
    SupportProjectionSignal,
    WorkflowManifestProjection,
)
from sqlalchemy import select
from tests.integration.runtime.node_operations.structural_revision_fixture import (
    StructuralRevisionContext,
    seeded_structural_revision_context,
)


class _CapturedProjectionPublisher:
    def __init__(self) -> None:
        self.signals: list[SupportProjectionSignal] = []

    def publish(self, signal: SupportProjectionSignal) -> bool:
        self.signals.append(signal)
        return True


class _RaisingProjectionPublisher:
    def __init__(self) -> None:
        self.signals: list[SupportProjectionSignal] = []

    def publish(self, signal: SupportProjectionSignal) -> bool:
        self.signals.append(signal)
        raise RuntimeError("projection queue unavailable")


async def test_structural_commits_publish_manifest_and_every_criteria_generation(
    tmp_path: Path,
) -> None:
    publisher = _CapturedProjectionPublisher()
    async with seeded_structural_revision_context(
        tmp_path,
        suffix="structural-follow-on",
        support_projection_publisher=publisher,
    ) as context:
        response = await context.executor.execute(
            scope=context.scope,
            operation_name="add_child",
            arguments={
                "expected_structural_revision_id": context.ids.flow_revision_id,
                "payload": {
                    "target_parent_node_key": "branch",
                    "child": {
                        "node_key": "qa_follow_on",
                        "role": "role.target",
                        "policy": "policy.target",
                        "description": "QA worker.",
                        "criteria": [
                            {
                                "slot": "qa_gate",
                                "description": "QA gate.",
                                "criteria": ["The result is verified."],
                            }
                        ],
                    },
                },
            },
        )
        added_revision_id = response.model_dump()["flow"]["active_flow_revision_id"]
        assert publisher.signals == list(
            await _expected_projection_signals(context, added_revision_id)
        )

        publisher.signals.clear()
        response = await context.executor.execute(
            scope=context.scope,
            operation_name="update_child",
            arguments={
                "expected_structural_revision_id": added_revision_id,
                "payload": {
                    "child_node_key": "qa_follow_on",
                    "patch": {
                        "criteria": [
                            {
                                "slot": "qa_gate",
                                "description": "Updated QA gate.",
                                "criteria": ["The updated result is verified."],
                            }
                        ]
                    },
                },
            },
        )
        updated_revision_id = response.model_dump()["flow"]["active_flow_revision_id"]
        assert publisher.signals == list(
            await _expected_projection_signals(context, updated_revision_id)
        )

        publisher.signals.clear()
        response = await context.executor.execute(
            scope=context.scope,
            operation_name="remove_child",
            arguments={
                "expected_structural_revision_id": updated_revision_id,
                "payload": {"child_node_key": "qa_follow_on"},
            },
        )
        removed_revision_id = response.model_dump()["flow"]["active_flow_revision_id"]
        assert publisher.signals == list(
            await _expected_projection_signals(context, removed_revision_id)
        )


async def test_structural_commit_survives_projection_publication_failure(
    tmp_path: Path,
) -> None:
    publisher = _RaisingProjectionPublisher()
    async with seeded_structural_revision_context(
        tmp_path,
        suffix="manifest-publish-failure",
        support_projection_publisher=publisher,
    ) as context:
        response = await context.executor.execute(
            scope=context.scope,
            operation_name="add_child",
            arguments={
                "expected_structural_revision_id": context.ids.flow_revision_id,
                "payload": {
                    "target_parent_node_key": "branch",
                    "child": {
                        "node_key": "publication_failure_child",
                        "role": "role.target",
                        "policy": "policy.target",
                        "description": "Committed despite projection failure.",
                    },
                },
            },
        )
        revision_id = response.model_dump()["flow"]["active_flow_revision_id"]
        async with context.session_factory() as session:
            flow = await session.get(FlowModel, context.ids.flow_id)

    assert flow is not None and flow.active_flow_revision_id == revision_id
    assert publisher.signals[0] == WorkflowManifestProjection(
        context.ids.flow_id,
        revision_id,
    )


async def _expected_projection_signals(
    context: StructuralRevisionContext,
    flow_revision_id: str,
) -> tuple[SupportProjectionSignal, ...]:
    async with context.session_factory() as session:
        nodes = tuple(
            await session.scalars(
                select(FlowNodeModel)
                .where(FlowNodeModel.flow_revision_id == flow_revision_id)
                .order_by(FlowNodeModel.order_index)
            )
        )
    criteria_signals: dict[tuple[str, str, int], CriteriaProjection] = {}
    for node in nodes:
        for criterion in node.criteria_json:
            owner_node_key = str(criterion["owner_node_key"])
            slot = str(criterion["slot"])
            version = int(criterion["version"])
            key = (owner_node_key, slot, version)
            criteria_signals[key] = CriteriaProjection(
                flow_revision_id=flow_revision_id,
                owner_node_key=owner_node_key,
                slot=slot,
                version=version,
            )
    return (
        WorkflowManifestProjection(context.ids.flow_id, flow_revision_id),
        *criteria_signals.values(),
    )
