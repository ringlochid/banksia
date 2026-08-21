from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import oh_my_subagents.runtime.node_operations.executor as executor_module
from oh_my_subagents.persistence.models import (
    AssignmentModel,
    DispatchTurnModel,
    HumanRequestModel,
)
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.dispatch.authority import (
    read_node_operation_authority,
    refresh_node_activity,
)
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.node_operations import (
    NodeActivitySignal,
    NodeOperationScope,
)
from tests.helpers.executor_harness import (
    seeded_executor,
)


async def test_executor_refreshes_activity_once_and_plan_revisions_only_on_change(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="plan") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        scope = NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id)
        first = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={
                "explanation": "Bound the implementation.",
                "steps": [{"step": "Inspect controller truth", "status": "in_progress"}],
            },
        )
        repeated = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={
                "explanation": "Bound the implementation.",
                "steps": [{"step": "Inspect controller truth", "status": "in_progress"}],
            },
        )
        cleared = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={"steps": []},
        )
        clear_absent = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={"steps": []},
        )

        assert first.model_dump()["changed"] is True
        assert repeated.model_dump()["changed"] is False
        assert cleared.model_dump() == {"changed": True, "plan": None}
        assert clear_absent.model_dump() == {"changed": False, "plan": None}
        assert [signal.activity_revision for signal in signals] == [1, 2, 3, 4]
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
        assert dispatch is not None and dispatch.node_activity_revision == 4
        assert assignment is not None and assignment.work_plan_revision == 2


async def test_pre_admission_scope_failure_does_not_refresh_activity(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="stale") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id="task.wrong",
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="get_current_context",
                arguments={},
            )
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        assert signals == []
        assert dispatch is not None and dispatch.node_activity_revision == 0


async def test_two_stale_session_admissions_both_advance_activity_monotonically(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="activity-race") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        scope = NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id)
        async with session_factory() as first_session:
            first_authority = await read_node_operation_authority(
                cast(AsyncSession, first_session),
                scope,
            )
        async with session_factory() as second_session:
            second_authority = await read_node_operation_authority(
                cast(AsyncSession, second_session),
                scope,
            )

        later_activity = utc_now() + timedelta(minutes=1)
        async with session_factory() as first_session:
            first_refresh = await refresh_node_activity(
                cast(AsyncSession, first_session),
                first_authority,
                occurred_at=later_activity,
            )
            await first_session.commit()
        async with session_factory() as second_session:
            second_refresh = await refresh_node_activity(
                cast(AsyncSession, second_session),
                second_authority,
                occurred_at=later_activity - timedelta(minutes=2),
            )
            await second_session.commit()
        async with session_factory() as read_session:
            dispatch = await read_session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert first_refresh.activity_revision == 1
        assert second_refresh.activity_revision == 2
        assert second_refresh.occurred_at == first_refresh.occurred_at
        assert dispatch is not None
        assert dispatch.node_activity_revision == 2
        assert dispatch.last_node_activity_at == second_refresh.occurred_at


async def test_executor_publishes_the_committed_activity_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="activity-signal") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        monkeypatch.setattr(
            executor_module,
            "utc_now",
            lambda: utc_now() - timedelta(days=1),
        )

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert dispatch is not None
        assert len(signals) == 1
        assert signals[0].activity_revision == dispatch.node_activity_revision
        assert signals[0].occurred_at == dispatch.last_node_activity_at


async def test_transaction_b_rejects_rotated_managed_generation_after_activity_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="generation-between-phases") as (
        executor,
        session_factory,
        ids,
        signals,
    ):

        async def publish_and_rotate_generation(signal: NodeActivitySignal) -> None:
            signals.append(signal)
            async with session_factory() as session:
                dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
                assert dispatch is not None
                dispatch.provider_start_revision += 1
                await session.commit()

        monkeypatch.setattr(
            executor,
            "_publish_activity_signal",
            publish_and_rotate_generation,
        )

        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                    provider_start_revision=0,
                ),
                operation_name="open_human_request",
                arguments={
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
                },
            )

        async with session_factory() as session:
            request = await session.scalar(
                select(HumanRequestModel).where(HumanRequestModel.task_id == ids.task_id)
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert error.value.code == OperationFailureCode.STALE_DISPATCH
        assert error.value.is_retryable is False
        assert request is None
        assert dispatch is not None
        assert dispatch.status == "open"
        assert dispatch.provider_start_revision == 1
        assert dispatch.node_activity_revision == 1
        assert [signal.activity_revision for signal in signals] == [1]
