from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

import banksia.operator.service as operator_service_module
from banksia.operator.contracts import (
    OperatorMessageRequest,
    OperatorProviderMessageResult,
)
from banksia.operator.errors import OperatorServiceError
from banksia.operator.operations import OperatorOperationExecutor
from banksia.operator.provider import (
    OperatorProviderAvailability,
    OperatorProviderError,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.service import OperatorServices, create_operator_services
from banksia.persistence.models import (
    OperatorConversationEntryModel,
    OperatorInvocationModel,
)
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_concurrency import (
    DatabaseBackend,
    TwoPartyBarrier,
    workflow_database,
)
from tests.helpers.workflow_runtime import (
    AsyncSessionFactory,
    initialized_workflow_database,
)

_AVAILABLE = OperatorProviderAvailability(
    availability="available",
    configured_provider="test",
    problem_code=None,
    explanation="The hermetic Operator provider is available.",
    setup_action=None,
    resolved_model="test-model",
    resolved_effort="high",
)


class RetryableFailureRunner:
    availability = _AVAILABLE

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del invocation, operations
        raise OperatorProviderError("transient", is_retry_safe=True)


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
async def test_same_retry_key_converges_to_one_real_invocation_without_lock_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: DatabaseBackend,
) -> None:
    async with workflow_database(tmp_path, backend=backend) as session_factory:
        services = _services(tmp_path, session_factory)
        conversation_id = await _create_failed_conversation(services, session_factory)
        barrier = TwoPartyBarrier()
        original = operator_service_module.store_operator_retry_invocation

        async def store_after_barrier(
            session_factory: AsyncSessionFactory,
            *,
            conversation_id: str,
            invocation_id: str,
            idempotency_key: str,
            digest: str,
        ) -> bool:
            await barrier.wait()
            return await original(
                session_factory,
                conversation_id=conversation_id,
                invocation_id=invocation_id,
                idempotency_key=idempotency_key,
                digest=digest,
            )

        monkeypatch.setattr(
            operator_service_module,
            "store_operator_retry_invocation",
            store_after_barrier,
        )
        outcomes = await asyncio.gather(
            services.conversations.retry_provider_invocation(
                conversation_id=conversation_id,
                idempotency_key="same-retry",
            ),
            services.conversations.retry_provider_invocation(
                conversation_id=conversation_id,
                idempotency_key="same-retry",
            ),
            return_exceptions=True,
        )
        async with session_factory() as session:
            invocation_count = await session.scalar(
                select(func.count())
                .select_from(OperatorInvocationModel)
                .where(OperatorInvocationModel.conversation_id == conversation_id)
            )
            active_count = await session.scalar(
                select(func.count())
                .select_from(OperatorInvocationModel)
                .where(
                    OperatorInvocationModel.conversation_id == conversation_id,
                    OperatorInvocationModel.state.in_(("queued", "running")),
                )
            )

    assert all(not isinstance(outcome, BaseException) for outcome in outcomes)
    assert invocation_count == 2
    assert active_count == 1


async def test_different_retry_keys_leave_one_winner_and_one_typed_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory)
        conversation_id = await _create_failed_conversation(services, session_factory)
        barrier = TwoPartyBarrier()
        original = operator_service_module.store_operator_retry_invocation

        async def store_after_barrier(
            session_factory: AsyncSessionFactory,
            *,
            conversation_id: str,
            invocation_id: str,
            idempotency_key: str,
            digest: str,
        ) -> bool:
            await barrier.wait()
            return await original(
                session_factory,
                conversation_id=conversation_id,
                invocation_id=invocation_id,
                idempotency_key=idempotency_key,
                digest=digest,
            )

        monkeypatch.setattr(
            operator_service_module,
            "store_operator_retry_invocation",
            store_after_barrier,
        )
        outcomes = await asyncio.gather(
            services.conversations.retry_provider_invocation(
                conversation_id=conversation_id,
                idempotency_key="retry-a",
            ),
            services.conversations.retry_provider_invocation(
                conversation_id=conversation_id,
                idempotency_key="retry-b",
            ),
            return_exceptions=True,
        )

    successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, OperatorServiceError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].response.problem.code == "operator_action_not_current"
    assert "locked" not in str(conflicts[0]).casefold()


async def test_duplicate_claim_completion_and_failure_are_single_winner_transitions(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory)
        completed_id, completed_invocation_id = await _queue_conversation(
            services,
            session_factory,
            suffix="completed",
        )
        completion_claims = await asyncio.gather(
            services.invocations.claim_provider_invocation(completed_invocation_id),
            services.invocations.claim_provider_invocation(completed_invocation_id),
        )
        claimed = next(item for item in completion_claims if item is not None)
        assert sum(item is not None for item in completion_claims) == 1
        outcome = OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="Persist this completion once.",
            ),
            provider_thread_id="concurrency-thread",
        )
        await asyncio.gather(
            services.invocations.complete_provider_invocation(claimed, outcome),
            services.invocations.complete_provider_invocation(claimed, outcome),
        )

        failed_id, failed_invocation_id = await _queue_conversation(
            services,
            session_factory,
            suffix="failed",
        )
        failure_claim = await services.invocations.claim_provider_invocation(failed_invocation_id)
        assert failure_claim is not None
        failure = OperatorProviderError("transient", is_retry_safe=True)
        await asyncio.gather(
            services.invocations.fail_provider_invocation(failure_claim, failure),
            services.invocations.fail_provider_invocation(failure_claim, failure),
        )

        async with session_factory() as session:
            completion_entries = await session.scalar(
                select(func.count())
                .select_from(OperatorConversationEntryModel)
                .where(
                    OperatorConversationEntryModel.conversation_id == completed_id,
                    OperatorConversationEntryModel.kind == "assistant_message",
                )
            )
            failure_entries = await session.scalar(
                select(func.count())
                .select_from(OperatorConversationEntryModel)
                .where(
                    OperatorConversationEntryModel.conversation_id == failed_id,
                    OperatorConversationEntryModel.kind == "recoverable_error",
                )
            )

    assert completion_entries == 1
    assert failure_entries == 1


async def test_repeated_duplicate_claims_return_exact_columns_and_one_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory)
        barrier = TwoPartyBarrier()
        original_claim = services.invocations._claim_provider_invocation

        async def claim_after_barrier(
            invocation_id: str,
        ) -> OperatorProviderInvocation | None:
            await barrier.wait()
            return await original_claim(invocation_id)

        monkeypatch.setattr(
            services.invocations,
            "_claim_provider_invocation",
            claim_after_barrier,
        )

        for iteration in range(12):
            barrier = TwoPartyBarrier()
            conversation_id, invocation_id = await _queue_conversation(
                services,
                session_factory,
                suffix=f"mapping-{iteration}",
            )
            claims = await asyncio.gather(
                services.invocations.claim_provider_invocation(invocation_id),
                services.invocations.claim_provider_invocation(invocation_id),
            )

            winners = [claim for claim in claims if claim is not None]
            assert len(winners) == 1
            winner = winners[0]
            assert winner.conversation_id == conversation_id
            assert winner.invocation_id == invocation_id
            assert winner.claim_generation == 1
            assert winner.provider_input == f"Queue the mapping-{iteration} turn."

        async with session_factory() as session:
            active_count = await session.scalar(
                select(func.count())
                .select_from(OperatorInvocationModel)
                .where(OperatorInvocationModel.state == "running")
            )

    assert active_count == 12


async def _create_failed_conversation(
    services: OperatorServices,
    session_factory: AsyncSessionFactory,
) -> str:
    conversation = await services.conversations.create_conversation(idempotency_key="create-failed")
    await services.conversations.submit_message(
        conversation_id=conversation.id,
        request=OperatorMessageRequest(text="Fail this turn safely."),
        idempotency_key="message-failed",
    )
    async with session_factory() as session:
        invocation_id = await session.scalar(
            select(OperatorInvocationModel.invocation_id).where(
                OperatorInvocationModel.conversation_id == conversation.id
            )
        )
    assert invocation_id is not None
    await services.coordinator.execute_provider_invocation(invocation_id)
    return conversation.id


async def _queue_conversation(
    services: OperatorServices,
    session_factory: AsyncSessionFactory,
    *,
    suffix: str,
) -> tuple[str, str]:
    conversation = await services.conversations.create_conversation(
        idempotency_key=f"create-{suffix}"
    )
    await services.conversations.submit_message(
        conversation_id=conversation.id,
        request=OperatorMessageRequest(text=f"Queue the {suffix} turn."),
        idempotency_key=f"message-{suffix}",
    )
    async with session_factory() as session:
        invocation_id = await session.scalar(
            select(OperatorInvocationModel.invocation_id).where(
                OperatorInvocationModel.conversation_id == conversation.id
            )
        )
    assert invocation_id is not None
    return conversation.id, invocation_id


def _services(
    tmp_path: Path,
    session_factory: AsyncSessionFactory,
) -> OperatorServices:
    dependencies = product_dispatch_dependencies(tmp_path)
    return create_operator_services(
        session_factory=session_factory,
        settings=dependencies.settings,
        dispatch_dependencies=dependencies,
        runtime_effect_publisher=None,
        provider_runner=RetryableFailureRunner(),
    )
