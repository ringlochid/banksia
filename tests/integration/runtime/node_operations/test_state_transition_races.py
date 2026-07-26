from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    DelegationWaveModel,
    DispatchTurnModel,
    HumanRequestModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import read_node_operation_authority
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.node_operations.catalog import get_node_operation_descriptor
from banksia.runtime.node_operations.contracts import NodeOperationDescriptor, NodeOperationName
from banksia.runtime.node_operations.operation_router import (
    execute_controller_node_operation,
)
from tests.helpers.executor_harness import (
    make_seed_child_terminal,
    seeded_async_executor,
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
                "options": [
                    {"id": "a", "title": "A"},
                    {"id": "b", "title": "B"},
                ],
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
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
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
            await make_seed_child_terminal(session, ids)
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
        ).request_model.model_validate(_terminal_checkpoint("blocked"))
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
            waits = tuple(
                await session.scalars(
                    select(AttemptWaitModel).where(
                        AttemptWaitModel.task_id == ids.task_id,
                        AttemptWaitModel.assignment_id == ids.root_assignment_id,
                        AttemptWaitModel.attempt_id == ids.root_attempt_id,
                        AttemptWaitModel.source_dispatch_id == ids.current_dispatch_id,
                    )
                )
            )
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert (int(checkpoint_count or 0), int(request_count or 0)) in {
            (1, 0),
            (0, 1),
        }
        assert len(waits) == int(request_count or 0)
        assert attempt is not None
        if waits:
            assert waits[0].human_request_id is not None
            assert attempt.current_dispatch_id is None
            assert attempt.current_wait_id == waits[0].wait_id
        else:
            assert attempt.current_wait_id is None
        assert dispatch is not None and dispatch.status == "closed"
        assert dispatch.node_activity_revision == 2
        assert [signal.activity_revision for signal in signals] == [1, 2]


async def test_delegate_and_command_wait_have_one_stable_async_sqlite_winner(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="delegate-command") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)

        scope = _scope(ids.task_id, ids.current_dispatch_id)
        delegate_descriptor = get_node_operation_descriptor(NodeOperationName.DELEGATE)
        delegate_request = delegate_descriptor.request_model.model_validate(
            {
                "assignments": [
                    {
                        "child_id": "child",
                        "prompt": "Do bounded child work.",
                    }
                ],
            }
        )
        command_descriptor = get_node_operation_descriptor(NodeOperationName.START_COMMAND_RUN)
        command_request = command_descriptor.request_model.model_validate(
            {
                "request": {
                    "command": {
                        "kind": "argv",
                        "argv": ["printf", "ready"],
                    },
                    "summary": "Produce one bounded output.",
                }
            }
        )

        async def commit_operation(
            descriptor: NodeOperationDescriptor,
            request: BaseModel,
        ) -> object:
            async with session_factory() as session:
                return await executor._execute_node_operation_transaction(
                    session,
                    scope=scope,
                    descriptor=descriptor,
                    request=request,
                )

        async with synchronized_transition_claims():
            results = await asyncio.gather(
                commit_operation(delegate_descriptor, delegate_request),
                commit_operation(command_descriptor, command_request),
                return_exceptions=True,
            )

        error = _one_runtime_error(results)
        assert error.code in {
            OperationFailureCode.CONFLICT,
            OperationFailureCode.STALE_DISPATCH,
        }
        async with session_factory() as session:
            wave_count = await session.scalar(select(func.count()).select_from(DelegationWaveModel))
            command_run_count = await session.scalar(
                select(func.count()).select_from(CommandRunModel)
            )
            waits = tuple(
                await session.scalars(
                    select(AttemptWaitModel).where(
                        AttemptWaitModel.task_id == ids.task_id,
                        AttemptWaitModel.assignment_id == ids.root_assignment_id,
                        AttemptWaitModel.attempt_id == ids.root_attempt_id,
                        AttemptWaitModel.source_dispatch_id == ids.current_dispatch_id,
                    )
                )
            )
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            open_child_assignment_count = await session.scalar(
                select(func.count())
                .select_from(AssignmentModel)
                .where(
                    AssignmentModel.task_id == ids.task_id,
                    AssignmentModel.member_id == ids.child_member_id,
                    AssignmentModel.terminal_outcome.is_(None),
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert (int(wave_count or 0), int(command_run_count or 0)) in {
            (1, 0),
            (0, 1),
        }
        assert len(waits) == 1
        assert attempt is not None and dispatch is not None
        if wave_count:
            assert waits[0].delegation_wave_id is not None
            assert attempt.current_dispatch_id is None
            assert attempt.current_wait_id == waits[0].wait_id
            assert open_child_assignment_count == 1
            assert dispatch.status == "closed"
        else:
            assert waits[0].delegation_wave_id is None
            assert attempt.current_dispatch_id is None
            assert attempt.current_wait_id == waits[0].wait_id
            assert open_child_assignment_count == 0
            assert dispatch.status == "closed"
        assert dispatch.node_activity_revision == 0


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
