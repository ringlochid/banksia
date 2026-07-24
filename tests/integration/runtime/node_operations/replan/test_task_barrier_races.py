from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from sqlalchemy import func, select

from banksia.persistence.models import (
    AttemptCheckpointModel,
    DispatchTurnModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeActivitySignal, NodeOperationScope
from banksia.runtime.task_control.service import (
    cancel_runtime_task,
    pause_runtime_task,
)
from tests.helpers.executor_harness import (
    make_seed_child_terminal,
    seeded_async_executor,
    seeded_executor,
    synchronized_transition_claims,
)

type _BarrierCompetitor = Literal["pause", "cancel", "terminal_checkpoint"]


@pytest.mark.parametrize(
    "competitor",
    ("pause", "cancel", "terminal_checkpoint"),
)
async def test_task_first_barrier_allows_one_replan_or_competing_transition(
    tmp_path: Path,
    competitor: _BarrierCompetitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if competitor == "terminal_checkpoint":
        await _assert_replan_or_terminal_checkpoint_wins(tmp_path)
        return
    await _assert_task_control_wins_before_replan_commit(
        tmp_path,
        competitor,
        monkeypatch,
    )


async def _assert_task_control_wins_before_replan_commit(
    tmp_path: Path,
    competitor: Literal["pause", "cancel"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity_admitted = asyncio.Event()
    release_replan = asyncio.Event()

    async def hold_after_activity_admission(signal: NodeActivitySignal) -> None:
        del signal
        activity_admitted.set()
        await release_replan.wait()

    async with seeded_async_executor(
        tmp_path,
        suffix=f"task-first-{competitor}",
    ) as (executor, session_factory, ids, _signals):
        monkeypatch.setattr(
            executor,
            "_publish_activity_signal",
            hold_after_activity_admission,
        )
        replan_task = asyncio.create_task(
            executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="add_child",
                arguments={"child": {"title": "Late reviewer"}},
            )
        )
        await asyncio.wait_for(activity_admitted.wait(), timeout=5)
        try:
            async with session_factory() as control_session:
                task = await control_session.get(TaskModel, ids.task_id)
                assert task is not None
                if competitor == "pause":
                    await pause_runtime_task(
                        control_session,
                        ids.task_id,
                        expected_team_revision_id=cast(
                            str,
                            task.current_team_revision_id,
                        ),
                        expected_control_revision=task.control_revision,
                    )
                else:
                    await cancel_runtime_task(
                        control_session,
                        ids.task_id,
                        expected_team_revision_id=cast(
                            str,
                            task.current_team_revision_id,
                        ),
                        expected_control_revision=task.control_revision,
                    )
        finally:
            release_replan.set()
        replan_result = (
            await asyncio.wait_for(
                asyncio.gather(replan_task, return_exceptions=True),
                timeout=5,
            )
        )[0]

        assert isinstance(replan_result, RuntimeOperationError)
        assert replan_result.code in {
            OperationFailureCode.CONFLICT,
            OperationFailureCode.STALE_DISPATCH,
        }
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            source = await session.get(
                DispatchTurnModel,
                ids.current_dispatch_id,
            )
            transition_count = await _count(session, ReplanTransitionModel)
            team_revision_count = await _count(session, TeamRevisionModel)

    assert task is not None and source is not None
    assert task.status == ("paused" if competitor == "pause" else "cancelled")
    assert task.control_revision == 1
    assert task.current_team_revision_id == ids.team_revision_id
    assert source.closed_reason == ("paused" if competitor == "pause" else "cancelled")
    assert transition_count == 0
    assert team_revision_count == 1


async def _assert_replan_or_terminal_checkpoint_wins(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="task-first-terminal") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="add_child",
                        arguments={"child": {"title": "Racing reviewer"}},
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name="checkpoint",
                        arguments={
                            "outcome": "blocked",
                            "summary": "The assignment cannot continue.",
                        },
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        errors = [result for result in results if isinstance(result, BaseException)]
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeOperationError)
        assert errors[0].code in {
            OperationFailureCode.CONFLICT,
            OperationFailureCode.STALE_DISPATCH,
        }
        assert sum(not isinstance(result, BaseException) for result in results) == 1

        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            source = await session.get(
                DispatchTurnModel,
                ids.current_dispatch_id,
            )
            transition_count = await _count(session, ReplanTransitionModel)
            checkpoint_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(AttemptCheckpointModel)
                    .where(AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id)
                )
                or 0
            )
            team_revision_count = await _count(session, TeamRevisionModel)

    assert task is not None and source is not None
    assert (transition_count, checkpoint_count) in {(1, 0), (0, 1)}
    if transition_count:
        assert task.status == "running"
        assert task.terminal_outcome is None
        assert source.closed_reason == "structural_replan"
        assert team_revision_count == 2
    else:
        assert task.status == "completed"
        assert task.terminal_outcome == "blocked"
        assert source.closed_reason == "boundary"
        assert team_revision_count == 1


async def _count(session: Any, model: type[object]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)
