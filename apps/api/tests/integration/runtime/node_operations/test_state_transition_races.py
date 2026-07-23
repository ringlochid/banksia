from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AttemptCheckpointModel,
    CommandRunModel,
    DispatchTurnModel,
    FlowNodeModel,
    FlowWaitModel,
    HumanRequestModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import read_node_operation_authority
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.node_operations.catalog import get_node_operation_descriptor
from banksia.runtime.node_operations.contracts import NodeOperationName
from banksia.runtime.node_operations.domain_handlers import (
    execute_controller_node_operation,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    seeded_executor,
    synchronized_transition_claims,
)

_HUMAN_REQUEST_ARGUMENTS: dict[str, object] = {
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
}


async def test_concurrent_terminal_checkpoints_have_one_stable_winner(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="terminal-race") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        scope = _scope(ids.task_id, ids.current_dispatch_id)
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="checkpoint",
                        arguments=_terminal_checkpoint("blocked"),
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name="checkpoint",
                        arguments=_terminal_checkpoint("retry"),
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        error = _one_runtime_error(results)
        assert error.code in {
            OperationFailureCode.CONFLICT,
            OperationFailureCode.STALE_DISPATCH,
        }
        async with session_factory() as session:
            checkpoints = tuple(
                await session.scalars(
                    select(AttemptCheckpointModel).where(
                        AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id
                    )
                )
            )
            boundaries = tuple(
                await session.scalars(
                    select(AcceptedBoundaryModel).where(
                        AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                    )
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert len(checkpoints) == len(boundaries) == 1
        assert checkpoints[0].outcome in {"blocked", "retry"}
        assert boundaries[0].checkpoint_id == checkpoints[0].checkpoint_id
        assert dispatch is not None and dispatch.status == "closed"
        assert dispatch.node_activity_revision == 2
        assert [signal.activity_revision for signal in signals] == [1, 2]


async def test_closed_dispatch_authority_maps_exact_transition_to_conflict(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="terminal-constraint") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        scope = _scope(ids.task_id, ids.current_dispatch_id)
        async with session_factory() as session:
            stale_authority = await read_node_operation_authority(
                cast(AsyncSession, session),
                scope,
            )

        await executor.execute(
            scope=scope,
            operation_name="checkpoint",
            arguments=_terminal_checkpoint("blocked"),
        )
        request = get_node_operation_descriptor(
            NodeOperationName.CHECKPOINT
        ).request_model.model_validate(_terminal_checkpoint("retry"))
        with pytest.raises(RuntimeOperationError) as error:
            async with session_factory() as session:
                await execute_controller_node_operation(
                    cast(AsyncSession, session),
                    stale_authority,
                    NodeOperationName.CHECKPOINT,
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
        scope = _scope(ids.task_id, ids.current_dispatch_id)
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="checkpoint",
                        arguments=_terminal_checkpoint("blocked"),
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name="open_human_request",
                        arguments=_HUMAN_REQUEST_ARGUMENTS,
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        error = _one_runtime_error(results)
        assert error.code in {
            OperationFailureCode.CONFLICT,
            OperationFailureCode.STALE_DISPATCH,
        }
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

        assert (int(checkpoint_count or 0), int(request_count or 0)) in {
            (1, 0),
            (0, 1),
        }
        assert int(wait_count or 0) == int(request_count or 0)
        assert dispatch is not None and dispatch.status == "closed"
        assert dispatch.node_activity_revision == 2
        assert [signal.activity_revision for signal in signals] == [1, 2]


@pytest.mark.parametrize(
    ("wait_operation", "wait_arguments"),
    (
        ("open_human_request", _HUMAN_REQUEST_ARGUMENTS),
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

        scope = _scope(ids.task_id, ids.current_dispatch_id)
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
                                "assignment": {"prompt": "Do bounded child work."},
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
        assert error.code in {
            OperationFailureCode.CONFLICT,
            OperationFailureCode.STALE_DISPATCH,
        }
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


def _scope(task_id: str, dispatch_id: str) -> NodeOperationScope:
    return NodeOperationScope(task_id=task_id, dispatch_id=dispatch_id)


def _terminal_checkpoint(outcome: str) -> dict[str, object]:
    return {
        "summary": f"The current assignment reached {outcome}.",
        "details": "This is the exact teammate-facing terminal report.",
        "outcome": outcome,
    }


def _one_runtime_error(results: Sequence[object]) -> RuntimeOperationError:
    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeOperationError)
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    return errors[0]
