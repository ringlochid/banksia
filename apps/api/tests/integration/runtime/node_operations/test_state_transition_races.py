from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    AssignmentCriteriaRefModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    CommandRunModel,
    DispatchTurnModel,
    FlowNodeModel,
    FlowWaitModel,
    HumanRequestModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import read_node_operation_authority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import NodeOperationScope
from autoclaw.runtime.node_operations.catalog import get_node_operation_descriptor
from autoclaw.runtime.node_operations.contracts import NodeOperationName
from autoclaw.runtime.node_operations.domain_handlers import execute_controller_node_operation
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    seeded_executor,
    synchronized_transition_claims,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_concurrent_terminal_checkpoints_have_one_stable_loser(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="terminal-race") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="record_checkpoint",
                        arguments=_terminal_checkpoint("blocked"),
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name="record_checkpoint",
                        arguments=_terminal_checkpoint("green"),
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        error = _one_runtime_error(results)
        assert error.code == OperationFailureCode.CONFLICT
        async with session_factory() as session:
            checkpoints = tuple(
                await session.scalars(
                    select(AttemptCheckpointModel).where(
                        AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id
                    )
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert len(checkpoints) == 1
        assert checkpoints[0].outcome in {"blocked", "green"}
        assert dispatch is not None and dispatch.node_activity_revision == 2
        assert [signal.activity_revision for signal in signals] == [1, 2]


async def test_terminal_checkpoint_constraint_maps_a_stale_handler_to_conflict(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="terminal-constraint") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        async with session_factory() as session:
            stale_authority = await read_node_operation_authority(
                cast(AsyncSession, session),
                scope,
            )

        await executor.execute(
            scope=scope,
            operation_name="record_checkpoint",
            arguments=_terminal_checkpoint("blocked"),
        )
        request = get_node_operation_descriptor(
            NodeOperationName.RECORD_CHECKPOINT
        ).request_model.model_validate(_terminal_checkpoint("green"))
        with pytest.raises(RuntimeOperationError) as error:
            async with session_factory() as session:
                await execute_controller_node_operation(
                    cast(AsyncSession, session),
                    stale_authority,
                    NodeOperationName.RECORD_CHECKPOINT,
                    request,
                )

        assert error.value.code == OperationFailureCode.CONFLICT
        async with session_factory() as session:
            checkpoint_count = await session.scalar(
                select(func.count())
                .select_from(AttemptCheckpointModel)
                .where(AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id)
            )
        assert checkpoint_count == 1


async def test_terminal_checkpoint_and_human_wait_have_one_winner(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="terminal-human-race") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="record_checkpoint",
                        arguments=_terminal_checkpoint("blocked"),
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name="open_human_request",
                        arguments={
                            "request": {
                                "kind": "direction",
                                "summary": "Choose one bounded direction.",
                                "items": [
                                    {
                                        "id": "direction",
                                        "prompt": "Which direction?",
                                        "options": [{"id": "a", "title": "A"}],
                                    }
                                ],
                            }
                        },
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        error = _one_runtime_error(results)
        assert error.code == OperationFailureCode.CONFLICT
        async with session_factory() as session:
            checkpoint_count = await session.scalar(
                select(func.count())
                .select_from(AttemptCheckpointModel)
                .where(AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id)
            )
            request_count = await session.scalar(
                select(func.count()).select_from(HumanRequestModel)
            )
            wait_count = await session.scalar(select(func.count()).select_from(FlowWaitModel))
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert (int(checkpoint_count or 0), int(request_count or 0)) in {(1, 0), (0, 1)}
        assert int(wait_count or 0) == int(request_count or 0)
        assert dispatch is not None
        assert dispatch.status == ("open" if checkpoint_count else "closed")
        assert dispatch.node_activity_revision == 2
        assert [signal.activity_revision for signal in signals] == [1, 2]


@pytest.mark.parametrize(
    ("wait_operation", "wait_arguments"),
    (
        (
            "open_human_request",
            {
                "request": {
                    "kind": "direction",
                    "summary": "Choose one bounded direction.",
                    "items": [
                        {
                            "id": "direction",
                            "prompt": "Which direction?",
                            "options": [{"id": "a", "title": "A"}],
                        }
                    ],
                }
            },
        ),
        (
            "start_command_run",
            {
                "request": {
                    "command": {"kind": "argv", "argv": ["printf", "ready"]},
                    "summary": "Produce one bounded output.",
                }
            },
        ),
    ),
)
async def test_assign_child_and_external_wait_have_one_stable_winner(
    tmp_path: Path,
    wait_operation: str,
    wait_arguments: dict[str, object],
) -> None:
    async with seeded_executor(tmp_path, suffix=f"assign-{wait_operation}") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        async with session_factory() as session:
            child = await session.get(FlowNodeModel, ids.child_node_id)
            assert child is not None
            child.current_assignment_id = None
            child.state = "ready"
            await session.commit()

        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="assign_child",
                        arguments={
                            "expected_structural_revision_id": ids.flow_revision_id,
                            "payload": {
                                "child_node_key": "child",
                                "assignment_intent": {"summary": "Do bounded child work."},
                            },
                        },
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name=wait_operation,
                        arguments=wait_arguments,
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        error = _one_runtime_error(results)
        assert error.code == OperationFailureCode.CONFLICT
        async with session_factory() as session:
            decision_count = await session.scalar(
                select(func.count()).select_from(AssignmentDecisionModel)
            )
            human_request_count = await session.scalar(
                select(func.count()).select_from(HumanRequestModel)
            )
            command_run_count = await session.scalar(
                select(func.count()).select_from(CommandRunModel)
            )
            wait_count = await session.scalar(select(func.count()).select_from(FlowWaitModel))
            child = await session.get(FlowNodeModel, ids.child_node_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        source_count = int(human_request_count or 0) + int(command_run_count or 0)
        assert (int(decision_count or 0), source_count) in {(1, 0), (0, 1)}
        assert int(wait_count or 0) == source_count
        assert child is not None and dispatch is not None
        if decision_count:
            assert child.current_assignment_id is not None
            assert dispatch.status == "open"
        else:
            assert child.current_assignment_id is None
            assert dispatch.status == "closed"
        assert dispatch.node_activity_revision == 2
        assert [signal.activity_revision for signal in signals] == [1, 2]


async def test_release_green_and_human_wait_have_one_winner(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="release-human-race") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        async with session_factory() as session:
            await _stage_release_green_race_basis(session, ids)

        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="release_green",
                        arguments={"expected_structural_revision_id": ids.flow_revision_id},
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name="open_human_request",
                        arguments={
                            "request": {
                                "kind": "direction",
                                "summary": "Choose one direction.",
                                "items": [
                                    {
                                        "id": "direction",
                                        "prompt": "Which direction?",
                                        "options": [{"id": "a", "title": "A"}],
                                    }
                                ],
                            }
                        },
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        errors = [result for result in results if isinstance(result, BaseException)]
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeOperationError)
        assert errors[0].code.value == "conflict"
        async with session_factory() as session:
            decision_count = await session.scalar(
                select(func.count()).select_from(AssignmentDecisionModel)
            )
            request_count = await session.scalar(
                select(func.count()).select_from(HumanRequestModel)
            )
            wait_count = await session.scalar(select(func.count()).select_from(FlowWaitModel))
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        assert (int(decision_count or 0), int(request_count or 0)) in {(1, 0), (0, 1)}
        assert int(wait_count or 0) == int(request_count or 0)
        assert dispatch is not None
        assert dispatch.status == ("open" if decision_count else "closed")
        assert dispatch.node_activity_revision == 2
        assert [signal.activity_revision for signal in signals] == [1, 2]


async def _stage_release_green_race_basis(
    session: object,
    ids: RuntimeIds,
) -> None:
    typed_session = cast(AsyncSession, session)
    child_attempt = await typed_session.get(AttemptModel, ids.child_attempt_id)
    child_checkpoint = await typed_session.get(
        AttemptCheckpointModel,
        ids.child_checkpoint_id,
    )
    root_assignment = await typed_session.get(AssignmentModel, ids.root_assignment_id)
    child_assignment = await typed_session.get(AssignmentModel, ids.child_assignment_id)
    assert child_attempt is not None and child_checkpoint is not None
    assert root_assignment is not None and child_assignment is not None

    child_attempt.status = "completed"
    child_attempt.terminal_outcome = "green"
    child_attempt.closed_at = utc_now()
    child_checkpoint.outcome = "green"
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
    root_assignment.produces_json = [{"slot": "root-output", "description": "Output."}]
    child_assignment.produces_json = [{"slot": "child-output", "description": "Output."}]
    typed_session.add(
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
    _stage_release_race_publication(
        typed_session,
        ids=ids,
        assignment_id=ids.root_assignment_id,
        attempt_id=ids.root_attempt_id,
        checkpoint_id=ids.root_checkpoint_id,
        slot="root-output",
    )
    _stage_release_race_publication(
        typed_session,
        ids=ids,
        assignment_id=ids.child_assignment_id,
        attempt_id=ids.child_attempt_id,
        checkpoint_id=ids.child_checkpoint_id,
        slot="child-output",
    )
    await typed_session.commit()


def _stage_release_race_publication(
    session: AsyncSession,
    *,
    ids: RuntimeIds,
    assignment_id: str,
    attempt_id: str,
    checkpoint_id: str,
    slot: str,
) -> None:
    publication_id = f"artifact-publication.{assignment_id}.{slot}.1"
    session.add(
        ArtifactPublicationModel(
            artifact_publication_id=publication_id,
            task_id=ids.task_id,
            flow_id=ids.flow_id,
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
    session.add(
        ArtifactCurrentPointerModel(
            artifact_current_pointer_id=f"artifact-current-pointer.{assignment_id}.{slot}",
            task_id=ids.task_id,
            flow_id=ids.flow_id,
            assignment_id=assignment_id,
            slot=slot,
            current_publication_id=publication_id,
            current_version=1,
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
        )
    )


def _terminal_checkpoint(outcome: str) -> dict[str, object]:
    return {
        "checkpoint": {
            "checkpoint_kind": "terminal",
            "outcome": outcome,
            "handoff": {
                "summary": f"The current assignment reached {outcome}.",
                "next_step": f"Return the matching {outcome} boundary.",
            },
        }
    }


def _one_runtime_error(results: Sequence[object]) -> RuntimeOperationError:
    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeOperationError)
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    return errors[0]
