from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import pytest
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.persistence import RuntimeBase
from autoclaw.runtime.post_commit import DispatchCleanupRequested
from autoclaw.runtime.providers import (
    DispatchStartRequest,
    ProviderAdapterRegistry,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStopOutcome,
)
from autoclaw.runtime.providers.cleanup import create_provider_dispatch_cleanup_handler
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
)
from tests.integration.runtime_schema_contract.test_provider_start_acceptance import (
    ACCEPTED_AT,
    StartingDispatchDatabase,
    starting_dispatch_database,
)


class _StopRecordingAdapter:
    kind = ProviderKind.CODEX

    def __init__(self) -> None:
        self.stop_calls: list[str] = []

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        del request
        raise AssertionError("cleanup must not start a provider")

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
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


@pytest.mark.parametrize(
    "closed_reason",
    ("paused", "cancelled", "control_failed", "task_terminal"),
)
async def test_cleanup_stops_only_committed_provider_stop_reasons(
    tmp_path: Path,
    closed_reason: str,
) -> None:
    with starting_dispatch_database(
        tmp_path,
        suffix=f"cleanup-stop-{closed_reason}",
    ) as database:
        _close_current_dispatch(database, closed_reason=closed_reason)
        adapter = _StopRecordingAdapter()
        handler = create_provider_dispatch_cleanup_handler(ProviderAdapterRegistry((adapter,)))

        async with SyncSessionAdapter(database.session_factory) as session:
            await handler(
                cast(AsyncSession, session),
                DispatchCleanupRequested(database.ids.current_dispatch_id),
            )

        assert adapter.stop_calls == [database.ids.current_dispatch_id]


@pytest.mark.parametrize(
    "closed_reason",
    ("boundary", "human_request_wait", "command_run_wait", "watchdog_superseded"),
)
async def test_cleanup_does_not_stop_legal_continuation_or_watchdog_handoff(
    tmp_path: Path,
    closed_reason: str,
) -> None:
    with starting_dispatch_database(
        tmp_path,
        suffix=f"cleanup-keep-{closed_reason}",
    ) as database:
        _close_current_dispatch(database, closed_reason=closed_reason)
        adapter = _StopRecordingAdapter()
        handler = create_provider_dispatch_cleanup_handler(ProviderAdapterRegistry((adapter,)))

        async with SyncSessionAdapter(database.session_factory) as session:
            await handler(
                cast(AsyncSession, session),
                DispatchCleanupRequested(database.ids.current_dispatch_id),
            )

        assert adapter.stop_calls == []


def _close_current_dispatch(
    database: StartingDispatchDatabase,
    *,
    closed_reason: str,
) -> None:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    flows = RuntimeBase.metadata.tables["flows"]
    dispatch_values: dict[str, object] = {
        "status": "closed",
        "closed_at": ACCEPTED_AT,
        "closed_reason": closed_reason,
        "next_provider_start_at": None,
        "provider_start_retry_kind": None,
    }
    if closed_reason == "watchdog_superseded":
        dispatch_values["adapter_started_at"] = ACCEPTED_AT
    with database.engine.begin() as connection:
        connection.execute(
            dispatches.update()
            .where(dispatches.c.dispatch_id == database.ids.current_dispatch_id)
            .values(**dispatch_values)
        )
        connection.execute(
            flows.update()
            .where(flows.c.flow_id == database.ids.flow_id)
            .values(current_dispatch_id=None)
        )
