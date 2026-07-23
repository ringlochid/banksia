from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Collection
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import banksia.runtime.node_operations.executor as executor_module
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence import RuntimeBase
from banksia.providers import ProviderKind
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeActivitySignal, NodeOperationExecutor
from banksia.runtime.node_operations.follow_on import SupportProjectionPublisher
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.post_commit.publisher import RuntimeEffectPublisher
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    RuntimeIds,
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)

type SessionFactory = Callable[[], SyncSessionAdapter]


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
    workspace = seeded_task_workspace(tmp_path, suffix)
    task_root = seeded_task_root(tmp_path, suffix)
    for path in (
        task_root / "notes",
        task_root / "artifacts",
        task_root / "command-runs",
    ):
        path.mkdir(parents=True, exist_ok=True)
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


def seeded_task_workspace(tmp_path: Path, suffix: str) -> Path:
    return tmp_path / f"task-{suffix}" / "workspace"


def seeded_task_root(tmp_path: Path, suffix: str) -> Path:
    return seeded_task_workspace(tmp_path, suffix) / ".banksia" / f"task.{suffix}"


def _default_provider_settings() -> Settings:
    return Settings(
        runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
        codex=CodexSettings(enabled=True),
    )


__all__ = [
    "SessionFactory",
    "seeded_executor",
    "seeded_task_root",
    "seeded_task_workspace",
    "synchronized_transition_claims",
]
