from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
from banksia.runtime.node_operations import (
    NodeActivitySignal,
    NodeOperationExecutor,
    NodeOperationScope,
)
from banksia.runtime.task_control.service import (
    cancel_runtime_task,
    pause_runtime_task,
)
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    make_seed_child_terminal,
    seeded_async_executor,
    seeded_executor,
    synchronized_transition_claims,
)
from tests.helpers.lineage_seed import RuntimeIds

type _BarrierCompetitor = Literal["pause", "cancel", "terminal_checkpoint"]


@dataclass(frozen=True, slots=True)
class _TaskControlRaceObservation:
    task_status: str
    control_revision: int
    team_revision_id: str | None
    source_closed_reason: str | None
    transition_count: int
    team_revision_count: int


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
    async with seeded_async_executor(
        tmp_path,
        suffix=f"task-first-{competitor}",
    ) as (executor, session_factory, ids, _signals):
        replan_error = await _run_replan_after_control_transition(
            executor,
            session_factory,
            ids,
            competitor,
            monkeypatch,
        )
        assert replan_error.code in {
            OperationFailureCode.CONFLICT,
            OperationFailureCode.STALE_DISPATCH,
        }
        observed = await _read_task_control_race(session_factory, ids)

    assert observed.task_status == ("paused" if competitor == "pause" else "cancelled")
    assert observed.control_revision == 1
    assert observed.team_revision_id == ids.team_revision_id
    assert observed.source_closed_reason == ("paused" if competitor == "pause" else "cancelled")
    assert observed.transition_count == 0
    assert observed.team_revision_count == 1


async def _run_replan_after_control_transition(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    competitor: Literal["pause", "cancel"],
    monkeypatch: pytest.MonkeyPatch,
) -> RuntimeOperationError:
    activity_admitted = asyncio.Event()
    release_replan = asyncio.Event()

    async def hold_after_activity_admission(signal: NodeActivitySignal) -> None:
        del signal
        activity_admitted.set()
        await release_replan.wait()

    monkeypatch.setattr(
        executor,
        "_publish_activity_signal",
        hold_after_activity_admission,
    )
    replan = asyncio.create_task(
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
            assert task is not None and task.current_team_revision_id is not None
            transition = pause_runtime_task if competitor == "pause" else cancel_runtime_task
            await transition(
                control_session,
                ids.task_id,
                expected_team_revision_id=task.current_team_revision_id,
                expected_control_revision=task.control_revision,
            )
    finally:
        release_replan.set()
    result = (
        await asyncio.wait_for(
            asyncio.gather(replan, return_exceptions=True),
            timeout=5,
        )
    )[0]
    assert isinstance(result, RuntimeOperationError)
    return result


async def _read_task_control_race(
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
) -> _TaskControlRaceObservation:
    async with session_factory() as session:
        task = await session.get(TaskModel, ids.task_id)
        source = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        transition_count = await _count(session, ReplanTransitionModel)
        team_revision_count = await _count(session, TeamRevisionModel)
    assert task is not None and source is not None
    return _TaskControlRaceObservation(
        task_status=task.status,
        control_revision=task.control_revision,
        team_revision_id=task.current_team_revision_id,
        source_closed_reason=source.closed_reason,
        transition_count=transition_count,
        team_revision_count=team_revision_count,
    )


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
