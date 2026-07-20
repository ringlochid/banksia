from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

import pytest
from autoclaw.config import RuntimeSettings
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.persistence import RuntimeBase
from autoclaw.runtime.node_mcp import DispatchMcpBindingRegistry
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationName
from autoclaw.runtime.node_operations.catalog import get_node_operation_descriptor
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DeadlineScheduler,
    DispatchStartDue,
    WatchdogDeadlineChanged,
)
from autoclaw.runtime.providers import (
    DispatchStartRequest,
    ProviderAdapterRegistry,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
    ProviderStopOutcome,
)
from autoclaw.runtime.providers.starter import DispatchStarter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
)
from tests.integration.runtime_schema_contract.test_provider_start_acceptance import (
    ACCEPTED_AT,
    PROVIDER_START_REVISION,
    START_DUE_AT,
    StartingDispatchDatabase,
    starting_dispatch_database,
)


class _RecordingScheduler:
    def __init__(self) -> None:
        self.registered: list[DispatchStartDue] = []

    def register(self, signal: DispatchStartDue) -> bool:
        self.registered.append(signal)
        return True


class _OperationLister:
    async def list_operations(self, _scope: object) -> tuple[object, ...]:
        return (get_node_operation_descriptor(NodeOperationName.GET_CURRENT_CONTEXT),)


class _RecordingAdapter:
    kind = ProviderKind.CODEX

    def __init__(
        self,
        *,
        failure: ProviderStartError | None = None,
        on_start: Callable[[], None] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.failure = failure
        self.on_start = on_start
        self.events = events if events is not None else []
        self.requests: list[DispatchStartRequest] = []
        self.stop_calls: list[str] = []

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        self.events.append(f"start:{request.dispatch_id}")
        self.requests.append(request)
        if self.on_start is not None:
            self.on_start()
        if self.failure is not None:
            raise self.failure
        return ProviderStartAccepted()

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        self.events.append(f"stop:{dispatch_id}")
        self.stop_calls.append(dispatch_id)
        return ProviderStopOutcome.STOPPED

    async def read_availability(self) -> ProviderCheckResult:
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.AVAILABLE,
            code="test_available",
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        yield


class _CommitThenRaiseSession(SyncSessionAdapter):
    async def commit(self) -> None:
        await super().commit()
        raise RuntimeError("simulated lost commit acknowledgement")


class _DispatchRow(Protocol):
    status: str
    closed_reason: str | None
    provider_start_revision: int
    provider_start_attempt_count: int
    provider_start_retry_kind: str | None
    provider_start_last_error_code: str | None


class _FlowRow(Protocol):
    status: str
    current_dispatch_id: str | None
    pause_reason: str | None
    pause_details: Mapping[str, object]


async def test_accepted_start_opens_once_retains_binding_and_publishes_watchdog(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-accepted") as database:
        _write_request_pair(database, tmp_path)
        adapter = _RecordingAdapter()
        starter, registry, scheduler, publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await _handle(database, starter, _signal(database))

        dispatch = _dispatch_row(database)
        request = adapter.requests[0]
        assert dispatch.status == "open"
        assert dispatch.provider_start_attempt_count == 4
        assert request.instructions == b"controller instructions\n"
        assert request.input == b"dispatch input\n"
        assert request.managed_node_mcp is not None
        assert request.managed_node_mcp.enabled_tools == ("get_current_context",)
        credential = request.managed_node_mcp.bearer_token.get_secret_value()
        assert registry.authenticate(credential) is not None
        assert scheduler.registered == []
        assert publisher.signals == (
            WatchdogDeadlineChanged(
                dispatch_id=database.ids.current_dispatch_id,
                activity_revision=0,
                due_at=ACCEPTED_AT + timedelta(minutes=15),
            ),
        )


@pytest.mark.parametrize(
    ("failure_kind", "expected_stop_count"),
    (
        (ProviderStartFailureKind.DEFINITE_FAILURE, 0),
        (ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE, 1),
    ),
)
async def test_provider_failure_rotates_binding_and_retries_same_dispatch(
    tmp_path: Path,
    failure_kind: ProviderStartFailureKind,
    expected_stop_count: int,
) -> None:
    with starting_dispatch_database(
        tmp_path,
        suffix=f"starter-{failure_kind.value}",
    ) as database:
        _write_request_pair(database, tmp_path)
        adapter = _RecordingAdapter(
            failure=ProviderStartError(
                kind=failure_kind,
                code=ProviderStartErrorCode.CONNECTION,
            )
        )
        starter, registry, scheduler, _publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await _handle(database, starter, _signal(database))

        dispatch = _dispatch_row(database)
        request = adapter.requests[0]
        assert dispatch.status == "starting"
        assert dispatch.provider_start_revision == PROVIDER_START_REVISION + 1
        assert dispatch.provider_start_attempt_count == 4
        assert dispatch.provider_start_retry_kind == failure_kind.value
        assert dispatch.provider_start_last_error_code == "provider_connection"
        assert len(adapter.stop_calls) == expected_stop_count
        assert scheduler.registered == [
            DispatchStartDue(
                dispatch_id=database.ids.current_dispatch_id,
                provider_start_revision=PROVIDER_START_REVISION + 1,
                due_at=ACCEPTED_AT + timedelta(seconds=8),
            )
        ]
        assert request.managed_node_mcp is not None
        credential = request.managed_node_mcp.bearer_token.get_secret_value()
        assert registry.authenticate(credential) is None


async def test_invalid_request_ref_pauses_without_provider_io(tmp_path: Path) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-invalid-ref") as database:
        _write_request_pair(database, tmp_path)
        with database.engine.begin() as connection:
            refs = RuntimeBase.metadata.tables["dispatch_prompt_refs"]
            connection.execute(
                refs.update()
                .where(refs.c.dispatch_id == database.ids.current_dispatch_id)
                .values(input_logical_path="_runtime/dispatch/another/input.md")
            )
        adapter = _RecordingAdapter()
        starter, _registry, _scheduler, publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await _handle(database, starter, _signal(database))

        dispatch = _dispatch_row(database)
        flow = _flow_row(database)
        assert adapter.requests == []
        assert dispatch.status == "closed"
        assert dispatch.closed_reason == "control_failed"
        assert flow.status == "paused"
        assert flow.current_dispatch_id is None
        assert flow.pause_reason == "runtime_transition_failed"
        assert publisher.signals == ()


async def test_persisted_unsupported_provider_policy_pauses_without_provider_io(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-unsupported-policy") as database:
        _write_request_pair(database, tmp_path)
        capabilities = RuntimeBase.metadata.tables["dispatch_capability_sets"]
        with database.engine.begin() as connection:
            connection.execute(
                capabilities.update()
                .where(capabilities.c.dispatch_id == database.ids.current_dispatch_id)
                .values(provider_native_access="denied")
            )
        adapter = _RecordingAdapter()
        starter, _registry, scheduler, publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await _handle(database, starter, _signal(database))

        dispatch = _dispatch_row(database)
        flow = _flow_row(database)
        assert adapter.requests == []
        assert adapter.stop_calls == []
        assert dispatch.status == "closed"
        assert dispatch.closed_reason == "control_failed"
        assert flow.status == "paused"
        assert flow.pause_details["failure_code"] == "provider_capability_unsupported"
        assert scheduler.registered == []
        assert publisher.signals == ()


async def test_missing_committed_provider_adapter_pauses_before_binding_or_io(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-missing-adapter") as database:
        _write_request_pair(database, tmp_path)
        starter, registry, scheduler, publisher = _starter(
            database,
            None,
            now=ACCEPTED_AT,
        )

        await _handle(database, starter, _signal(database))

        dispatch = _dispatch_row(database)
        flow = _flow_row(database)
        assert dispatch.status == "closed"
        assert dispatch.closed_reason == "control_failed"
        assert flow.status == "paused"
        assert flow.pause_details["failure_code"] == "dispatch_provider_adapter_missing"
        assert registry.revoke_all() == 0
        assert scheduler.registered == []
        assert publisher.signals == ()


async def test_early_node_close_is_acceptance_loser_with_stop_and_no_retry(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-early-close") as database:
        _write_request_pair(database, tmp_path)

        def close_before_acceptance() -> None:
            dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
            flows = RuntimeBase.metadata.tables["flows"]
            with database.engine.begin() as connection:
                connection.execute(
                    dispatches.update()
                    .where(dispatches.c.dispatch_id == database.ids.current_dispatch_id)
                    .values(
                        status="closed",
                        closed_at=ACCEPTED_AT,
                        closed_reason="boundary",
                        next_provider_start_at=None,
                        provider_start_retry_kind=None,
                    )
                )
                connection.execute(
                    flows.update()
                    .where(flows.c.flow_id == database.ids.flow_id)
                    .values(current_dispatch_id=None)
                )

        adapter = _RecordingAdapter(on_start=close_before_acceptance)
        starter, registry, scheduler, publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await _handle(database, starter, _signal(database))

        dispatch = _dispatch_row(database)
        assert dispatch.status == "closed"
        assert dispatch.provider_start_revision == PROVIDER_START_REVISION
        assert adapter.stop_calls == [database.ids.current_dispatch_id]
        assert scheduler.registered == []
        assert publisher.signals == ()
        request = adapter.requests[0]
        assert request.managed_node_mcp is not None
        credential = request.managed_node_mcp.bearer_token.get_secret_value()
        assert registry.authenticate(credential) is None


async def test_initial_watchdog_recovery_stops_predecessor_before_start_once(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-watchdog") as database:
        _write_request_pair(database, tmp_path)
        dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
        with database.engine.begin() as connection:
            connection.execute(
                dispatches.update()
                .where(dispatches.c.dispatch_id == database.ids.current_dispatch_id)
                .values(
                    opened_reason="watchdog_recovery",
                    provider_start_revision=0,
                    provider_start_attempt_count=0,
                )
            )
        events: list[str] = []
        adapter = _RecordingAdapter(events=events)
        starter, registry, _scheduler, _publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )
        predecessor_id = database.ids.child_dispatch_id
        predecessor = registry.issue_binding(
            task_id=database.ids.task_id,
            dispatch_id=predecessor_id,
            provider_start_revision=0,
            exposure_ceiling=("get_current_context",),
        )

        await _handle(
            database,
            starter,
            DispatchStartDue(database.ids.current_dispatch_id, 0, START_DUE_AT),
        )

        assert events[:2] == [
            f"stop:{predecessor_id}",
            f"start:{database.ids.current_dispatch_id}",
        ]
        assert registry.authenticate(predecessor.credential) is None


async def test_future_signal_only_registers_and_stale_due_signal_does_no_io(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-stale") as database:
        adapter = _RecordingAdapter()
        starter, _registry, scheduler, _publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )
        future = DispatchStartDue(
            database.ids.current_dispatch_id,
            PROVIDER_START_REVISION + 100,
            ACCEPTED_AT + timedelta(hours=1),
        )

        await _handle(database, starter, future)
        await _handle(
            database,
            starter,
            DispatchStartDue(
                database.ids.current_dispatch_id,
                PROVIDER_START_REVISION - 1,
                START_DUE_AT,
            ),
        )

        assert scheduler.registered == [future]
        assert adapter.requests == []


async def test_startup_recovery_stops_and_rotates_before_retrying_same_dispatch(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-recovered") as database:
        adapter = _RecordingAdapter()
        starter, _registry, scheduler, publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )
        signal = _signal(database)
        starter.mark_recovered(signal)

        await _handle(database, starter, signal)

        dispatch = _dispatch_row(database)
        assert adapter.requests == []
        assert adapter.stop_calls == [database.ids.current_dispatch_id]
        assert dispatch.status == "starting"
        assert dispatch.provider_start_revision == PROVIDER_START_REVISION + 1
        assert dispatch.provider_start_attempt_count == 4
        assert dispatch.provider_start_retry_kind == "uncertain_acceptance"
        assert dispatch.provider_start_last_error_code == "provider_uncertain"
        assert scheduler.registered == [
            DispatchStartDue(
                database.ids.current_dispatch_id,
                PROVIDER_START_REVISION + 1,
                ACCEPTED_AT + timedelta(seconds=8),
            )
        ]
        assert publisher.signals == ()


async def test_ambiguous_acceptance_commit_rereads_truth_before_cleanup(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-ambiguous-commit") as database:
        _write_request_pair(database, tmp_path)
        adapter = _RecordingAdapter()
        starter, registry, scheduler, publisher = _starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        async with _CommitThenRaiseSession(database.session_factory) as session:
            await starter.schedule_or_start_dispatch(cast(AsyncSession, session), _signal(database))

        dispatch = _dispatch_row(database)
        request = adapter.requests[0]
        assert dispatch.status == "open"
        assert dispatch.provider_start_attempt_count == 4
        assert adapter.stop_calls == []
        assert scheduler.registered == []
        assert request.managed_node_mcp is not None
        credential = request.managed_node_mcp.bearer_token.get_secret_value()
        assert registry.authenticate(credential) is not None
        assert publisher.signals == (
            WatchdogDeadlineChanged(
                dispatch_id=database.ids.current_dispatch_id,
                activity_revision=0,
                due_at=ACCEPTED_AT + timedelta(minutes=15),
            ),
        )


def _starter(
    database: StartingDispatchDatabase,
    adapter: _RecordingAdapter | None,
    *,
    now: datetime,
) -> tuple[
    DispatchStarter,
    DispatchMcpBindingRegistry,
    _RecordingScheduler,
    CapturedRuntimeEffectPublisher,
]:
    binding_registry = DispatchMcpBindingRegistry()
    scheduler = _RecordingScheduler()
    publisher = CapturedRuntimeEffectPublisher()
    starter = DispatchStarter(
        adapters=ProviderAdapterRegistry(() if adapter is None else (adapter,)),
        binding_registry=binding_registry,
        operation_executor=cast(NodeOperationExecutor, _OperationLister()),
        scheduler=cast(DeadlineScheduler, scheduler),
        runtime_effect_publisher=publisher,
        runtime_settings=RuntimeSettings(),
        session_factory=lambda: cast(
            AbstractAsyncContextManager[AsyncSession],
            SyncSessionAdapter(database.session_factory),
        ),
        managed_node_mcp_url="http://127.0.0.1:18125/_internal/node/mcp",
        compatibility_node_mcp_url="http://127.0.0.1:18125/node/mcp",
        clock=lambda: now,
    )
    return starter, binding_registry, scheduler, publisher


async def _handle(
    database: StartingDispatchDatabase,
    starter: DispatchStarter,
    signal: DispatchStartDue,
) -> None:
    async with SyncSessionAdapter(database.session_factory) as session:
        await starter.schedule_or_start_dispatch(cast(AsyncSession, session), signal)


def _signal(database: StartingDispatchDatabase) -> DispatchStartDue:
    return DispatchStartDue(
        database.ids.current_dispatch_id,
        PROVIDER_START_REVISION,
        START_DUE_AT,
    )


def _write_request_pair(database: StartingDispatchDatabase, tmp_path: Path) -> None:
    task_root = tmp_path / f"task-root-{database.ids.suffix}"
    workspace = tmp_path / f"workspace-{database.ids.suffix}"
    workspace.mkdir(parents=True)
    request_root = task_root / "_runtime" / "dispatch" / database.ids.current_dispatch_id
    request_root.mkdir(parents=True)
    (request_root / "instructions.md").write_bytes(b"controller instructions\n")
    (request_root / "input.md").write_bytes(b"dispatch input\n")
    with database.engine.begin() as connection:
        tasks = RuntimeBase.metadata.tables["tasks"]
        bindings = RuntimeBase.metadata.tables["workspace_bindings"]
        connection.execute(
            tasks.update()
            .where(tasks.c.task_id == database.ids.task_id)
            .values(task_root_path=str(task_root))
        )
        connection.execute(
            bindings.update()
            .where(bindings.c.task_id == database.ids.task_id)
            .values(normalized_root_path=str(workspace))
        )


def _dispatch_row(database: StartingDispatchDatabase) -> _DispatchRow:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    with database.engine.connect() as connection:
        return cast(
            _DispatchRow,
            connection.execute(
                select(dispatches).where(
                    dispatches.c.dispatch_id == database.ids.current_dispatch_id
                )
            ).one(),
        )


def _flow_row(database: StartingDispatchDatabase) -> _FlowRow:
    flows = RuntimeBase.metadata.tables["flows"]
    with database.engine.connect() as connection:
        return cast(
            _FlowRow,
            connection.execute(select(flows).where(flows.c.flow_id == database.ids.flow_id)).one(),
        )
