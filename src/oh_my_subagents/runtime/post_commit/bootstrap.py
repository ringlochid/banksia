from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

import oh_my_subagents.runtime.post_commit.delegation_wave_startup as delegation_wave_startup
import oh_my_subagents.runtime.post_commit.dispatch_startup as dispatch_startup
import oh_my_subagents.runtime.post_commit.external_wait_startup as external_wait_startup
from oh_my_subagents.runtime.post_commit.signals import RuntimeEffectSignal
from oh_my_subagents.runtime.startup_audit import (
    StartupAuditPage,
    StartupAuditRoutingError,
    audit_startup_source_family,
)

type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type RuntimeEffectStartupPublish = Callable[[RuntimeEffectSignal], Awaitable[bool]]
type RuntimeEffectPageFetcher = Callable[
    [str | None, int],
    Awaitable[StartupAuditPage[RuntimeEffectSignal, str]],
]
type RuntimeEffectFamily = tuple[str, RuntimeEffectPageFetcher]


@dataclass(frozen=True, slots=True)
class StartupRuntimeFamilyResult:
    """Discovered, routed, and deliberately deferred rows for one source family."""

    discovered_count: int
    routed_count: int
    deferred_count: int


async def audit_startup_runtime_effects(
    *,
    session_factory: AsyncSessionContextFactory,
    publish: RuntimeEffectStartupPublish,
    routed_signal_types: Collection[type[RuntimeEffectSignal]],
    watchdog_inactivity_timeout_seconds: int,
) -> dict[str, StartupRuntimeFamilyResult]:
    """Exhaust exact runtime pages and publish only routes with real handlers."""

    if watchdog_inactivity_timeout_seconds <= 0:
        raise ValueError("watchdog inactivity timeout must be positive")

    families = _startup_runtime_families(
        session_factory,
        watchdog_inactivity_timeout_seconds=watchdog_inactivity_timeout_seconds,
    )
    routable = frozenset(routed_signal_types)
    results: dict[str, StartupRuntimeFamilyResult] = {}
    for family_name, fetch_page in families:
        routed_count = 0
        deferred_count = 0

        async def route(signal: RuntimeEffectSignal) -> None:
            nonlocal routed_count, deferred_count
            if type(signal) not in routable:
                deferred_count += 1
                return
            if not await publish(signal):
                raise StartupAuditRoutingError(
                    f"startup audit could not publish {type(signal).__name__}"
                )
            routed_count += 1

        discovered_count = await audit_startup_source_family(
            family_name=family_name,
            fetch_page=fetch_page,
            route_source=route,
            cursor_advances=lambda previous, candidate: candidate > previous,
        )
        results[family_name] = StartupRuntimeFamilyResult(
            discovered_count=discovered_count,
            routed_count=routed_count,
            deferred_count=deferred_count,
        )
    return results


def _startup_runtime_families(
    session_factory: AsyncSessionContextFactory,
    *,
    watchdog_inactivity_timeout_seconds: int,
) -> tuple[RuntimeEffectFamily, ...]:
    return (
        *_continuation_runtime_families(session_factory),
        *_command_runtime_families(session_factory),
        *_resource_runtime_families(
            session_factory,
            watchdog_inactivity_timeout_seconds=watchdog_inactivity_timeout_seconds,
        ),
    )


def _continuation_runtime_families(
    session_factory: AsyncSessionContextFactory,
) -> tuple[RuntimeEffectFamily, ...]:
    return (
        (
            "runnable_task_start",
            lambda cursor, size: dispatch_startup.read_task_start_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "complete_delegation_wave",
            lambda cursor, size: delegation_wave_startup.read_wave_settlement_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "settled_delegation_wave",
            lambda cursor, size: delegation_wave_startup.read_wave_continuation_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "committed_replan",
            lambda cursor, size: dispatch_startup.read_replan_continuation_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "open_human_request",
            lambda cursor, size: external_wait_startup.read_human_deadline_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "terminal_human_request",
            lambda cursor, size: external_wait_startup.read_human_continuation_page(
                session_factory,
                cursor,
                size,
            ),
        ),
    )


def _command_runtime_families(
    session_factory: AsyncSessionContextFactory,
) -> tuple[RuntimeEffectFamily, ...]:
    return (
        (
            "terminal_command_run",
            lambda cursor, size: external_wait_startup.read_command_continuation_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "pending_command_run",
            lambda cursor, size: external_wait_startup.read_command_pending_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "running_command_run",
            lambda cursor, size: external_wait_startup.read_command_running_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "cancellation_requested_command_run",
            lambda cursor, size: external_wait_startup.read_command_cancellation_page(
                session_factory,
                cursor,
                size,
            ),
        ),
    )


def _resource_runtime_families(
    session_factory: AsyncSessionContextFactory,
    *,
    watchdog_inactivity_timeout_seconds: int,
) -> tuple[RuntimeEffectFamily, ...]:
    return (
        (
            "current_starting_dispatch",
            lambda cursor, size: dispatch_startup.read_dispatch_start_page(
                session_factory,
                cursor,
                size,
            ),
        ),
        (
            "current_open_watchdog",
            lambda cursor, size: dispatch_startup.read_watchdog_deadline_page(
                session_factory,
                cursor,
                size,
                inactivity_timeout_seconds=watchdog_inactivity_timeout_seconds,
            ),
        ),
    )


__all__ = [
    "StartupRuntimeFamilyResult",
    "audit_startup_runtime_effects",
]
