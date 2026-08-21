from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

from sqlalchemy import Connection, Engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from oh_my_subagents.config import RuntimeSettings
from oh_my_subagents.persistence import RuntimeBase
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.node_mcp import DispatchMcpBindingRegistry
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor, NodeOperationName
from oh_my_subagents.runtime.node_operations.catalog import get_node_operation_descriptor
from oh_my_subagents.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DeadlineScheduler,
    DispatchStartDue,
)
from oh_my_subagents.runtime.providers import (
    DispatchStartRequest,
    ProviderAdapterRegistry,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStartError,
    ProviderSteerOutcome,
    ProviderStopOutcome,
)
from oh_my_subagents.runtime.providers.starter import DispatchStarter
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope
from tests.helpers.sqlite_runtime import SyncSessionAdapter, create_runtime_schema_engine

START_DUE_AT = datetime(2026, 7, 18, 1, tzinfo=UTC)
ACCEPTED_AT = START_DUE_AT + timedelta(seconds=3)
PROVIDER_START_REVISION = 7

type _SyncSessionFactory = sessionmaker[Session]


class _DispatchRow(Protocol):
    status: str
    closed_reason: str | None
    provider_start_revision: int
    provider_start_attempt_count: int
    provider_start_retry_kind: str | None
    provider_start_last_error_code: str | None


class _TaskRow(Protocol):
    status: str
    pause_reason: str | None
    pause_details: Mapping[str, object]


@dataclass(frozen=True)
class StartingDispatchDatabase:
    engine: Engine
    session_factory: _SyncSessionFactory
    ids: RuntimeIds


class RecordingAdapter:
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

    async def can_steer(self, dispatch_id: str) -> bool:
        return dispatch_id in {request.dispatch_id for request in self.requests}

    async def steer(self, dispatch_id: str, message: str) -> ProviderSteerOutcome:
        del message
        return (
            ProviderSteerOutcome.DELIVERED
            if await self.can_steer(dispatch_id)
            else ProviderSteerOutcome.NOT_RUNNING
        )

    async def read_availability(self) -> ProviderCheckResult:
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.AVAILABLE,
            code="test_available",
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        yield


class CommitThenRaiseSession(SyncSessionAdapter):
    async def commit(self) -> None:
        await super().commit()
        raise RuntimeError("simulated lost commit acknowledgement")


class _RecordingScheduler:
    def __init__(self) -> None:
        self.registered: list[DispatchStartDue] = []

    def register(self, signal: DispatchStartDue) -> bool:
        self.registered.append(signal)
        return True


class _OperationLister:
    async def list_operations(self, _scope: object) -> tuple[object, ...]:
        return (get_node_operation_descriptor(NodeOperationName.GET_CURRENT_CONTEXT),)


@contextmanager
def starting_dispatch_database(
    tmp_path: Path,
    *,
    suffix: str,
) -> Iterator[StartingDispatchDatabase]:
    engine = create_runtime_schema_engine(tmp_path, name=f"{suffix}.sqlite")
    session_factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection, suffix=suffix)
            _prepare_starting_dispatch(connection, ids)
        yield StartingDispatchDatabase(
            engine=engine,
            session_factory=session_factory,
            ids=ids,
        )
    finally:
        engine.dispose()


def create_dispatch_starter(
    database: StartingDispatchDatabase,
    adapter: RecordingAdapter | None,
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
        clock=lambda: now,
    )
    return starter, binding_registry, scheduler, publisher


async def handle_dispatch_start(
    database: StartingDispatchDatabase,
    starter: DispatchStarter,
    signal: DispatchStartDue,
) -> None:
    async with SyncSessionAdapter(database.session_factory) as session:
        await starter.schedule_or_start_dispatch(cast(AsyncSession, session), signal)


def dispatch_start_signal(database: StartingDispatchDatabase) -> DispatchStartDue:
    return DispatchStartDue(
        database.ids.current_dispatch_id,
        PROVIDER_START_REVISION,
        START_DUE_AT,
    )


def prepare_dispatch_workspace(
    database: StartingDispatchDatabase,
    tmp_path: Path,
) -> None:
    task_root = tmp_path / f"task-root-{database.ids.suffix}"
    workspace = tmp_path / f"workspace-{database.ids.suffix}"
    workspace.mkdir(parents=True)
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


def read_dispatch_row(database: StartingDispatchDatabase) -> _DispatchRow:
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


def read_dispatch_request_text(database: StartingDispatchDatabase) -> tuple[str, str]:
    requests = RuntimeBase.metadata.tables["dispatch_requests"]
    with database.engine.connect() as connection:
        row = connection.execute(
            select(requests.c.instructions, requests.c.input).where(
                requests.c.dispatch_id == database.ids.current_dispatch_id
            )
        ).one()
    return str(row.instructions), str(row.input)


def read_task_row(database: StartingDispatchDatabase) -> _TaskRow:
    tasks = RuntimeBase.metadata.tables["tasks"]
    with database.engine.connect() as connection:
        return cast(
            _TaskRow,
            connection.execute(select(tasks).where(tasks.c.task_id == database.ids.task_id)).one(),
        )


def read_attempt_current_dispatch_id(database: StartingDispatchDatabase) -> str | None:
    attempts = RuntimeBase.metadata.tables["attempts"]
    with database.engine.connect() as connection:
        return connection.scalar(
            select(attempts.c.current_dispatch_id).where(
                attempts.c.attempt_id == database.ids.root_attempt_id
            )
        )


def _prepare_starting_dispatch(connection: Connection, ids: RuntimeIds) -> None:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    connection.execute(
        dispatches.update()
        .where(dispatches.c.dispatch_id == ids.current_dispatch_id)
        .values(
            status="starting",
            provider_start_revision=PROVIDER_START_REVISION,
            provider_start_attempt_count=3,
            next_provider_start_at=START_DUE_AT,
            provider_start_retry_kind="uncertain_acceptance",
            provider_start_last_error_code="provider_timeout",
            adapter_started_at=None,
            last_node_activity_at=None,
        )
    )


__all__ = [
    "ACCEPTED_AT",
    "PROVIDER_START_REVISION",
    "START_DUE_AT",
    "CommitThenRaiseSession",
    "RecordingAdapter",
    "StartingDispatchDatabase",
    "create_dispatch_starter",
    "dispatch_start_signal",
    "handle_dispatch_start",
    "prepare_dispatch_workspace",
    "read_attempt_current_dispatch_id",
    "read_dispatch_request_text",
    "read_dispatch_row",
    "read_task_row",
    "starting_dispatch_database",
]
