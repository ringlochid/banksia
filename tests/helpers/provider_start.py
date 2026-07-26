from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from banksia.persistence import RuntimeBase
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope
from tests.helpers.sqlite_runtime import create_runtime_schema_engine

START_DUE_AT = datetime(2026, 7, 18, 1, tzinfo=UTC)
ACCEPTED_AT = START_DUE_AT + timedelta(seconds=3)
PROVIDER_START_REVISION = 7

type _SyncSessionFactory = sessionmaker[Session]


@dataclass(frozen=True)
class StartingDispatchDatabase:
    engine: Engine
    session_factory: _SyncSessionFactory
    ids: RuntimeIds


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
    "StartingDispatchDatabase",
    "starting_dispatch_database",
]
