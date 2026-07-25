from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from banksia.operator.contracts import OperatorAvailability, OperatorProviderResult
from banksia.operator.operations import OperatorOperationExecutor

type OperatorProviderProblem = Literal[
    "configuration",
    "authentication",
    "unavailable",
    "rate_limited",
    "transient",
    "timeout",
    "refusal",
    "invalid_output",
    "thread_lost",
    "cancelled",
    "internal_protocol",
]
logger = logging.getLogger(__name__)

_PROVIDER_FAILURE_EXPLANATIONS: dict[OperatorProviderProblem, str] = {
    "configuration": "The Operator provider is not configured for this request.",
    "authentication": "The Operator provider could not authenticate.",
    "unavailable": "The Operator provider is temporarily unavailable.",
    "rate_limited": "The Operator provider is temporarily rate limited.",
    "transient": "The Operator provider turn failed temporarily.",
    "timeout": "The Operator provider turn timed out.",
    "refusal": "The Operator provider could not complete this request.",
    "invalid_output": "The Operator provider returned an invalid response.",
    "thread_lost": "The exact provider conversation is no longer available.",
    "cancelled": "The Operator provider turn was cancelled.",
    "internal_protocol": "The Operator provider turn failed safely.",
}


@dataclass(frozen=True, slots=True)
class OperatorProviderAvailability:
    availability: OperatorAvailability
    configured_provider: str | None
    problem_code: str | None
    explanation: str
    setup_action: str | None
    resolved_model: str | None = None
    resolved_effort: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorProviderInvocation:
    conversation_id: str
    invocation_id: str
    claim_generation: int
    provider_input: str
    provider_thread_id: str | None
    resolved_model: str | None
    resolved_effort: str | None


@dataclass(frozen=True, slots=True)
class OperatorProviderOutcome:
    result: OperatorProviderResult
    provider_thread_id: str | None = None
    provider_turn_reference: str | None = None


class OperatorProviderError(Exception):
    def __init__(
        self,
        problem: OperatorProviderProblem,
        *,
        is_retry_safe: bool,
    ) -> None:
        explanation = self.explanation_for(problem)
        super().__init__(explanation)
        self.problem = problem
        self.explanation = explanation
        self.is_retry_safe = is_retry_safe
        self.is_thread_lost = problem == "thread_lost"

    @staticmethod
    def explanation_for(problem: OperatorProviderProblem) -> str:
        return _PROVIDER_FAILURE_EXPLANATIONS[problem]


class OperatorProviderRunner(Protocol):
    @property
    def availability(self) -> OperatorProviderAvailability: ...

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome: ...


class UnavailableOperatorProviderRunner:
    def __init__(
        self,
        availability: OperatorProviderAvailability | None = None,
    ) -> None:
        self._availability = availability or OperatorProviderAvailability(
            availability="unconfigured",
            configured_provider=None,
            problem_code="operator_provider_unconfigured",
            explanation="Operator is not configured with a provider.",
            setup_action="Configure [operator] provider settings, then restart Banksia.",
        )

    @property
    def availability(self) -> OperatorProviderAvailability:
        return self._availability

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del invocation, operations
        raise OperatorProviderError(
            "configuration",
            is_retry_safe=False,
        )


class OperatorInvocationOwner(Protocol):
    async def claim_provider_invocation(
        self,
        invocation_id: str,
    ) -> OperatorProviderInvocation | None: ...

    async def complete_provider_invocation(
        self,
        invocation: OperatorProviderInvocation,
        outcome: OperatorProviderOutcome,
    ) -> None: ...

    async def fail_provider_invocation(
        self,
        invocation: OperatorProviderInvocation,
        failure: OperatorProviderError,
    ) -> None: ...

    async def recover_provider_startup(self) -> tuple[str, ...]: ...


class OperatorInvocationCoordinator:
    def __init__(
        self,
        *,
        runner: OperatorProviderRunner,
        operations: OperatorOperationExecutor,
    ) -> None:
        self._runner = runner
        self._operations = operations
        self._owner: OperatorInvocationOwner | None = None
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._was_started = False

    @property
    def availability(self) -> OperatorProviderAvailability:
        return self._runner.availability

    def bind_owner(self, owner: OperatorInvocationOwner) -> None:
        if self._owner is not None and self._owner is not owner:
            raise RuntimeError("Operator invocation owner is already bound")
        self._owner = owner

    async def __aenter__(self) -> OperatorInvocationCoordinator:
        owner = self._require_owner()
        self._was_started = True
        self._worker = asyncio.create_task(self._run_worker())
        queued = await owner.recover_provider_startup()
        if self.availability.availability == "available":
            for invocation_id in queued:
                await self.publish(invocation_id)
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback
        if self._worker is not None:
            await self._queue.put(None)
            await self._worker
            self._worker = None

    async def publish(self, invocation_id: str) -> None:
        if self._was_started and (self._worker is None or self._worker.done()):
            raise RuntimeError("Operator provider worker is unavailable")
        await self._queue.put(invocation_id)

    async def drain(self) -> None:
        await self._queue.join()

    async def execute_provider_invocation(self, invocation_id: str) -> None:
        owner = self._require_owner()
        invocation = await self._retry_persistence_call(
            owner.claim_provider_invocation,
            invocation_id,
        )
        if invocation is None:
            return
        try:
            outcome = await self._runner.invoke(invocation, self._operations)
        except OperatorProviderError as exc:
            await self._retry_persistence_call(
                owner.fail_provider_invocation,
                invocation,
                exc,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._retry_persistence_call(
                owner.fail_provider_invocation,
                invocation,
                OperatorProviderError(
                    "internal_protocol",
                    is_retry_safe=True,
                ),
            )
        else:
            await self._retry_persistence_call(
                owner.complete_provider_invocation,
                invocation,
                outcome,
            )

    async def _run_worker(self) -> None:
        while True:
            invocation_id = await self._queue.get()
            try:
                if invocation_id is None:
                    return
                try:
                    await self.execute_provider_invocation(invocation_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Operator provider work item failed without stopping the worker",
                        extra={"invocation_id": invocation_id},
                    )
            finally:
                self._queue.task_done()

    async def _retry_persistence_call[T](
        self,
        operation: Callable[..., Awaitable[T]],
        *arguments: object,
    ) -> T:
        for attempt in range(3):
            try:
                return await operation(*arguments)
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(0)
        raise AssertionError("Operator persistence retry loop did not return")

    def _require_owner(self) -> OperatorInvocationOwner:
        if self._owner is None:
            raise RuntimeError("Operator invocation owner is unavailable")
        return self._owner


__all__ = [
    "OperatorInvocationCoordinator",
    "OperatorInvocationOwner",
    "OperatorProviderAvailability",
    "OperatorProviderError",
    "OperatorProviderInvocation",
    "OperatorProviderOutcome",
    "OperatorProviderProblem",
    "OperatorProviderRunner",
    "UnavailableOperatorProviderRunner",
]
