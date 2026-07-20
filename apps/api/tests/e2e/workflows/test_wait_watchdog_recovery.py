from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from autoclaw.config import CodexSettings, RuntimeSettings, Settings
from autoclaw.definitions.contracts.registry import PolicyDefinitionInput
from autoclaw.definitions.contracts.workflow import NodeKind, ProviderKind
from autoclaw.persistence.models import DispatchTurnModel, FlowModel, PolicyRevisionModel
from autoclaw.runtime.contracts import HumanRequestResolveRequest
from autoclaw.runtime.dispatch import accept_provider_start_if_current
from autoclaw.runtime.dispatch.ordinary_continuation import OrdinaryOpeningResult
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.human_request.continuation import open_human_request_successor
from autoclaw.runtime.human_request.service import resolve_human_request
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    HumanRequestTerminal,
    WatchdogDue,
)
from autoclaw.runtime.watchdog import (
    WatchdogRecoveryResult,
    calculate_watchdog_due_at,
    recover_stale_dispatch,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds

_BASE_TIME = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


@dataclass
class _ManualClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


async def test_human_wait_excludes_watchdog_then_recovery_replaces_once(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    clock = _ManualClock(_BASE_TIME + timedelta(minutes=15, seconds=1))
    dependencies = _opening_dependencies(publisher, clock)
    async with seeded_executor(tmp_path, suffix="wait-watchdog-recovery") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        await _enable_policy(session_factory)
        excluded, continued = await _wait_for_human_and_continue(
            executor,
            session_factory,
            ids,
            dependencies,
        )
        assert continued.dispatch_id is not None

        recovery_anchor = _BASE_TIME + timedelta(hours=1)
        stale_after_wait = await _set_stale_dispatch(
            session_factory,
            continued.dispatch_id,
            activity_revision=2,
            anchor=recovery_anchor,
        )
        clock.current = stale_after_wait.due_at + timedelta(seconds=1)
        async with session_factory() as session:
            recovered = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=stale_after_wait,
                dependencies=dependencies,
            )
        async with session_factory() as session:
            duplicate = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=stale_after_wait,
                dependencies=dependencies,
            )
            predecessor = await session.get(DispatchTurnModel, continued.dispatch_id)
            successor = await session.get(DispatchTurnModel, recovered.dispatch_id)
            flow = await session.get(FlowModel, ids.flow_id)

    assert excluded.outcome == "skipped"
    assert continued.outcome == "opened"
    assert recovered.outcome == "opened"
    assert duplicate.outcome == "skipped"
    assert predecessor is not None and predecessor.closed_reason == "watchdog_superseded"
    assert successor is not None and successor.opened_reason == "watchdog_recovery"
    assert flow is not None and flow.current_dispatch_id == recovered.dispatch_id


async def _wait_for_human_and_continue(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    dependencies: DispatchOpeningDependencies,
) -> tuple[WatchdogRecoveryResult, OrdinaryOpeningResult]:
    stale_before_wait = await _set_stale_dispatch(
        session_factory,
        ids.current_dispatch_id,
        activity_revision=1,
        anchor=_BASE_TIME,
    )
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose the recovery direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Continue?",
                        "options": [{"id": "yes", "title": "Yes"}],
                    }
                ],
            }
        },
    )
    request_id = str(opened.model_dump()["request_id"])
    async with session_factory() as session:
        excluded = await recover_stale_dispatch(
            cast(AsyncSession, session),
            signal=stale_before_wait,
            dependencies=dependencies,
        )
        await resolve_human_request(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            request_id=request_id,
            request=HumanRequestResolveRequest(item_responses={"direction": "yes"}),
        )
    async with session_factory() as session:
        continued = await open_human_request_successor(
            cast(AsyncSession, session),
            signal=HumanRequestTerminal(request_id),
            dependencies=dependencies,
        )
    assert continued.dispatch_id is not None
    await _accept_dispatch(session_factory, ids.task_id, continued.dispatch_id)
    return excluded, continued


async def _set_stale_dispatch(
    session_factory: SessionFactory,
    dispatch_id: str,
    *,
    activity_revision: int,
    anchor: datetime,
) -> WatchdogDue:
    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, dispatch_id)
        assert dispatch is not None
        dispatch.status = "open"
        dispatch.adapter_started_at = anchor
        dispatch.last_node_activity_at = anchor
        dispatch.node_activity_revision = activity_revision
        dispatch.next_provider_start_at = None
        dispatch.provider_start_retry_kind = None
        await session.commit()
    return WatchdogDue(
        dispatch_id=dispatch_id,
        activity_revision=activity_revision,
        due_at=calculate_watchdog_due_at(
            adapter_started_at=anchor,
            last_node_activity_at=anchor,
            inactivity_timeout_seconds=900,
        ),
    )


async def _accept_dispatch(
    session_factory: SessionFactory,
    task_id: str,
    dispatch_id: str,
) -> None:
    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, dispatch_id)
        assert dispatch is not None and dispatch.next_provider_start_at is not None
        accepted = await accept_provider_start_if_current(
            cast(AsyncSession, session),
            task_id=task_id,
            dispatch_id=dispatch_id,
            expected_provider_start_revision=dispatch.provider_start_revision,
            expected_provider_start_attempt_count=dispatch.provider_start_attempt_count,
            expected_due_at=dispatch.next_provider_start_at,
            accepted_at=_BASE_TIME + timedelta(minutes=30),
        )
        await session.commit()
    assert accepted.is_accepted


async def _enable_policy(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
        assert policy is not None
        policy.content_json = PolicyDefinitionInput(
            id="policy.target",
            description="Allow wait continuation and watchdog recovery.",
            applies_to=[NodeKind.ROOT, NodeKind.WORKER],
        ).model_dump(mode="json")
        await session.commit()


def _opening_dependencies(
    publisher: CapturedRuntimeEffectPublisher,
    clock: _ManualClock,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(
                default_provider=ProviderKind.CODEX,
                watchdog_inactivity_timeout_seconds=900,
                watchdog_same_attempt_replacement_limit=2,
            ),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
        clock=clock,
    )
