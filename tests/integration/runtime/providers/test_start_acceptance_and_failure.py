from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from oh_my_subagents.persistence import RuntimeBase
from oh_my_subagents.runtime.post_commit import DispatchStartDue, WatchdogDeadlineChanged
from oh_my_subagents.runtime.providers import (
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
)
from tests.helpers.provider_start import (
    ACCEPTED_AT,
    PROVIDER_START_REVISION,
    RecordingAdapter,
    create_dispatch_starter,
    dispatch_start_signal,
    handle_dispatch_start,
    prepare_dispatch_workspace,
    read_attempt_current_dispatch_id,
    read_dispatch_request_text,
    read_dispatch_row,
    read_task_row,
    starting_dispatch_database,
)


async def test_accepted_start_opens_once_retains_binding_and_publishes_watchdog(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-accepted") as database:
        prepare_dispatch_workspace(database, tmp_path)
        adapter = RecordingAdapter()
        starter, registry, scheduler, publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await handle_dispatch_start(database, starter, dispatch_start_signal(database))

        dispatch = read_dispatch_row(database)
        request = adapter.requests[0]
        assert dispatch.status == "open"
        assert dispatch.provider_start_attempt_count == 4
        assert (request.instructions, request.input) == read_dispatch_request_text(database)
        assert request.working_directory == (tmp_path / f"workspace-{database.ids.suffix}")
        assert request.managed_node_mcp is not None
        assert request.managed_node_mcp.enabled_tools == ("get_current_context",)
        credential = request.managed_node_mcp.bearer_token.get_secret_value()
        assert registry.authenticate(credential) is not None
        assert scheduler.registered == []
        assert publisher.signals == (
            WatchdogDeadlineChanged(
                dispatch_id=database.ids.current_dispatch_id,
                activity_revision=0,
                due_at=ACCEPTED_AT + timedelta(minutes=45),
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
        prepare_dispatch_workspace(database, tmp_path)
        adapter = RecordingAdapter(
            failure=ProviderStartError(
                kind=failure_kind,
                code=ProviderStartErrorCode.CONNECTION,
            )
        )
        starter, registry, scheduler, _publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await handle_dispatch_start(database, starter, dispatch_start_signal(database))

        dispatch = read_dispatch_row(database)
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
        retry_signal = scheduler.registered[0]
        adapter.failure = None
        retry_starter, _registry, _retry_scheduler, _retry_publisher = create_dispatch_starter(
            database,
            adapter,
            now=retry_signal.due_at,
        )
        await handle_dispatch_start(database, retry_starter, retry_signal)

        assert [request.dispatch_id for request in adapter.requests] == [
            database.ids.current_dispatch_id,
            database.ids.current_dispatch_id,
        ]
        assert {(request.instructions, request.input) for request in adapter.requests} == {
            read_dispatch_request_text(database)
        }
        assert not (
            tmp_path / f"task-root-{database.ids.suffix}" / "_runtime" / "dispatch"
        ).exists()


async def test_missing_dispatch_request_pauses_without_provider_io(tmp_path: Path) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-missing-request") as database:
        prepare_dispatch_workspace(database, tmp_path)
        with database.engine.begin() as connection:
            requests = RuntimeBase.metadata.tables["dispatch_requests"]
            connection.execute(
                requests.delete().where(requests.c.dispatch_id == database.ids.current_dispatch_id)
            )
        adapter = RecordingAdapter()
        starter, _registry, _scheduler, publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await handle_dispatch_start(database, starter, dispatch_start_signal(database))

        dispatch = read_dispatch_row(database)
        task = read_task_row(database)
        assert adapter.requests == []
        assert dispatch.status == "closed"
        assert dispatch.closed_reason == "control_failed"
        assert task.status == "paused"
        assert read_attempt_current_dispatch_id(database) is None
        assert task.pause_reason == "runtime_transition_failed"
        assert publisher.signals == ()


async def test_missing_capability_snapshot_pauses_without_provider_io(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-illegal-configuration") as database:
        prepare_dispatch_workspace(database, tmp_path)
        capabilities = RuntimeBase.metadata.tables["dispatch_capability_sets"]
        with database.engine.begin() as connection:
            connection.execute(
                capabilities.delete().where(
                    capabilities.c.dispatch_id == database.ids.current_dispatch_id
                )
            )
        adapter = RecordingAdapter()
        starter, _registry, scheduler, publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await handle_dispatch_start(database, starter, dispatch_start_signal(database))

        dispatch = read_dispatch_row(database)
        task = read_task_row(database)
        assert adapter.requests == []
        assert adapter.stop_calls == []
        assert dispatch.status == "closed"
        assert dispatch.closed_reason == "control_failed"
        assert task.status == "paused"
        assert task.pause_details["failure_code"] == "dispatch_start_request_invalid"
        assert scheduler.registered == []
        assert publisher.signals == ()


async def test_missing_committed_provider_adapter_pauses_before_binding_or_io(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-missing-adapter") as database:
        prepare_dispatch_workspace(database, tmp_path)
        starter, registry, scheduler, publisher = create_dispatch_starter(
            database,
            None,
            now=ACCEPTED_AT,
        )

        await handle_dispatch_start(database, starter, dispatch_start_signal(database))

        dispatch = read_dispatch_row(database)
        task = read_task_row(database)
        assert dispatch.status == "closed"
        assert dispatch.closed_reason == "control_failed"
        assert task.status == "paused"
        assert task.pause_details["failure_code"] == "dispatch_provider_adapter_missing"
        assert registry.revoke_all() == 0
        assert scheduler.registered == []
        assert publisher.signals == ()


async def test_early_node_close_is_acceptance_loser_with_stop_and_no_retry(
    tmp_path: Path,
) -> None:
    with starting_dispatch_database(tmp_path, suffix="starter-early-close") as database:
        prepare_dispatch_workspace(database, tmp_path)

        def close_before_acceptance() -> None:
            dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
            attempts = RuntimeBase.metadata.tables["attempts"]
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
                    attempts.update()
                    .where(attempts.c.attempt_id == database.ids.root_attempt_id)
                    .values(current_dispatch_id=None)
                )

        adapter = RecordingAdapter(on_start=close_before_acceptance)
        starter, registry, scheduler, publisher = create_dispatch_starter(
            database,
            adapter,
            now=ACCEPTED_AT,
        )

        await handle_dispatch_start(database, starter, dispatch_start_signal(database))

        dispatch = read_dispatch_row(database)
        assert dispatch.status == "closed"
        assert dispatch.provider_start_revision == PROVIDER_START_REVISION
        assert adapter.stop_calls == [database.ids.current_dispatch_id]
        assert scheduler.registered == []
        assert publisher.signals == ()
        request = adapter.requests[0]
        assert request.managed_node_mcp is not None
        credential = request.managed_node_mcp.bearer_token.get_secret_value()
        assert registry.authenticate(credential) is None


__all__ = []
