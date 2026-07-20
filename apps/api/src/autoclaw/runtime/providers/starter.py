from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.config import RuntimeSettings
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.persistence.models import DispatchTurnModel
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.dispatch.provider_start import (
    ProviderStartAcceptanceResult,
    ProviderStartCandidate,
    accept_provider_start_if_current,
    provider_start_is_current,
    read_provider_start_acceptance_after_commit,
    read_provider_start_candidate,
    rotate_provider_start_after_failure,
)
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_mcp import DispatchMcpBinding, DispatchMcpBindingRegistry
from autoclaw.runtime.node_operations import NodeOperationExecutor
from autoclaw.runtime.post_commit import (
    AsyncSessionContextFactory,
    DeadlineScheduler,
    DispatchStartDue,
    RuntimeEffectPublisher,
    WatchdogDeadlineChanged,
)
from autoclaw.runtime.providers.contracts import (
    DEFAULT_PROVIDER_STOP_TIMEOUT_SECONDS,
    ProviderAdapter,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
)
from autoclaw.runtime.providers.registry import ProviderAdapterRegistry
from autoclaw.runtime.providers.request_preparation import (
    PreparedProviderStart,
    ProviderStartRequestBuilder,
)
from autoclaw.runtime.providers.transition_failure import pause_invalid_provider_start
from autoclaw.runtime.watchdog import calculate_watchdog_due_at

logger = logging.getLogger(__name__)


class DispatchStarter:
    """Schedule or start one exact provider generation without observing output."""

    def __init__(
        self,
        *,
        adapters: ProviderAdapterRegistry,
        binding_registry: DispatchMcpBindingRegistry,
        operation_executor: NodeOperationExecutor,
        scheduler: DeadlineScheduler,
        runtime_effect_publisher: RuntimeEffectPublisher,
        runtime_settings: RuntimeSettings,
        session_factory: AsyncSessionContextFactory,
        managed_node_mcp_url: str,
        compatibility_node_mcp_url: str,
        clock: Callable[[], datetime] = utc_now,
        stop_timeout_seconds: float = DEFAULT_PROVIDER_STOP_TIMEOUT_SECONDS,
    ) -> None:
        if stop_timeout_seconds <= 0:
            raise ValueError("provider stop timeout must be positive")
        self._adapters = adapters
        self._binding_registry = binding_registry
        self._request_builder = ProviderStartRequestBuilder(
            binding_registry=binding_registry,
            operation_executor=operation_executor,
            managed_node_mcp_url=managed_node_mcp_url,
            compatibility_node_mcp_url=compatibility_node_mcp_url,
        )
        self._scheduler = scheduler
        self._runtime_effect_publisher = runtime_effect_publisher
        self._runtime_settings = runtime_settings.model_copy(deep=True)
        self._session_factory = session_factory
        self._clock = clock
        self._stop_timeout_seconds = stop_timeout_seconds
        self._in_flight_dispatches: set[str] = set()
        self._recovered_start_signals: set[DispatchStartDue] = set()

    def mark_recovered(self, signal: DispatchStartDue) -> None:
        """Mark one startup-audit signal for conservative stop-and-retry."""
        self._recovered_start_signals.add(signal)

    async def schedule_or_start_dispatch(
        self,
        session: AsyncSession,
        signal: DispatchStartDue,
    ) -> None:
        """Schedule a future hint or process one due exact generation once."""
        if _as_utc(signal.due_at) > _as_utc(self._clock()):
            self._scheduler.register(signal)
            return
        if signal.dispatch_id in self._in_flight_dispatches:
            return

        self._in_flight_dispatches.add(signal.dispatch_id)
        try:
            if signal in self._recovered_start_signals:
                await self._handle_recovered_due(session, signal)
            else:
                await self._start_due_dispatch(session, signal)
        finally:
            self._in_flight_dispatches.discard(signal.dispatch_id)
            self._recovered_start_signals.discard(signal)

    async def _handle_recovered_due(
        self,
        session: AsyncSession,
        signal: DispatchStartDue,
    ) -> None:
        loaded = await self._read_candidate_and_adapter(session, signal)
        if loaded is None:
            return
        candidate, adapter = loaded

        if _is_initial_watchdog_recovery(candidate, signal):
            await self._stop_watchdog_predecessor(session, candidate)
        self._binding_registry.revoke_dispatch(signal.dispatch_id)
        await self._record_provider_failure(
            session,
            signal=signal,
            candidate=candidate,
            adapter=adapter,
            binding=None,
            failure_kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
            error_code=ProviderStartErrorCode.UNCERTAIN,
        )

    async def _start_due_dispatch(
        self,
        session: AsyncSession,
        signal: DispatchStartDue,
    ) -> None:
        loaded = await self._read_candidate_and_adapter(session, signal)
        if loaded is None:
            return
        candidate, adapter = loaded
        prepared = await self._prepare_request_or_pause(session, signal, candidate)
        if prepared is None:
            return

        if _is_initial_watchdog_recovery(candidate, signal):
            await self._stop_watchdog_predecessor(session, candidate)
        await self._invoke_provider_start(
            session,
            signal=signal,
            candidate=candidate,
            adapter=adapter,
            prepared=prepared,
        )

    async def _read_candidate_and_adapter(
        self,
        session: AsyncSession,
        signal: DispatchStartDue,
    ) -> tuple[ProviderStartCandidate, ProviderAdapter] | None:
        candidate = await read_provider_start_candidate(session, signal)
        await session.rollback()
        if candidate is None:
            return None

        if candidate.provider_kind is None:
            await pause_invalid_provider_start(
                session,
                signal=signal,
                candidate=candidate,
                failed_at=self._clock(),
                failure_code="dispatch_provider_route_invalid",
            )
            return None
        try:
            adapter = self._adapters.get(candidate.provider_kind)
        except LookupError:
            await pause_invalid_provider_start(
                session,
                signal=signal,
                candidate=candidate,
                failed_at=self._clock(),
                failure_code="dispatch_provider_adapter_missing",
            )
            return None
        return candidate, adapter

    async def _prepare_request_or_pause(
        self,
        session: AsyncSession,
        signal: DispatchStartDue,
        candidate: ProviderStartCandidate,
    ) -> PreparedProviderStart | None:
        try:
            return await self._request_builder.prepare_provider_start(
                session,
                signal,
                candidate,
            )
        except (
            RuntimeOperationError,
            ValidationError,
            UnicodeDecodeError,
            OSError,
            ValueError,
        ) as exc:
            await session.rollback()
            await pause_invalid_provider_start(
                session,
                signal=signal,
                candidate=candidate,
                failed_at=self._clock(),
                failure_code=_controller_failure_code(exc),
            )
            return None

    async def _invoke_provider_start(
        self,
        session: AsyncSession,
        *,
        signal: DispatchStartDue,
        candidate: ProviderStartCandidate,
        adapter: ProviderAdapter,
        prepared: PreparedProviderStart,
    ) -> None:
        if not await provider_start_is_current(
            session,
            signal=signal,
            candidate=candidate,
        ):
            self._revoke(prepared.binding)
            return

        try:
            await adapter.start(prepared.request)
        except asyncio.CancelledError:
            self._revoke(prepared.binding)
            await self._bounded_stop(adapter, signal.dispatch_id)
            raise
        except ProviderStartError as exc:
            await self._record_provider_failure(
                session,
                signal=signal,
                candidate=candidate,
                adapter=adapter,
                binding=prepared.binding,
                failure_kind=exc.kind,
                error_code=exc.code,
            )
            return
        except Exception:
            await self._record_provider_failure(
                session,
                signal=signal,
                candidate=candidate,
                adapter=adapter,
                binding=prepared.binding,
                failure_kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                error_code=ProviderStartErrorCode.UNCERTAIN,
            )
            return

        await self._record_acceptance(
            session,
            signal=signal,
            candidate=candidate,
            adapter=adapter,
            binding=prepared.binding,
        )

    async def _stop_watchdog_predecessor(
        self,
        session: AsyncSession,
        candidate: ProviderStartCandidate,
    ) -> None:
        predecessor_dispatch_id = candidate.predecessor_dispatch_id
        assert predecessor_dispatch_id is not None
        self._binding_registry.revoke_dispatch(predecessor_dispatch_id)
        predecessor_kind = await session.scalar(
            select(DispatchTurnModel.provider_route_kind).where(
                DispatchTurnModel.dispatch_id == predecessor_dispatch_id,
                DispatchTurnModel.task_id == candidate.task_id,
                DispatchTurnModel.flow_id == candidate.flow_id,
            )
        )
        await session.rollback()
        if predecessor_kind is None:
            return
        try:
            adapter = self._adapters.get(ProviderKind(predecessor_kind))
        except (LookupError, ValueError):
            return
        await self._bounded_stop(adapter, predecessor_dispatch_id)

    async def _record_acceptance(
        self,
        session: AsyncSession,
        *,
        signal: DispatchStartDue,
        candidate: ProviderStartCandidate,
        adapter: ProviderAdapter,
        binding: DispatchMcpBinding | None,
    ) -> None:
        accepted_at = self._clock()
        try:
            result = await accept_provider_start_if_current(
                session,
                task_id=candidate.task_id,
                dispatch_id=signal.dispatch_id,
                expected_provider_start_revision=signal.provider_start_revision,
                expected_provider_start_attempt_count=(candidate.provider_start_attempt_count),
                expected_due_at=candidate.persisted_due_at,
                accepted_at=accepted_at,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            async with self._session_factory() as reconciliation_session:
                reconciled = await read_provider_start_acceptance_after_commit(
                    reconciliation_session,
                    candidate=candidate,
                    signal=signal,
                )
                await reconciliation_session.rollback()
                if reconciled.is_accepted:
                    self._publish_watchdog(signal, reconciled)
                    return
                await self._record_provider_failure(
                    reconciliation_session,
                    signal=signal,
                    candidate=candidate,
                    adapter=adapter,
                    binding=binding,
                    failure_kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                    error_code=ProviderStartErrorCode.UNCERTAIN,
                )
            return

        if not result.is_accepted:
            self._revoke(binding)
            await self._bounded_stop(adapter, signal.dispatch_id)
            return

        self._publish_watchdog(signal, result)

    def _publish_watchdog(
        self,
        signal: DispatchStartDue,
        result: ProviderStartAcceptanceResult,
    ) -> None:
        assert result.adapter_started_at is not None
        assert result.node_activity_revision is not None
        due_at = calculate_watchdog_due_at(
            adapter_started_at=result.adapter_started_at,
            last_node_activity_at=result.last_node_activity_at,
            inactivity_timeout_seconds=(self._runtime_settings.watchdog_inactivity_timeout_seconds),
        )
        self._runtime_effect_publisher.publish(
            WatchdogDeadlineChanged(
                dispatch_id=signal.dispatch_id,
                activity_revision=result.node_activity_revision,
                due_at=due_at,
            )
        )

    async def _record_provider_failure(
        self,
        session: AsyncSession,
        *,
        signal: DispatchStartDue,
        candidate: ProviderStartCandidate,
        adapter: ProviderAdapter,
        binding: DispatchMcpBinding | None,
        failure_kind: ProviderStartFailureKind,
        error_code: ProviderStartErrorCode,
    ) -> None:
        retry = _next_retry_signal(
            signal,
            attempt_count=candidate.provider_start_attempt_count,
            now=self._clock(),
            settings=self._runtime_settings,
        )
        try:
            rotated = await rotate_provider_start_after_failure(
                session,
                signal=signal,
                candidate=candidate,
                retry=retry,
                failure_kind=failure_kind.value,
                error_code=error_code.value,
            )
        except Exception:
            await session.rollback()
            self._revoke(binding)
            if failure_kind is ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE:
                await self._bounded_stop(adapter, signal.dispatch_id)
            raise

        self._revoke(binding)
        if failure_kind is ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE:
            await self._bounded_stop(adapter, signal.dispatch_id)
        if rotated:
            self._scheduler.register(retry)

    def _revoke(self, binding: DispatchMcpBinding | None) -> None:
        if binding is not None:
            self._binding_registry.revoke_binding(binding)

    async def _bounded_stop(self, adapter: ProviderAdapter, dispatch_id: str) -> None:
        try:
            async with asyncio.timeout(self._stop_timeout_seconds):
                await adapter.stop(dispatch_id)
        except Exception as exc:
            logger.warning(
                "provider stop did not complete cleanly",
                extra={
                    "provider_kind": adapter.kind.value,
                    "dispatch_id": dispatch_id,
                    "exception_type": type(exc).__name__,
                },
            )


def _is_initial_watchdog_recovery(
    candidate: ProviderStartCandidate,
    signal: DispatchStartDue,
) -> bool:
    return (
        candidate.opened_reason == "watchdog_recovery"
        and candidate.predecessor_dispatch_id is not None
        and signal.provider_start_revision == 0
        and candidate.provider_start_attempt_count == 0
    )


def _next_retry_signal(
    signal: DispatchStartDue,
    *,
    attempt_count: int,
    now: datetime,
    settings: RuntimeSettings,
) -> DispatchStartDue:
    delay = min(
        settings.dispatch_launch_retry_max_backoff_seconds,
        settings.dispatch_launch_retry_initial_backoff_seconds * (2 ** min(attempt_count, 63)),
    )
    return DispatchStartDue(
        dispatch_id=signal.dispatch_id,
        provider_start_revision=signal.provider_start_revision + 1,
        due_at=_as_utc(now) + timedelta(seconds=delay),
    )


def _controller_failure_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    value = getattr(code, "value", None)
    if isinstance(value, str):
        return value
    return "dispatch_start_request_invalid"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "DEFAULT_PROVIDER_STOP_TIMEOUT_SECONDS",
    "DispatchStarter",
]
