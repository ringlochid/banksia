from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence import RuntimeBase
from banksia.runtime.post_commit import DispatchStartDue, WatchdogDeadlineChanged
from tests.helpers.provider_start import (
    ACCEPTED_AT,
    PROVIDER_START_REVISION,
    START_DUE_AT,
    CommitThenRaiseSession,
    RecordingAdapter,
    create_dispatch_starter,
    dispatch_start_signal,
    handle_dispatch_start,
    prepare_dispatch_workspace,
    read_dispatch_row,
    starting_dispatch_database,
)


async def test_initial_watchdog_recovery_stops_predecessor_before_start_once(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-watchdog") as database:
        prepare_dispatch_workspace(database, tmp_path)
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
        adapter = RecordingAdapter(events=events)
        starter, registry, _scheduler, _publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )
        predecessor_id = database.ids.root_dispatch_id
        predecessor = registry.issue_binding(
            task_id=database.ids.task_id,
            dispatch_id=predecessor_id,
            provider_start_revision=0,
            exposure_ceiling=("get_current_context",),
        )

        await handle_dispatch_start(
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
        adapter = RecordingAdapter()
        starter, _registry, scheduler, _publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )
        future = DispatchStartDue(
            database.ids.current_dispatch_id,
            PROVIDER_START_REVISION + 100,
            ACCEPTED_AT + timedelta(hours=1),
        )

        await handle_dispatch_start(database, starter, future)
        await handle_dispatch_start(
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
        adapter = RecordingAdapter()
        starter, _registry, scheduler, publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )
        signal = dispatch_start_signal(database)
        starter.mark_recovered(signal)

        await handle_dispatch_start(database, starter, signal)

        dispatch = read_dispatch_row(database)
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
        prepare_dispatch_workspace(database, tmp_path)
        adapter = RecordingAdapter()
        starter, registry, scheduler, publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        async with CommitThenRaiseSession(database.session_factory) as session:
            await starter.schedule_or_start_dispatch(
                cast(AsyncSession, session),
                dispatch_start_signal(database),
            )

        dispatch = read_dispatch_row(database)
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
                due_at=ACCEPTED_AT + timedelta(minutes=45),
            ),
        )


__all__ = []
