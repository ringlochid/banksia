from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast

import pytest
from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    AssignmentCriteriaRefModel,
    AssignmentDecisionArtifactModel,
    AssignmentDecisionCheckpointModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    DispatchCapabilitySetModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.dispatch.authority import read_node_operation_authority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import NodeOperationScope
from autoclaw.runtime.node_operations.contracts import NodeOperationName, ReleaseRequest
from autoclaw.runtime.node_operations.structural_handlers import (
    execute_structural_node_operation,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import seeded_executor
from tests.helpers.lineage_seed import RuntimeIds


async def test_release_green_persists_current_child_checkpoint_and_keeps_d1_open(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="release-green") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await _stage_terminal_child_checkpoint(
                session,
                attempt_id=ids.child_attempt_id,
                checkpoint_id=ids.child_checkpoint_id,
                outcome="green",
            )
            root_assignment, child_assignment = await _read_release_assignments(session, ids)
            _stage_release_criteria(session, ids, root_assignment, child_assignment)
            root_assignment.produces_json = [{"slot": "root-output", "description": "Root output."}]
            child_assignment.produces_json = [
                {"slot": "child-output", "description": "Child output."}
            ]
            _stage_required_publication(
                session,
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                attempt_id=ids.root_attempt_id,
                checkpoint_id=ids.root_checkpoint_id,
                slot="root-output",
            )
            _stage_required_publication(
                session,
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.child_assignment_id,
                attempt_id=ids.child_attempt_id,
                checkpoint_id=ids.child_checkpoint_id,
                slot="child-output",
            )
            await session.commit()

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="release_green",
            arguments={"expected_structural_revision_id": ids.flow_revision_id},
        )

        async with session_factory() as session:
            decision = await session.scalar(
                select(AssignmentDecisionModel).where(
                    AssignmentDecisionModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            assert decision is not None
            evidence = await session.scalar(
                select(AssignmentDecisionCheckpointModel).where(
                    AssignmentDecisionCheckpointModel.assignment_decision_id
                    == decision.assignment_decision_id
                )
            )
            artifact_count = await session.scalar(
                select(func.count())
                .select_from(AssignmentDecisionArtifactModel)
                .where(
                    AssignmentDecisionArtifactModel.assignment_decision_id
                    == decision.assignment_decision_id
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        assert decision.decision_kind == "release_green"
        assert evidence is not None and evidence.checkpoint_id == ids.child_checkpoint_id
        assert artifact_count == 2
        assert dispatch is not None and dispatch.status == "open"


async def test_release_green_rejects_live_child_without_partial_decision(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="release-live") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="release_green",
                arguments={"expected_structural_revision_id": ids.flow_revision_id},
            )
        async with session_factory() as session:
            decision = await session.scalar(
                select(AssignmentDecisionModel).where(
                    AssignmentDecisionModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
        assert decision is None


async def test_release_green_rejects_missing_current_publication_without_partial_decision(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="release-publication") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await _terminalize_child(session, ids.child_attempt_id, outcome="green")
            child_checkpoint = await session.get(AttemptCheckpointModel, ids.child_checkpoint_id)
            child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
            assert child_checkpoint is not None and child_assignment is not None
            child_checkpoint.outcome = "green"
            child_assignment.produces_json = [
                {"slot": "required-output", "description": "Required output."}
            ]
            await session.commit()
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="release_green",
                arguments={"expected_structural_revision_id": ids.flow_revision_id},
            )
        async with session_factory() as session:
            decision = await session.scalar(
                select(AssignmentDecisionModel).where(
                    AssignmentDecisionModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
        assert decision is None


async def test_release_blocked_requires_root_checkpoint_and_terminal_descendants(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="release-blocked") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await _terminalize_child(session, ids.child_attempt_id, outcome="blocked")
            await session.commit()
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "terminal",
                    "outcome": "blocked",
                    "handoff": {
                        "summary": "The whole flow is blocked.",
                        "next_step": "Escalate the blocking condition.",
                    },
                }
            },
        )
        context = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )
        assert "release_blocked" in context.model_dump(mode="json")["allowed_actions"]

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="release_blocked",
            arguments={"expected_structural_revision_id": ids.flow_revision_id},
        )
        async with session_factory() as session:
            decision = await session.scalar(
                select(AssignmentDecisionModel).where(
                    AssignmentDecisionModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            assert decision is not None
            evidence_count = await session.scalar(
                select(func.count())
                .select_from(AssignmentDecisionCheckpointModel)
                .where(
                    AssignmentDecisionCheckpointModel.assignment_decision_id
                    == decision.assignment_decision_id
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        assert decision.decision_kind == "release_blocked"
        assert evidence_count == 2
        assert dispatch is not None and dispatch.status == "open"


async def test_release_write_rejects_stale_transaction_b(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="guard") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as setup_session:
            await _stage_terminal_child_checkpoint(
                setup_session,
                attempt_id=ids.child_attempt_id,
                checkpoint_id=ids.child_checkpoint_id,
                outcome="blocked",
            )
            await setup_session.commit()
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "terminal",
                    "outcome": "blocked",
                    "handoff": {
                        "summary": "The current flow cannot proceed.",
                        "next_step": "Repair the blocking condition.",
                    },
                }
            },
        )
        scope = NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id)
        async with session_factory() as stale_session:
            authority = await read_node_operation_authority(
                cast(AsyncSession, stale_session), scope
            )
            await stale_session.rollback()
            async with session_factory() as winner_session:
                flow = await winner_session.get(FlowModel, ids.flow_id)
                source = await winner_session.get(
                    DispatchTurnModel,
                    ids.current_dispatch_id,
                )
                assert flow is not None and source is not None
                successor_id = "dispatch.guard.root.3"
                now = utc_now()
                source.status = "closed"
                source.closed_at = now
                source.closed_reason = "watchdog_superseded"
                flow.current_dispatch_id = None
                await winner_session.flush()
                successor = _successor_dispatch(ids, successor_id, now)
                winner_session.add(successor)
                await winner_session.flush((successor,))
                _stage_dispatch_support(winner_session, successor_id, now)
                flow.current_dispatch_id = successor_id
                await winner_session.commit()
            with pytest.raises(RuntimeOperationError) as stale:
                await execute_structural_node_operation(
                    cast(AsyncSession, stale_session),
                    authority,
                    NodeOperationName.RELEASE_BLOCKED,
                    ReleaseRequest(
                        expected_structural_revision_id=ids.flow_revision_id,
                    ),
                )

        assert stale.value.code.value == "conflict"
        async with session_factory() as read_session:
            decision = await read_session.scalar(
                select(AssignmentDecisionModel).where(
                    AssignmentDecisionModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
        assert decision is None


async def _stage_terminal_child_checkpoint(
    session: object,
    *,
    attempt_id: str,
    checkpoint_id: str,
    outcome: str,
) -> None:
    await _terminalize_child(session, attempt_id, outcome=outcome)
    typed_session = cast(AsyncSession, session)
    checkpoint = await typed_session.get(AttemptCheckpointModel, checkpoint_id)
    assert checkpoint is not None
    checkpoint.outcome = outcome


async def _read_release_assignments(
    session: object,
    ids: RuntimeIds,
) -> tuple[AssignmentModel, AssignmentModel]:
    typed_session = cast(AsyncSession, session)
    root_assignment = await typed_session.get(AssignmentModel, ids.root_assignment_id)
    child_assignment = await typed_session.get(AssignmentModel, ids.child_assignment_id)
    assert root_assignment is not None and child_assignment is not None
    return root_assignment, child_assignment


def _stage_release_criteria(
    session: object,
    ids: RuntimeIds,
    root_assignment: AssignmentModel,
    child_assignment: AssignmentModel,
) -> None:
    root_assignment.criteria_json = [
        {
            "slot": "criteria",
            "path": "_runtime/criteria/root.md",
            "description": "Root criteria.",
            "version": 1,
        }
    ]
    child_assignment.criteria_json = [
        {
            "slot": "child-criteria",
            "path": "_runtime/criteria/child.md",
            "description": "Child criteria.",
            "version": 1,
        }
    ]
    cast(AsyncSession, session).add(
        AssignmentCriteriaRefModel(
            assignment_criteria_ref_id="criteria-ref.release-green.child.0",
            assignment_id=ids.child_assignment_id,
            slot="child-criteria",
            logical_path="_runtime/criteria/child.md",
            description="Child criteria.",
            version=1,
            order_index=0,
        )
    )


def _successor_dispatch(
    ids: RuntimeIds,
    successor_id: str,
    now: datetime,
) -> DispatchTurnModel:
    return DispatchTurnModel(
        dispatch_id=successor_id,
        task_id=ids.task_id,
        flow_id=ids.flow_id,
        assignment_id=ids.root_assignment_id,
        attempt_id=ids.root_attempt_id,
        node_key="root",
        flow_start_source_flow_id=None,
        predecessor_dispatch_id=ids.current_dispatch_id,
        status="open",
        opened_reason="watchdog_recovery",
        requested_provider="codex",
        resolved_provider="codex",
        provider_selection_basis="default",
        provider_route_kind="codex",
        model_override=None,
        effort_override=None,
        gateway_profile=None,
        provider_start_revision=0,
        provider_start_attempt_count=0,
        next_provider_start_at=None,
        provider_start_retry_kind=None,
        provider_start_last_error_code=None,
        created_at=now,
        adapter_started_at=now,
        last_node_activity_at=now,
        node_activity_revision=0,
        closed_at=None,
        closed_reason=None,
    )


def _stage_dispatch_support(
    session: object,
    successor_id: str,
    now: datetime,
) -> None:
    typed_session = cast(AsyncSession, session)
    typed_session.add(
        DispatchPromptRefsModel(
            dispatch_id=successor_id,
            instructions_logical_path=f"_runtime/dispatch/{successor_id}/instructions.md",
            input_logical_path=f"_runtime/dispatch/{successor_id}/input.md",
            dynamic_input_version=1,
            created_at=now,
        )
    )
    typed_session.add(
        DispatchCapabilitySetModel(
            dispatch_id=successor_id,
            provider_native_access="full",
            provider_native_access_source="default",
            network_access="allow",
            network_access_source="default",
            human_direction="allow",
            human_approval="allow",
            human_input="allow",
            human_review="allow",
            command_run="allow",
            created_at=now,
        )
    )


async def _terminalize_child(
    session: object,
    attempt_id: str,
    *,
    outcome: str,
) -> None:
    typed_session = cast(AsyncSession, session)
    attempt = await typed_session.get(AttemptModel, attempt_id)
    assert attempt is not None
    attempt.status = "completed"
    attempt.terminal_outcome = outcome
    attempt.closed_at = utc_now()


def _stage_required_publication(
    session: object,
    *,
    task_id: str,
    flow_id: str,
    assignment_id: str,
    attempt_id: str,
    checkpoint_id: str,
    slot: str,
) -> None:
    typed_session = cast(AsyncSession, session)
    publication_id = f"artifact-publication.{assignment_id}.{slot}.1"
    typed_session.add(
        ArtifactPublicationModel(
            artifact_publication_id=publication_id,
            task_id=task_id,
            flow_id=flow_id,
            assignment_id=assignment_id,
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
            slot=slot,
            version=1,
            logical_path=f"outputs/artifacts/{slot}.txt",
            description=f"Published {slot}.",
            supersedes_publication_id=None,
            supersedes_version=None,
        )
    )
    typed_session.add(
        ArtifactCurrentPointerModel(
            artifact_current_pointer_id=f"artifact-current-pointer.{assignment_id}.{slot}",
            task_id=task_id,
            flow_id=flow_id,
            assignment_id=assignment_id,
            slot=slot,
            current_publication_id=publication_id,
            current_version=1,
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
        )
    )
