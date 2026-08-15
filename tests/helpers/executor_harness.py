from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Collection
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from unittest.mock import patch

from sqlalchemy import Engine, event, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

import banksia.runtime.node_operations.executor as executor_module
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence import RuntimeBase
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptModel,
    TaskModel,
    WorkspaceBindingModel,
)
from banksia.persistence.session import (
    RuntimeAsyncSession,
    install_sqlite_transaction_control,
)
from banksia.platform.workspace_files import ensure_private_directory
from banksia.providers import ProviderKind
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeActivitySignal, NodeOperationExecutor
from banksia.runtime.node_operations.follow_on import SupportProjectionPublisher
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.post_commit.publisher import RuntimeEffectPublisher
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    FIXTURE_TIMESTAMP,
    RuntimeIds,
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)

type SessionFactory = Callable[[], SyncSessionAdapter]
type AsyncSessionFactory = async_sessionmaker[RuntimeAsyncSession]


@asynccontextmanager
async def synchronized_transition_claims(*, contenders: int = 2) -> AsyncIterator[None]:
    original_claim = executor_module.claim_exact_node_operation_transition
    arrived = 0
    release = asyncio.Event()

    async def synchronized_claim(
        session: AsyncSession,
        authority: NodeOperationAuthority,
    ) -> None:
        nonlocal arrived
        arrived += 1
        if arrived == contenders:
            release.set()
        await release.wait()
        await original_claim(session, authority)

    with patch.object(
        executor_module,
        "claim_exact_node_operation_transition",
        synchronized_claim,
    ):
        yield


@asynccontextmanager
async def seeded_executor(
    tmp_path: Path,
    *,
    suffix: str,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    support_projection_publisher: SupportProjectionPublisher | None = None,
    provider_settings: Settings | None = None,
    available_adapter_kinds: Collection[ProviderKind] = (ProviderKind.CODEX,),
) -> AsyncIterator[
    tuple[
        NodeOperationExecutor,
        SessionFactory,
        RuntimeIds,
        list[NodeActivitySignal],
    ]
]:
    sync_engine: Engine = create_runtime_schema_engine(tmp_path, name=f"{suffix}.sqlite")
    workspace, task_root = _prepare_runtime_paths(tmp_path, suffix)
    try:
        with sync_engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection, suffix=suffix)
            connection.execute(
                RuntimeBase.metadata.tables["tasks"]
                .update()
                .where(RuntimeBase.metadata.tables["tasks"].c.task_id == ids.task_id)
                .values(task_root_path=str(task_root))
            )
            connection.execute(
                RuntimeBase.metadata.tables["workspace_bindings"]
                .update()
                .where(RuntimeBase.metadata.tables["workspace_bindings"].c.task_id == ids.task_id)
                .values(normalized_root_path=str(workspace))
            )
    except Exception:
        sync_engine.dispose()
        raise

    sync_factory = sessionmaker(sync_engine, expire_on_commit=False, autoflush=False)

    def session_factory() -> SyncSessionAdapter:
        return SyncSessionAdapter(sync_factory)

    signals: list[NodeActivitySignal] = []

    async def publish(signal: NodeActivitySignal) -> None:
        signals.append(signal)

    try:
        with patch.object(
            executor_module,
            "get_session_factory",
            return_value=session_factory,
        ):
            yield (
                NodeOperationExecutor(
                    publish_activity_signal=publish,
                    runtime_effect_publisher=runtime_effect_publisher,
                    support_projection_publisher=support_projection_publisher,
                    dispatch_opening_dependencies=DispatchOpeningDependencies.create(
                        settings=provider_settings or _default_provider_settings(),
                        available_adapter_kinds=available_adapter_kinds,
                        post_commit_publisher=CapturedRuntimeEffectPublisher(),
                    ),
                ),
                session_factory,
                ids,
                signals,
            )
    finally:
        sync_engine.dispose()


@asynccontextmanager
async def seeded_async_executor(
    tmp_path: Path,
    *,
    suffix: str,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    support_projection_publisher: SupportProjectionPublisher | None = None,
    provider_settings: Settings | None = None,
    available_adapter_kinds: Collection[ProviderKind] = (ProviderKind.CODEX,),
) -> AsyncIterator[
    tuple[
        NodeOperationExecutor,
        AsyncSessionFactory,
        RuntimeIds,
        list[NodeActivitySignal],
    ]
]:
    """Seed one real aiosqlite runtime with a separate session per contender."""

    engine, session_factory = _create_async_sqlite_runtime(tmp_path, suffix)
    signals: list[NodeActivitySignal] = []

    async def publish(signal: NodeActivitySignal) -> None:
        signals.append(signal)

    try:
        ids = await _seed_async_runtime(engine, session_factory, tmp_path, suffix)
        with patch.object(
            executor_module,
            "get_session_factory",
            return_value=session_factory,
        ):
            yield (
                NodeOperationExecutor(
                    publish_activity_signal=publish,
                    runtime_effect_publisher=runtime_effect_publisher,
                    support_projection_publisher=support_projection_publisher,
                    dispatch_opening_dependencies=DispatchOpeningDependencies.create(
                        settings=provider_settings or _default_provider_settings(),
                        available_adapter_kinds=available_adapter_kinds,
                        post_commit_publisher=CapturedRuntimeEffectPublisher(),
                    ),
                ),
                session_factory,
                ids,
                signals,
            )
    finally:
        await engine.dispose()


def _prepare_runtime_paths(tmp_path: Path, suffix: str) -> tuple[Path, Path]:
    workspace = seeded_task_workspace(tmp_path, suffix)
    task_root = seeded_task_root(tmp_path, suffix)
    ensure_private_directory(task_root)
    for path in (
        task_root / "notes",
        task_root / "artifacts",
        task_root / "command-runs",
    ):
        ensure_private_directory(path)
    return workspace, task_root


def _create_async_sqlite_runtime(
    tmp_path: Path,
    suffix: str,
) -> tuple[AsyncEngine, AsyncSessionFactory]:
    database_path = tmp_path / f"{suffix}.sqlite"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"timeout": 5},
    )
    install_sqlite_transaction_control(engine.sync_engine)
    event.listen(engine.sync_engine, "connect", _configure_async_sqlite_connection)
    return (
        engine,
        async_sessionmaker(
            engine,
            class_=RuntimeAsyncSession,
            expire_on_commit=False,
            autoflush=False,
        ),
    )


def _configure_async_sqlite_connection(
    dbapi_connection: SQLiteConnection,
    connection_record: object,
) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


async def _seed_async_runtime(
    engine: AsyncEngine,
    session_factory: AsyncSessionFactory,
    tmp_path: Path,
    suffix: str,
) -> RuntimeIds:
    workspace, task_root = _prepare_runtime_paths(tmp_path, suffix)
    async with engine.begin() as connection:
        await connection.run_sync(RuntimeBase.metadata.create_all)
        await connection.run_sync(seed_catalog)
        ids = await connection.run_sync(partial(seed_runtime_scope, suffix=suffix))
    async with session_factory() as session:
        await session.execute(
            update(TaskModel)
            .where(TaskModel.task_id == ids.task_id)
            .values(task_root_path=str(task_root))
        )
        await session.execute(
            update(WorkspaceBindingModel)
            .where(WorkspaceBindingModel.task_id == ids.task_id)
            .values(normalized_root_path=str(workspace))
        )
        await session.commit()
    return ids


def seeded_task_workspace(tmp_path: Path, suffix: str) -> Path:
    return tmp_path / f"task-{suffix}" / "workspace"


def seeded_task_root(tmp_path: Path, suffix: str) -> Path:
    return seeded_task_workspace(tmp_path, suffix) / ".banksia" / f"task.{suffix}"


async def make_seed_child_terminal(
    session: AsyncSession | SyncSessionAdapter,
    ids: RuntimeIds,
) -> None:
    """Close the pre-seeded child lane so a test may delegate to it again."""

    child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
    child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
    assert child_assignment is not None
    assert child_attempt is not None
    child_assignment.terminal_outcome = "blocked"
    child_assignment.closed_at = FIXTURE_TIMESTAMP
    child_attempt.status = "completed"
    child_attempt.terminal_outcome = "blocked"
    child_attempt.latest_checkpoint_id = ids.child_checkpoint_id
    child_attempt.closed_at = FIXTURE_TIMESTAMP
    session.add(
        AcceptedBoundaryModel(
            accepted_boundary_id=f"accepted-boundary.{ids.child_dispatch_id}",
            source_dispatch_id=ids.child_dispatch_id,
            task_id=ids.task_id,
            assignment_id=ids.child_assignment_id,
            attempt_id=ids.child_attempt_id,
            outcome="blocked",
            checkpoint_id=ids.child_checkpoint_id,
            successor_dispatch_id=None,
            committed_at=FIXTURE_TIMESTAMP,
        )
    )
    await session.commit()


def _default_provider_settings() -> Settings:
    return Settings(
        runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
        codex=CodexSettings(enabled=True),
    )


__all__ = [
    "AsyncSessionFactory",
    "SessionFactory",
    "make_seed_child_terminal",
    "seeded_async_executor",
    "seeded_executor",
    "seeded_task_root",
    "seeded_task_workspace",
    "synchronized_transition_claims",
]
