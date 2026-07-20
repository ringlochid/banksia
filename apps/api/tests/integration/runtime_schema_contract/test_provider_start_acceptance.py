from __future__ import annotations

import asyncio
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import cast

from autoclaw.persistence import RuntimeBase
from autoclaw.runtime.dispatch import (
    ProviderStartAcceptanceResult,
    accept_provider_start_if_current,
)
from autoclaw.runtime.dispatch.authority import read_node_operation_authority
from autoclaw.runtime.node_operations.contracts import NodeOperationScope
from autoclaw.runtime.node_operations.source_transitions import close_source_dispatch
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    RuntimeIds,
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)

START_DUE_AT = datetime(2026, 7, 18, 1, tzinfo=UTC)
ACCEPTED_AT = START_DUE_AT + timedelta(seconds=3)
PROVIDER_START_REVISION = 7

type SyncSessionFactory = sessionmaker[Session]


@dataclass(frozen=True)
class StartingDispatchDatabase:
    engine: Engine
    session_factory: SyncSessionFactory
    ids: RuntimeIds


async def test_exact_current_provider_acceptance_opens_once_and_clears_retry_state(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="winner") as database:
        winner = await _accept_start(database)
        repeated = await _accept_start(database)

        with database.engine.connect() as connection:
            dispatch = connection.execute(
                select(RuntimeBase.metadata.tables["dispatch_turns"]).where(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id
                    == database.ids.current_dispatch_id
                )
            ).one()
            flow_current_dispatch_id = connection.scalar(
                select(RuntimeBase.metadata.tables["flows"].c.current_dispatch_id).where(
                    RuntimeBase.metadata.tables["flows"].c.flow_id == database.ids.flow_id
                )
            )

    assert winner == ProviderStartAcceptanceResult(
        task_id=database.ids.task_id,
        dispatch_id=database.ids.current_dispatch_id,
        provider_start_revision=PROVIDER_START_REVISION,
        is_accepted=True,
        provider_start_attempt_count=4,
        adapter_started_at=ACCEPTED_AT,
        node_activity_revision=0,
        last_node_activity_at=None,
    )
    assert repeated.is_accepted is False
    assert dispatch.status == "open"
    assert dispatch.adapter_started_at.replace(tzinfo=UTC) == ACCEPTED_AT
    assert dispatch.provider_start_attempt_count == 4
    assert dispatch.next_provider_start_at is None
    assert dispatch.provider_start_retry_kind is None
    assert dispatch.provider_start_last_error_code is None
    assert flow_current_dispatch_id == database.ids.current_dispatch_id


async def test_wrong_task_and_stale_provider_start_revision_are_noop_losers(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="stale") as database:
        wrong_task = await _accept_start(database, task_id="task.wrong")
        stale_revision = await _accept_start(
            database,
            expected_provider_start_revision=PROVIDER_START_REVISION - 1,
        )

        with database.engine.connect() as connection:
            dispatch = connection.execute(
                select(RuntimeBase.metadata.tables["dispatch_turns"]).where(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id
                    == database.ids.current_dispatch_id
                )
            ).one()

    assert wrong_task.is_accepted is False
    assert stale_revision.is_accepted is False
    assert dispatch.status == "starting"
    assert dispatch.adapter_started_at is None
    assert dispatch.next_provider_start_at.replace(tzinfo=UTC) == START_DUE_AT
    assert dispatch.provider_start_retry_kind == "uncertain_acceptance"
    assert dispatch.provider_start_last_error_code == "provider_timeout"


def test_concurrent_acceptance_writers_commit_one_winner(tmp_path: Path) -> None:
    with starting_dispatch_database(tmp_path, suffix="acceptance-race") as database:
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(
                executor.submit(_run_acceptance_writer, database, barrier) for _ in range(2)
            )
            outcomes = tuple(future.result(timeout=10) for future in futures)

        with database.engine.connect() as connection:
            dispatch = connection.execute(
                select(RuntimeBase.metadata.tables["dispatch_turns"]).where(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id
                    == database.ids.current_dispatch_id
                )
            ).one()

    assert sorted(outcomes) == [False, True]
    assert dispatch.status == "open"
    assert dispatch.adapter_started_at is not None


async def test_boundary_close_before_late_acceptance_wins_without_reopen(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="boundary-wins") as database:
        async with SyncSessionAdapter(database.session_factory) as session:
            authority = await read_node_operation_authority(
                cast(AsyncSession, session),
                NodeOperationScope(
                    task_id=database.ids.task_id,
                    dispatch_id=database.ids.current_dispatch_id,
                ),
            )
            await close_source_dispatch(
                cast(AsyncSession, session),
                authority,
                now=ACCEPTED_AT - timedelta(seconds=1),
                closed_reason="boundary",
                waiting_cause="none",
                waiting_source_id=None,
            )
            await session.commit()

        late_acceptance = await _accept_start(database)

        with database.engine.connect() as connection:
            dispatch = connection.execute(
                select(RuntimeBase.metadata.tables["dispatch_turns"]).where(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id
                    == database.ids.current_dispatch_id
                )
            ).one()
            flow = connection.execute(
                select(RuntimeBase.metadata.tables["flows"]).where(
                    RuntimeBase.metadata.tables["flows"].c.flow_id == database.ids.flow_id
                )
            ).one()

    assert late_acceptance.is_accepted is False
    assert dispatch.status == "closed"
    assert dispatch.closed_reason == "boundary"
    assert dispatch.adapter_started_at is None
    assert flow.current_dispatch_id is None


def test_concurrent_successor_candidates_commit_one_current_dispatch(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="successor-race") as database:
        _close_starting_dispatch_for_successor_race(database)
        barrier = Barrier(2)
        candidate_ids = (
            "dispatch.successor-race.first",
            "dispatch.successor-race.second",
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(
                executor.submit(
                    _run_successor_writer,
                    database,
                    barrier,
                    candidate_dispatch_id,
                )
                for candidate_dispatch_id in candidate_ids
            )
            outcomes = tuple(future.result(timeout=10) for future in futures)

        dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
        flows = RuntimeBase.metadata.tables["flows"]
        with database.engine.connect() as connection:
            committed_candidates = tuple(
                connection.scalars(
                    select(dispatches.c.dispatch_id)
                    .where(dispatches.c.dispatch_id.in_(candidate_ids))
                    .order_by(dispatches.c.dispatch_id)
                )
            )
            flow_current_dispatch_id = connection.scalar(
                select(flows.c.current_dispatch_id).where(flows.c.flow_id == database.ids.flow_id)
            )
            successor_count = connection.scalar(
                select(func.count())
                .select_from(dispatches)
                .where(dispatches.c.predecessor_dispatch_id == database.ids.current_dispatch_id)
            )

    assert sorted(outcomes) == ["committed", "constraint_loser"]
    assert len(committed_candidates) == 1
    assert successor_count == 1
    assert flow_current_dispatch_id == committed_candidates[0]


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


async def _accept_start(
    database: StartingDispatchDatabase,
    *,
    task_id: str | None = None,
    expected_provider_start_revision: int = PROVIDER_START_REVISION,
) -> ProviderStartAcceptanceResult:
    async with SyncSessionAdapter(database.session_factory) as session:
        result = await accept_provider_start_if_current(
            cast(AsyncSession, session),
            task_id=task_id or database.ids.task_id,
            dispatch_id=database.ids.current_dispatch_id,
            expected_provider_start_revision=expected_provider_start_revision,
            expected_provider_start_attempt_count=3,
            expected_due_at=START_DUE_AT,
            accepted_at=ACCEPTED_AT,
        )
        await session.commit()
        return result


def _run_acceptance_writer(
    database: StartingDispatchDatabase,
    barrier: Barrier,
) -> bool:
    barrier.wait(timeout=5)
    return asyncio.run(_accept_start(database)).is_accepted


def _close_starting_dispatch_for_successor_race(
    database: StartingDispatchDatabase,
) -> None:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    flows = RuntimeBase.metadata.tables["flows"]
    with database.engine.begin() as connection:
        connection.execute(
            dispatches.update()
            .where(dispatches.c.dispatch_id == database.ids.current_dispatch_id)
            .values(
                status="closed",
                next_provider_start_at=None,
                provider_start_retry_kind=None,
                closed_at=ACCEPTED_AT,
                closed_reason="boundary",
            )
        )
        connection.execute(
            flows.update()
            .where(flows.c.flow_id == database.ids.flow_id)
            .values(current_dispatch_id=None)
        )


def _run_successor_writer(
    database: StartingDispatchDatabase,
    barrier: Barrier,
    candidate_dispatch_id: str,
) -> str:
    barrier.wait(timeout=5)
    try:
        with database.engine.begin() as connection:
            connection.execute(
                RuntimeBase.metadata.tables["dispatch_turns"].insert(),
                _starting_successor_row(database.ids, candidate_dispatch_id),
            )
            flows = RuntimeBase.metadata.tables["flows"]
            connection.execute(
                flows.update()
                .where(
                    flows.c.flow_id == database.ids.flow_id,
                    flows.c.current_dispatch_id.is_(None),
                )
                .values(current_dispatch_id=candidate_dispatch_id)
            )
        return "committed"
    except IntegrityError:
        return "constraint_loser"


def _starting_successor_row(
    ids: RuntimeIds,
    dispatch_id: str,
) -> dict[str, object]:
    return {
        "dispatch_id": dispatch_id,
        "task_id": ids.task_id,
        "flow_id": ids.flow_id,
        "assignment_id": ids.root_assignment_id,
        "attempt_id": ids.root_attempt_id,
        "node_key": "root",
        "flow_start_source_flow_id": None,
        "predecessor_dispatch_id": ids.current_dispatch_id,
        "status": "starting",
        "opened_reason": "boundary",
        "requested_provider": "codex",
        "resolved_provider": "codex",
        "provider_selection_basis": "default",
        "provider_route_kind": "codex",
        "model_override": None,
        "effort_override": None,
        "gateway_profile": None,
        "provider_start_revision": 0,
        "provider_start_attempt_count": 0,
        "next_provider_start_at": START_DUE_AT,
        "provider_start_retry_kind": "initial",
        "provider_start_last_error_code": None,
        "created_at": START_DUE_AT,
        "adapter_started_at": None,
        "last_node_activity_at": None,
        "node_activity_revision": 0,
        "closed_at": None,
        "closed_reason": None,
    }
