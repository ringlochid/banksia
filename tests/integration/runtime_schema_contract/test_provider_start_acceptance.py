from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from pathlib import Path
from threading import Barrier
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence import RuntimeBase
from banksia.runtime.dispatch import (
    ProviderStartAcceptanceResult,
    accept_provider_start_if_current,
)
from tests.helpers.provider_start import (
    ACCEPTED_AT,
    PROVIDER_START_REVISION,
    START_DUE_AT,
    StartingDispatchDatabase,
    starting_dispatch_database,
)
from tests.helpers.sqlite_runtime import SyncSessionAdapter


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
            attempt_current_dispatch_id = connection.scalar(
                select(RuntimeBase.metadata.tables["attempts"].c.current_dispatch_id).where(
                    RuntimeBase.metadata.tables["attempts"].c.attempt_id
                    == database.ids.root_attempt_id
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
    assert attempt_current_dispatch_id == database.ids.current_dispatch_id


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
        _close_starting_dispatch(database)

        late_acceptance = await _accept_start(database)

        with database.engine.connect() as connection:
            dispatch = connection.execute(
                select(RuntimeBase.metadata.tables["dispatch_turns"]).where(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id
                    == database.ids.current_dispatch_id
                )
            ).one()
            attempt_current_dispatch_id = connection.scalar(
                select(RuntimeBase.metadata.tables["attempts"].c.current_dispatch_id).where(
                    RuntimeBase.metadata.tables["attempts"].c.attempt_id
                    == database.ids.root_attempt_id
                )
            )

    assert late_acceptance.is_accepted is False
    assert dispatch.status == "closed"
    assert dispatch.closed_reason == "boundary"
    assert dispatch.adapter_started_at is None
    assert attempt_current_dispatch_id is None


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


def _close_starting_dispatch(database: StartingDispatchDatabase) -> None:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    attempts = RuntimeBase.metadata.tables["attempts"]
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
            attempts.update()
            .where(attempts.c.attempt_id == database.ids.root_attempt_id)
            .values(current_dispatch_id=None)
        )
