from __future__ import annotations

from pathlib import Path

import autoclaw.runtime.node_operations.structural_handlers as structural_handlers
import pytest
from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    FlowEdgeModel,
    FlowNodeModel,
    PolicyRevisionModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import NodeOperationScope
from autoclaw.runtime.projection.signals import (
    AttemptAssignmentProjection,
    SupportProjectionSignal,
)
from sqlalchemy import func, select
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


class _CapturedProjectionPublisher:
    def __init__(self) -> None:
        self.signals: list[SupportProjectionSignal] = []

    def publish(self, signal: SupportProjectionSignal) -> bool:
        self.signals.append(signal)
        return True


async def test_assign_child_consumes_budget_once_and_publishes_exact_attempt(
    tmp_path: Path,
) -> None:
    publisher = _CapturedProjectionPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="child-budget-success",
        support_projection_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        await _prepare_assignable_child(session_factory, ids, remaining=1)

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments=_assign_child_arguments(ids.flow_revision_id),
        )
        assignment_key = response.model_dump()["target_assignment_key"]
        attempt_id = response.model_dump()["target_attempt_id"]
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            assignment = await session.scalar(
                select(AssignmentModel).where(AssignmentModel.assignment_key == assignment_key)
            )
        assert parent is not None and parent.child_assignments_remaining == 0
        assert assignment is not None
        assert publisher.signals == [
            AttemptAssignmentProjection(
                assignment.assignment_id,
                attempt_id,
                ids.flow_revision_id,
            )
        ]

        with pytest.raises(RuntimeOperationError) as duplicate:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments=_assign_child_arguments(ids.flow_revision_id),
            )
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
        assert duplicate.value.code == OperationFailureCode.ILLEGAL_STATE
        assert parent is not None and parent.child_assignments_remaining == 0
        assert len(publisher.signals) == 1


async def test_assign_child_pins_current_artifact_consume_ref(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="child-artifact-input") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        await _prepare_assignable_child(session_factory, ids, remaining=1)
        await _set_child_artifact_selector(
            session_factory,
            ids,
            is_required=True,
        )
        await _publish_root_input(session_factory, ids)

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments=_assign_child_arguments(ids.flow_revision_id),
        )

        async with session_factory() as session:
            assignment = await session.scalar(
                select(AssignmentModel).where(
                    AssignmentModel.assignment_key == response.model_dump()["target_assignment_key"]
                )
            )

    assert assignment is not None
    assert assignment.consumes_json == [
        {
            "kind": "artifact",
            "slot": "input",
            "version": 1,
            "path": "outputs/artifacts/root/input/input.v01.md",
            "description": "Root output consumed by child.",
        }
    ]


async def test_assign_child_omits_missing_optional_artifact_consume(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="child-optional-input") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        await _prepare_assignable_child(session_factory, ids, remaining=1)
        await _set_child_artifact_selector(
            session_factory,
            ids,
            is_required=False,
        )

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments=_assign_child_arguments(ids.flow_revision_id),
        )

        async with session_factory() as session:
            assignment = await session.scalar(
                select(AssignmentModel).where(
                    AssignmentModel.assignment_key == response.model_dump()["target_assignment_key"]
                )
            )

    assert assignment is not None and assignment.consumes_json == []


async def test_assign_child_missing_required_artifact_commits_nothing(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="child-required-input") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        assignment_count = await _prepare_assignable_child(
            session_factory,
            ids,
            remaining=1,
        )
        await _set_child_artifact_selector(
            session_factory,
            ids,
            is_required=True,
        )

        with pytest.raises(RuntimeOperationError) as missing:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments=_assign_child_arguments(ids.flow_revision_id),
            )

        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            final_assignment_count = await session.scalar(
                select(func.count()).select_from(AssignmentModel)
            )
            decision = await session.scalar(select(AssignmentDecisionModel))

    assert missing.value.code == OperationFailureCode.MISSING_REQUIRED_PUBLICATION
    assert parent is not None and parent.child_assignments_remaining == 1
    assert child is not None and child.current_assignment_id is None
    assert final_assignment_count == assignment_count
    assert decision is None


async def test_assign_child_zero_budget_commits_nothing(tmp_path: Path) -> None:
    publisher = _CapturedProjectionPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="child-budget-zero",
        support_projection_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        assignment_count = await _prepare_assignable_child(
            session_factory,
            ids,
            remaining=0,
        )

        with pytest.raises(RuntimeOperationError) as exhausted:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments=_assign_child_arguments(ids.flow_revision_id),
            )
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            final_assignment_count = await session.scalar(
                select(func.count()).select_from(AssignmentModel)
            )
            decision = await session.scalar(select(AssignmentDecisionModel))
        assert exhausted.value.code == OperationFailureCode.BUDGET_EXHAUSTED
        assert parent is not None and parent.child_assignments_remaining == 0
        assert child is not None and child.current_assignment_id is None
        assert final_assignment_count == assignment_count
        assert decision is None
        assert publisher.signals == []


async def test_assign_child_loser_rolls_back_budget_decrement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _CapturedProjectionPublisher()

    async def lose_child_claim(*_args: object, **_kwargs: object) -> None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another child assignment won the target node",
            is_retryable=False,
        )

    monkeypatch.setattr(structural_handlers, "_claim_child_node", lose_child_claim)
    async with seeded_executor(
        tmp_path,
        suffix="child-budget-rollback",
        support_projection_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        assignment_count = await _prepare_assignable_child(
            session_factory,
            ids,
            remaining=1,
        )

        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments=_assign_child_arguments(ids.flow_revision_id),
            )
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            final_assignment_count = await session.scalar(
                select(func.count()).select_from(AssignmentModel)
            )
            decision = await session.scalar(select(AssignmentDecisionModel))
        assert parent is not None and parent.child_assignments_remaining == 1
        assert child is not None and child.current_assignment_id is None
        assert final_assignment_count == assignment_count
        assert decision is None
        assert publisher.signals == []


async def test_assign_child_supersedes_terminal_child_with_fresh_assignment(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="child-fresh-assignment") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            previous = await session.get(AssignmentModel, ids.child_assignment_id)
            previous_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            previous_checkpoint = await session.get(
                AttemptCheckpointModel,
                ids.child_checkpoint_id,
            )
            policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
            assert parent is not None
            assert child is not None
            assert previous is not None
            assert previous_attempt is not None
            assert previous_checkpoint is not None
            assert policy is not None
            historical_parent_id = f"assignment.{ids.suffix}.root.previous"
            session.add(
                AssignmentModel(
                    assignment_id=historical_parent_id,
                    task_id=ids.task_id,
                    flow_id=ids.flow_id,
                    flow_revision_id=ids.flow_revision_id,
                    flow_node_id=ids.root_node_id,
                    assignment_key=f"assignment-key.{ids.suffix}.root.previous",
                    node_key="root",
                    parent_assignment_id=None,
                    summary="Previous root assignment.",
                    instruction=None,
                    criteria_json=[],
                    consumes_json=[],
                    produces_json=[],
                    current_attempt_id=None,
                    work_plan_revision=0,
                    superseded_at=utc_now(),
                )
            )
            parent.child_assignment_limit = 2
            parent.child_assignments_remaining = 2
            child.state = "done"
            previous.parent_assignment_id = historical_parent_id
            previous_attempt.status = "completed"
            previous_attempt.terminal_outcome = "green"
            previous_attempt.closed_at = utc_now()
            previous_attempt.latest_checkpoint_id = previous_checkpoint.checkpoint_id
            previous_checkpoint.outcome = "green"
            policy.content_json = {
                "id": "policy.target",
                "description": "Target child policy.",
                "applies_to": ["root", "parent", "worker"],
            }
            await session.commit()

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments=_assign_child_arguments(ids.flow_revision_id),
        )

        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            previous = await session.get(AssignmentModel, ids.child_assignment_id)
            current = await session.scalar(
                select(AssignmentModel).where(
                    AssignmentModel.assignment_key == response.model_dump()["target_assignment_key"]
                )
            )
            current_attempt = (
                await session.get(AttemptModel, current.current_attempt_id)
                if current is not None and current.current_attempt_id is not None
                else None
            )

        assert parent is not None and parent.child_assignments_remaining == 1
        assert previous is not None and previous.superseded_at is not None
        assert current is not None and current.superseded_at is None
        assert child is not None and child.current_assignment_id == current.assignment_id
        assert child.state == "waiting"
        assert current_attempt is not None and current_attempt.status == "pending"


async def test_assign_child_rejects_replacing_an_assigned_artifact_provider(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="child-assigned-consumer") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        reviewer_node_id = f"flow-node.{ids.suffix}.reviewer"
        reviewer_assignment_id = f"assignment.{ids.suffix}.reviewer"
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            previous = await session.get(AssignmentModel, ids.child_assignment_id)
            previous_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            previous_checkpoint = await session.get(
                AttemptCheckpointModel,
                ids.child_checkpoint_id,
            )
            policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
            assert parent is not None and child is not None and previous is not None
            assert previous_attempt is not None and previous_checkpoint is not None
            assert policy is not None
            parent.child_assignment_limit = 2
            parent.child_assignments_remaining = 2
            child.state = "done"
            previous_attempt.status = "completed"
            previous_attempt.terminal_outcome = "green"
            previous_attempt.closed_at = utc_now()
            previous_attempt.latest_checkpoint_id = previous_checkpoint.checkpoint_id
            previous_checkpoint.outcome = "green"
            policy.content_json = {
                "id": "policy.target",
                "description": "Target child policy.",
                "applies_to": ["root", "parent", "worker"],
            }
            reviewer = FlowNodeModel(
                flow_node_id=reviewer_node_id,
                flow_id=ids.flow_id,
                flow_revision_id=ids.flow_revision_id,
                node_key="reviewer",
                parent_node_key="root",
                structural_kind="worker",
                role_key=child.role_key,
                role_revision_no=child.role_revision_no,
                role_description=child.role_description,
                role_instruction=child.role_instruction,
                policy_key=child.policy_key,
                policy_revision_no=child.policy_revision_no,
                policy_description=child.policy_description,
                policy_instruction=child.policy_instruction,
                provider_kind=child.provider_kind,
                description="Review the child output.",
                node_instruction=None,
                child_node_keys_json=[],
                consumes_json={"artifacts": [{"slot": "result", "required": True}]},
                produces_json=None,
                criteria_json=[],
                child_defaults_json=None,
                state="waiting",
                current_assignment_id=reviewer_assignment_id,
                order_index=2,
            )
            reviewer_assignment = AssignmentModel(
                assignment_id=reviewer_assignment_id,
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                flow_revision_id=ids.flow_revision_id,
                flow_node_id=reviewer_node_id,
                assignment_key=f"assignment-key.{ids.suffix}.reviewer",
                node_key="reviewer",
                parent_assignment_id=ids.root_assignment_id,
                summary="Review the child output.",
                instruction=None,
                criteria_json=[],
                consumes_json=[],
                produces_json=[],
                current_attempt_id=None,
                work_plan_revision=0,
            )
            edge = FlowEdgeModel(
                flow_edge_id=f"flow-edge.{ids.suffix}.child-reviewer",
                flow_revision_id=ids.flow_revision_id,
                provider_node_key="child",
                consumer_node_key="reviewer",
                kind="artifact",
                slot="result",
                description="Child result consumed by reviewer.",
                order_index=1,
            )
            session.add_all((reviewer, reviewer_assignment, edge))
            await session.commit()

        with pytest.raises(RuntimeOperationError) as stale_consumer:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments=_assign_child_arguments(ids.flow_revision_id),
            )

        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            previous = await session.get(AssignmentModel, ids.child_assignment_id)
        assert stale_consumer.value.code == OperationFailureCode.CONFLICT
        assert "downstream artifact consumer" in stale_consumer.value.summary
        assert parent is not None and parent.child_assignments_remaining == 2
        assert child is not None and child.current_assignment_id == ids.child_assignment_id
        assert previous is not None and previous.superseded_at is None


async def test_staged_child_allows_progress_but_rejects_terminal_checkpoint(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="child-staged-checkpoint") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        await _prepare_assignable_child(session_factory, ids, remaining=1)
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments=_assign_child_arguments(ids.flow_revision_id),
        )
        progress = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "progress",
                    "handoff": {
                        "summary": "The child assignment is staged.",
                        "next_step": "Return yield.",
                    },
                }
            },
        )

        with pytest.raises(RuntimeOperationError) as terminal:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="record_checkpoint",
                arguments={
                    "checkpoint": {
                        "checkpoint_kind": "terminal",
                        "outcome": "green",
                        "handoff": {
                            "summary": "This dispatch has staged a child.",
                            "next_step": "Return yield instead of terminal closure.",
                        },
                    }
                },
            )

        async with session_factory() as session:
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
        assert terminal.value.code == OperationFailureCode.ILLEGAL_STATE
        assert attempt is not None
        assert attempt.latest_checkpoint_id == progress.model_dump()["checkpoint_id"]


async def _prepare_assignable_child(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    remaining: int,
) -> int:
    async with session_factory() as session:
        parent = await session.get(AssignmentModel, ids.root_assignment_id)
        child = await session.get(FlowNodeModel, ids.child_node_id)
        policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
        assert parent is not None and child is not None and policy is not None
        parent.child_assignment_limit = remaining
        parent.child_assignments_remaining = remaining
        child.current_assignment_id = None
        child.state = "ready"
        policy.content_json = {
            "id": "policy.target",
            "description": "Target child policy.",
            "applies_to": ["root", "parent", "worker"],
        }
        assignment_count = await session.scalar(select(func.count()).select_from(AssignmentModel))
        await session.commit()
    return int(assignment_count or 0)


async def _set_child_artifact_selector(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    is_required: bool,
) -> None:
    async with session_factory() as session:
        child = await session.get(FlowNodeModel, ids.child_node_id)
        assert child is not None
        child.consumes_json = {
            "artifacts": [{"slot": "input", "required": is_required}],
            "criteria": [],
        }
        await session.commit()


async def _publish_root_input(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> None:
    publication_id = f"artifact-publication.{ids.suffix}.root.input.1"
    async with session_factory() as session:
        session.add(
            ArtifactPublicationModel(
                artifact_publication_id=publication_id,
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                attempt_id=ids.root_attempt_id,
                checkpoint_id=ids.root_checkpoint_id,
                slot="input",
                version=1,
                logical_path="outputs/artifacts/root/input/input.v01.md",
                description="Root output consumed by child.",
                supersedes_publication_id=None,
                supersedes_version=None,
            )
        )
        session.add(
            ArtifactCurrentPointerModel(
                artifact_current_pointer_id=(f"artifact-current-pointer.{ids.suffix}.root.input"),
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                slot="input",
                current_publication_id=publication_id,
                current_version=1,
                attempt_id=ids.root_attempt_id,
                checkpoint_id=ids.root_checkpoint_id,
            )
        )
        await session.commit()


def _assign_child_arguments(flow_revision_id: str) -> dict[str, object]:
    return {
        "expected_structural_revision_id": flow_revision_id,
        "payload": {
            "child_node_key": "child",
            "assignment_intent": {"summary": "Do bounded child work."},
        },
    }
