from __future__ import annotations

import asyncio
from typing import cast

import pytest
from banksia.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    FlowModel,
    FlowRevisionModel,
    MemberModel,
    ReplanTransitionModel,
    TeamRevisionModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.ordinary_continuation import OrdinaryOpeningResult
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.flow.service import cancel_runtime_flow, pause_runtime_flow
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.node_operations.activity import NodeActivitySignal
from banksia.runtime.replan.continuation import continue_committed_replan
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.postgres_runtime_race import (
    PostgresRuntimeHarness,
    observe_flow_first_order,
    postgres_runtime_harness,
    wait_for_thread_event,
)


@pytest.mark.parametrize("control_operation", ("pause", "cancel"))
async def test_node_mutation_holds_flow_before_pause_or_cancel(
    control_operation: str,
) -> None:
    activity_admitted = asyncio.Event()
    release_activity = asyncio.Event()

    async def hold_after_activity_admission(signal: NodeActivitySignal) -> None:
        del signal
        activity_admitted.set()
        await release_activity.wait()

    async with postgres_runtime_harness(
        suffix=f"node-flow-first-{control_operation}",
        publish_activity_signal=hold_after_activity_admission,
    ) as harness:
        replan_task = asyncio.create_task(
            harness.executor.execute(
                scope=NodeOperationScope(
                    task_id=harness.ids.task_id,
                    dispatch_id=harness.ids.current_dispatch_id,
                ),
                operation_name="add_child",
                arguments={"child": {"title": "Reviewer"}},
            )
        )
        await asyncio.wait_for(activity_admitted.wait(), timeout=10)

        async with harness.session_factory() as blocker:
            locked_dispatch_id = await blocker.scalar(
                select(DispatchTurnModel.dispatch_id)
                .where(DispatchTurnModel.dispatch_id == harness.ids.current_dispatch_id)
                .with_for_update()
            )
            assert locked_dispatch_id == harness.ids.current_dispatch_id
            with observe_flow_first_order(
                harness.engine,
                owner_local_table="dispatch_turns",
            ) as lock_events:
                release_activity.set()
                await wait_for_thread_event(lock_events.owner_flow_acquired)
                await wait_for_thread_event(lock_events.owner_local_update_started)
                control_task = asyncio.create_task(
                    _apply_flow_control(
                        harness,
                        control_operation=control_operation,
                    )
                )
                await wait_for_thread_event(lock_events.control_flow_update_started)
                await blocker.rollback()
                replan_result, control_result = await asyncio.wait_for(
                    asyncio.gather(
                        replan_task,
                        control_task,
                        return_exceptions=True,
                    ),
                    timeout=20,
                )

        assert not isinstance(replan_result, BaseException)
        assert isinstance(control_result, RuntimeOperationError)
        assert control_result.code == OperationFailureCode.CONFLICT
        async with harness.session_factory() as session:
            counts = await _replan_counts(session)
            flow = await session.get(FlowModel, harness.ids.flow_id)
            source_dispatch = await session.get(
                DispatchTurnModel,
                harness.ids.current_dispatch_id,
            )
            attempt = await session.get(AttemptModel, harness.ids.root_attempt_id)

    assert counts == (2, 2, 3, 1)
    assert flow is not None and flow.status == "running"
    assert flow.active_flow_revision_id != harness.ids.flow_revision_id
    assert source_dispatch is not None
    assert source_dispatch.closed_reason == "structural_replan"
    assert attempt is not None and attempt.current_dispatch_id is None


async def test_replan_successor_holds_flow_before_cancel() -> None:
    async with postgres_runtime_harness(suffix="successor-flow-first") as harness:
        await harness.executor.execute(
            scope=NodeOperationScope(
                task_id=harness.ids.task_id,
                dispatch_id=harness.ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        async with harness.session_factory() as session:
            transition = await session.scalar(select(ReplanTransitionModel))
            assert transition is not None
            transition_id = transition.replan_transition_id
            await session.execute(
                update(ReplanTransitionModel)
                .where(ReplanTransitionModel.replan_transition_id == transition_id)
                .values(manifest_state="current", successor_state="pending")
            )
            await session.commit()

        async with harness.session_factory() as blocker:
            locked_transition_id = await blocker.scalar(
                select(ReplanTransitionModel.replan_transition_id)
                .where(ReplanTransitionModel.replan_transition_id == transition_id)
                .with_for_update()
            )
            assert locked_transition_id == transition_id
            with observe_flow_first_order(
                harness.engine,
                owner_local_table="replan_transitions",
            ) as lock_events:
                successor_task = asyncio.create_task(
                    _continue_replan_successor(harness, transition_id=transition_id)
                )
                await wait_for_thread_event(lock_events.owner_flow_acquired)
                await wait_for_thread_event(lock_events.owner_local_update_started)
                cancel_task = asyncio.create_task(
                    _apply_flow_control(
                        harness,
                        control_operation="cancel",
                    )
                )
                await wait_for_thread_event(lock_events.control_flow_update_started)
                await blocker.rollback()
                successor_result, cancel_result = await asyncio.wait_for(
                    asyncio.gather(
                        successor_task,
                        cancel_task,
                        return_exceptions=True,
                    ),
                    timeout=20,
                )

        assert isinstance(successor_result, OrdinaryOpeningResult)
        assert not isinstance(cancel_result, BaseException)
        assert successor_result.outcome == "opened"
        assert successor_result.dispatch_id is not None
        async with harness.session_factory() as session:
            flow = await session.get(FlowModel, harness.ids.flow_id)
            attempt = await session.get(AttemptModel, harness.ids.root_attempt_id)
            transition = await session.get(ReplanTransitionModel, transition_id)
            successor = await session.get(
                DispatchTurnModel,
                successor_result.dispatch_id,
            )
            live_dispatch_count = await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(DispatchTurnModel.status.in_(("starting", "open")))
            )

    assert flow is not None and flow.status == "cancelled"
    assert attempt is not None and attempt.status == "cancelled"
    assert attempt.current_dispatch_id is None and attempt.current_wait_id is None
    assert transition is not None and transition.successor_state == "opened"
    assert transition.successor_dispatch_id == successor_result.dispatch_id
    assert successor is not None and successor.closed_reason == "cancelled"
    assert live_dispatch_count == 0


async def _apply_flow_control(
    harness: PostgresRuntimeHarness,
    *,
    control_operation: str,
) -> object:
    control = pause_runtime_flow if control_operation == "pause" else cancel_runtime_flow
    async with harness.session_factory() as session:
        flow = await session.get(FlowModel, harness.ids.flow_id)
        assert flow is not None
        assert flow.active_flow_revision_id is not None
        return await control(
            session,
            harness.ids.task_id,
            expected_active_flow_revision_id=flow.active_flow_revision_id,
            expected_control_revision=flow.control_revision,
        )


async def _continue_replan_successor(
    harness: PostgresRuntimeHarness,
    *,
    transition_id: str,
) -> OrdinaryOpeningResult:
    async with harness.session_factory() as session:
        return await continue_committed_replan(
            session,
            transition_id=transition_id,
            dependencies=harness.dependencies,
        )


async def _replan_counts(session: AsyncSession) -> tuple[int, int, int, int]:
    values = []
    for model in (
        TeamRevisionModel,
        FlowRevisionModel,
        MemberModel,
        ReplanTransitionModel,
    ):
        count = await session.scalar(select(func.count()).select_from(model))
        assert count is not None
        values.append(count)
    return cast(tuple[int, int, int, int], tuple(values))
