from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from autoclaw.config import CodexSettings, RuntimeSettings, Settings
from autoclaw.definitions.contracts.registry import PolicyDefinitionInput
from autoclaw.definitions.contracts.workflow import NodeKind, ProviderKind
from autoclaw.persistence.models import (
    CommandRunModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
    HumanRequestModel,
    PolicyRevisionModel,
    TaskEventModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import read_node_operation_authority
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.dispatch.request_pair import (
    DispatchRequestPairRefs,
    publish_dispatch_request_pair,
)
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations.contracts import (
    NodeOperationScope,
    OpenHumanRequestRequest,
    StartCommandRunRequest,
)
from autoclaw.runtime.node_operations.external_wait_handlers import (
    open_human_request,
    start_command_run,
)
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchCleanupRequested,
    DispatchStartDue,
    WatchdogDue,
)
from autoclaw.runtime.watchdog import (
    calculate_watchdog_due_at,
    recover_stale_dispatch,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds

_BASE_TIME = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
type WaitKind = Literal["human", "command"]


@dataclass
class _ManualClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


async def test_watchdog_replaces_one_stale_dispatch_and_duplicate_signal_loses(
    tmp_path: Path,
) -> None:
    clock = _ManualClock(_BASE_TIME + timedelta(minutes=15, seconds=1))
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="watchdog-replace") as (
        _,
        session_factory,
        ids,
        _,
    ):
        await _enable_target_policy(session_factory)
        signal = await _stale_signal(session_factory, ids, activity_revision=7)
        dependencies = _opening_dependencies(clock=clock, publisher=publisher)
        async with session_factory() as session:
            first = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
        async with session_factory() as session:
            duplicate = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
            predecessor = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            successor = await session.get(DispatchTurnModel, first.dispatch_id)
            flow = await session.get(FlowModel, ids.flow_id)
            refs = await session.get(DispatchPromptRefsModel, first.dispatch_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.dispatch_id == first.dispatch_id,
                    TaskEventModel.event_type == "dispatch_opened",
                )
            )

    assert first.outcome == "opened"
    assert duplicate.outcome == "skipped"
    assert predecessor is not None and predecessor.closed_reason == "watchdog_superseded"
    assert successor is not None and successor.status == "starting"
    assert successor.opened_reason == "watchdog_recovery"
    assert successor.predecessor_dispatch_id == ids.current_dispatch_id
    assert successor.assignment_id == ids.root_assignment_id
    assert successor.attempt_id == ids.root_attempt_id
    assert flow is not None and flow.current_dispatch_id == first.dispatch_id
    assert dispatch_count == 4
    assert refs is not None
    input_text = (tmp_path / "task-watchdog-replace" / refs.input_logical_path).read_text(
        encoding="utf-8"
    )
    assert '"kind": "watchdog_recovery"' in input_text
    assert '"recovery_count": 1' in input_text
    assert event is not None
    assert event.payload["opened_reason"] == "watchdog_recovery"
    assert event.payload["predecessor_dispatch_id"] == ids.current_dispatch_id
    assert len(publisher.signals) == 1
    assert isinstance(publisher.signals[0], DispatchStartDue)
    assert publisher.signals[0].dispatch_id == first.dispatch_id


async def test_new_activity_during_materialization_makes_due_signal_stale(
    tmp_path: Path,
) -> None:
    suffix = "watchdog-activity-race"
    database_path = tmp_path / f"{suffix}.sqlite"
    clock = _ManualClock(_BASE_TIME + timedelta(minutes=15, seconds=1))
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix=suffix) as (
        _,
        session_factory,
        ids,
        _,
    ):
        await _enable_target_policy(session_factory)
        signal = await _stale_signal(session_factory, ids, activity_revision=1)

        def publish_then_refresh_activity(
            *,
            paths: object,
            dispatch_id: str,
            instructions_bytes: bytes,
            input_bytes: bytes,
        ) -> DispatchRequestPairRefs:
            refs = publish_dispatch_request_pair(
                paths=paths,  # type: ignore[arg-type]
                dispatch_id=dispatch_id,
                instructions_bytes=instructions_bytes,
                input_bytes=input_bytes,
            )
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "UPDATE dispatch_turns SET node_activity_revision = 2 WHERE dispatch_id = ?",
                    (ids.current_dispatch_id,),
                )
                connection.commit()
            return refs

        dependencies = DispatchOpeningDependencies.create(
            settings=_provider_settings(),
            available_adapter_kinds={ProviderKind.CODEX},
            post_commit_publisher=publisher,
            clock=clock,
            request_pair_publisher=publish_then_refresh_activity,
        )
        async with session_factory() as session:
            result = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
            source = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert result.outcome == "skipped"
    assert source is not None and source.status == "open"
    assert source.node_activity_revision == 2
    assert dispatch_count == 3
    assert publisher.signals == ()


async def test_watchdog_preparation_failure_closes_authority_and_pauses(
    tmp_path: Path,
) -> None:
    clock = _ManualClock(_BASE_TIME + timedelta(minutes=15, seconds=1))
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="watchdog-preparation-failure") as (
        _,
        session_factory,
        ids,
        _,
    ):
        signal = await _stale_signal(session_factory, ids, activity_revision=1)
        dependencies = DispatchOpeningDependencies.create(
            settings=Settings(runtime=RuntimeSettings(default_provider=ProviderKind.CODEX)),
            available_adapter_kinds={ProviderKind.CODEX},
            post_commit_publisher=publisher,
            clock=clock,
        )
        async with session_factory() as session:
            result = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            flow = await session.get(FlowModel, ids.flow_id)

    assert result.outcome == "paused"
    assert dispatch is not None and dispatch.closed_reason == "control_failed"
    assert flow is not None and flow.pause_reason == "runtime_transition_failed"
    assert isinstance(publisher.signals[-1], DispatchCleanupRequested)


@pytest.mark.parametrize("source_kind", ("human", "command"))
async def test_terminal_unconsumed_source_excludes_watchdog(
    tmp_path: Path,
    source_kind: WaitKind,
) -> None:
    suffix = f"watchdog-terminal-{source_kind}"
    clock = _ManualClock(_BASE_TIME + timedelta(minutes=15, seconds=1))
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix=suffix) as (
        _,
        session_factory,
        ids,
        _,
    ):
        signal = await _stale_signal(session_factory, ids, activity_revision=1)
        async with session_factory() as session:
            _add_terminal_source(cast(AsyncSession, session), ids, source_kind)
            await session.commit()
        async with session_factory() as session:
            result = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=_opening_dependencies(clock=clock, publisher=publisher),
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

    assert result.outcome == "skipped"
    assert dispatch is not None and dispatch.status == "open"
    assert publisher.signals == ()


@pytest.mark.parametrize("wait_kind", ("human", "command"))
@pytest.mark.parametrize("winner", ("wait", "watchdog"))
async def test_wait_open_and_watchdog_have_one_commit_order_winner(
    tmp_path: Path,
    wait_kind: WaitKind,
    winner: Literal["wait", "watchdog"],
) -> None:
    suffix = f"watchdog-{wait_kind}-{winner}"
    clock = _ManualClock(_BASE_TIME + timedelta(minutes=15, seconds=1))
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix=suffix) as (
        _,
        session_factory,
        ids,
        _,
    ):
        await _enable_target_policy(session_factory)
        signal = await _stale_signal(session_factory, ids, activity_revision=1)
        async with session_factory() as session:
            authority = await read_node_operation_authority(
                cast(AsyncSession, session),
                NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
            )
            await session.rollback()

        if winner == "wait":
            async with session_factory() as session:
                await _open_wait(cast(AsyncSession, session), authority, wait_kind)
            async with session_factory() as session:
                result = await recover_stale_dispatch(
                    cast(AsyncSession, session),
                    signal=signal,
                    dependencies=_opening_dependencies(clock=clock, publisher=publisher),
                )
            assert result.outcome == "skipped"
        else:
            async with session_factory() as session:
                result = await recover_stale_dispatch(
                    cast(AsyncSession, session),
                    signal=signal,
                    dependencies=_opening_dependencies(clock=clock, publisher=publisher),
                )
            assert result.outcome == "opened"
            async with session_factory() as session:
                with pytest.raises(RuntimeOperationError) as error:
                    await _open_wait(cast(AsyncSession, session), authority, wait_kind)
                await session.rollback()
            assert error.value.code == OperationFailureCode.CONFLICT

        async with session_factory() as session:
            source_count = await _wait_source_count(
                cast(AsyncSession, session),
                wait_kind,
            )
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert (source_count, int(dispatch_count or 0)) == ((1, 3) if winner == "wait" else (0, 4))


async def test_third_same_attempt_stale_dispatch_pauses_without_successor(
    tmp_path: Path,
) -> None:
    clock = _ManualClock(_BASE_TIME + timedelta(minutes=15, seconds=1))
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="watchdog-cap") as (
        _,
        session_factory,
        ids,
        _,
    ):
        await _enable_target_policy(session_factory)
        dependencies = _opening_dependencies(clock=clock, publisher=publisher)
        current_dispatch_id = ids.current_dispatch_id
        for replacement_index in range(2):
            signal = await _stale_signal(
                session_factory,
                ids,
                dispatch_id=current_dispatch_id,
                activity_revision=replacement_index + 1,
                anchor=_BASE_TIME + timedelta(hours=replacement_index),
            )
            clock.current = signal.due_at + timedelta(seconds=1)
            async with session_factory() as session:
                result = await recover_stale_dispatch(
                    cast(AsyncSession, session),
                    signal=signal,
                    dependencies=dependencies,
                )
            assert result.outcome == "opened" and result.dispatch_id is not None
            current_dispatch_id = result.dispatch_id

        third_signal = await _stale_signal(
            session_factory,
            ids,
            dispatch_id=current_dispatch_id,
            activity_revision=3,
            anchor=_BASE_TIME + timedelta(hours=2),
        )
        clock.current = third_signal.due_at + timedelta(seconds=1)
        async with session_factory() as session:
            exhausted = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=third_signal,
                dependencies=dependencies,
            )
            flow = await session.get(FlowModel, ids.flow_id)
            dispatch = await session.get(DispatchTurnModel, current_dispatch_id)
            replacement_count = await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(DispatchTurnModel.opened_reason == "watchdog_recovery")
            )
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert exhausted.outcome == "paused"
    assert exhausted.dispatch_id is None
    assert flow is not None and flow.status == "paused"
    assert flow.pause_reason == "runtime_recovery_exhausted"
    assert flow.current_dispatch_id is None
    assert dispatch is not None and dispatch.closed_reason == "control_failed"
    assert replacement_count == 2
    assert dispatch_count == 5
    assert isinstance(publisher.signals[-1], DispatchCleanupRequested)
    assert publisher.signals[-1].dispatch_id == current_dispatch_id


async def _stale_signal(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    activity_revision: int,
    dispatch_id: str | None = None,
    anchor: datetime = _BASE_TIME,
) -> WatchdogDue:
    exact_dispatch_id = dispatch_id or ids.current_dispatch_id
    await _set_open_activity(
        session_factory,
        exact_dispatch_id,
        adapter_started_at=anchor,
        last_activity_at=anchor,
        activity_revision=activity_revision,
    )
    return WatchdogDue(
        dispatch_id=exact_dispatch_id,
        activity_revision=activity_revision,
        due_at=calculate_watchdog_due_at(
            adapter_started_at=anchor,
            last_node_activity_at=anchor,
            inactivity_timeout_seconds=900,
        ),
    )


async def _set_open_activity(
    session_factory: SessionFactory,
    dispatch_id: str,
    *,
    adapter_started_at: datetime,
    last_activity_at: datetime | None,
    activity_revision: int,
) -> None:
    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, dispatch_id)
        assert dispatch is not None
        dispatch.status = "open"
        dispatch.adapter_started_at = adapter_started_at
        dispatch.last_node_activity_at = last_activity_at
        dispatch.node_activity_revision = activity_revision
        dispatch.next_provider_start_at = None
        dispatch.provider_start_retry_kind = None
        dispatch.provider_start_last_error_code = None
        dispatch.closed_at = None
        dispatch.closed_reason = None
        await session.commit()


async def _enable_target_policy(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
        assert policy is not None
        policy.content_json = PolicyDefinitionInput(
            id="policy.target",
            description="Allow exact watchdog continuation in the fixture.",
            applies_to=[NodeKind.ROOT, NodeKind.WORKER],
        ).model_dump(mode="json")
        await session.commit()


def _provider_settings() -> Settings:
    return Settings(
        runtime=RuntimeSettings(
            default_provider=ProviderKind.CODEX,
            watchdog_inactivity_timeout_seconds=900,
            watchdog_same_attempt_replacement_limit=2,
        ),
        codex=CodexSettings(enabled=True),
    )


def _opening_dependencies(
    *,
    clock: _ManualClock,
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=_provider_settings(),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
        clock=clock,
    )


def _add_terminal_source(
    session: AsyncSession,
    ids: RuntimeIds,
    source_kind: WaitKind,
) -> None:
    if source_kind == "human":
        session.add(
            HumanRequestModel(
                request_id=f"human-request.{ids.suffix}",
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                attempt_id=ids.root_attempt_id,
                source_dispatch_id=ids.current_dispatch_id,
                request_kind="input",
                request_summary="Already answered.",
                request_items_json=[{"id": "answer", "prompt": "Answer?"}],
                context_refs_json=None,
                suggested_human_instruction=None,
                capability_basis_json={"decision": "allow", "kind": "input"},
                due_at=None,
                timeout_policy_json=None,
                default_behavior_json=None,
                status="resolved",
                resolution_kind="answered",
                item_responses_json={"answer": "yes"},
                resolution_policy_basis_json=None,
                resolution_summary="Answered.",
                resolved_by_actor_ref="operator.test",
                resolved_by_surface="controller",
                opened_at=_BASE_TIME,
                resolved_at=_BASE_TIME,
            )
        )
        return
    session.add(
        CommandRunModel(
            run_id=f"command-run.{ids.suffix}",
            task_id=ids.task_id,
            flow_id=ids.flow_id,
            assignment_id=ids.root_assignment_id,
            attempt_id=ids.root_attempt_id,
            source_dispatch_id=ids.current_dispatch_id,
            command_spec_json={"kind": "argv", "argv": ["true"]},
            cwd_policy_json=None,
            environment_refs_json=None,
            summary="Already complete.",
            expected_outputs_json=None,
            timeout_seconds=None,
            due_at=None,
            state="succeeded",
            ownership_revision=1,
            terminal_summary="Succeeded.",
            terminal_exit_code=0,
            terminal_event_source="controller",
            created_at=_BASE_TIME,
            started_at=_BASE_TIME,
            ended_at=_BASE_TIME,
        )
    )


async def _open_wait(
    session: AsyncSession,
    authority: object,
    wait_kind: WaitKind,
) -> None:
    from autoclaw.runtime.dispatch.authority import NodeOperationAuthority

    exact_authority = cast(NodeOperationAuthority, authority)
    if wait_kind == "human":
        human_request = OpenHumanRequestRequest.model_validate(
            {
                "request": {
                    "kind": "input",
                    "summary": "Wait for one answer.",
                    "items": [
                        {
                            "id": "answer",
                            "prompt": "Answer?",
                            "options": [{"id": "yes", "title": "Yes"}],
                        }
                    ],
                }
            }
        )
        await open_human_request(session, exact_authority, human_request)
        return
    command_request = StartCommandRunRequest.model_validate(
        {
            "request": {
                "command": {"kind": "argv", "argv": ["true"]},
                "summary": "Run one command.",
            }
        }
    )
    await start_command_run(session, exact_authority, command_request)


async def _wait_source_count(session: AsyncSession, wait_kind: WaitKind) -> int:
    model = HumanRequestModel if wait_kind == "human" else CommandRunModel
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


__all__ = []
