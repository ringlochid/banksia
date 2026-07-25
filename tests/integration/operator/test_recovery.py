from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select

from banksia.operator.contracts import (
    OperatorMessageRequest,
    OperatorProviderMessageResult,
)
from banksia.operator.errors import OperatorServiceError
from banksia.operator.operations import OperatorOperationExecutor, OperatorOperationScope
from banksia.operator.operations.executor import OperatorToolResult
from banksia.operator.provider import (
    OperatorProviderAvailability,
    OperatorProviderError,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.service import OperatorServices, create_operator_services
from banksia.persistence.models import OperatorEffectModel, OperatorInvocationModel, TaskModel
from banksia.workflows.authoring import read_workflow_draft
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import (
    AsyncSessionFactory,
    initialized_workflow_database,
)


class MessageOperatorRunner:
    availability = OperatorProviderAvailability(
        availability="available",
        configured_provider="test",
        problem_code=None,
        explanation="The hermetic Operator provider is available.",
        setup_action=None,
        resolved_model="test-model",
        resolved_effort="high",
    )

    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del operations
        self.inputs.append(invocation.provider_input)
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The recovered provider turn completed.",
            ),
            provider_thread_id=invocation.provider_thread_id or "recovery-thread",
        )


class ThreadLostOperatorRunner:
    availability = MessageOperatorRunner.availability

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del invocation, operations
        raise OperatorProviderError(
            "thread_lost",
            is_retry_safe=False,
        )


class SimulatedProcessExit(BaseException):
    pass


class ImmediateEffectExitRunner:
    availability = MessageOperatorRunner.availability

    def __init__(self) -> None:
        self.tool_result: OperatorToolResult | None = None

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        self.tool_result = await operations.execute(
            scope=OperatorOperationScope(
                conversation_id=invocation.conversation_id,
                invocation_id=invocation.invocation_id,
                claim_generation=invocation.claim_generation,
            ),
            provider_call_id="call-create-draft",
            operation_name="workflow_draft_create",
            arguments={
                "request": {
                    "kind": "create",
                    "workflow_id": "operator-recovery-draft",
                    "description": "A draft committed before process loss.",
                }
            },
        )
        raise SimulatedProcessExit


class MismatchedThreadRunner:
    availability = MessageOperatorRunner.availability

    def __init__(self) -> None:
        self.calls = 0

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del operations
        self.calls += 1
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The provider returned a response.",
            ),
            provider_thread_id="thread-a" if self.calls == 1 else "thread-b",
        )


class EffectThenThreadLostRunner:
    availability = MessageOperatorRunner.availability

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        result = await operations.execute(
            scope=OperatorOperationScope(
                conversation_id=invocation.conversation_id,
                invocation_id=invocation.invocation_id,
                claim_generation=invocation.claim_generation,
            ),
            provider_call_id="call-before-thread-loss",
            operation_name="workflow_draft_create",
            arguments={
                "request": {
                    "kind": "create",
                    "workflow_id": "thread-loss-receipt",
                    "description": "This committed effect receipt must survive.",
                }
            },
        )
        assert result.kind == "result"
        raise OperatorProviderError("thread_lost", is_retry_safe=False)


class RetryProposalRunner:
    availability = MessageOperatorRunner.availability

    def __init__(self) -> None:
        self.calls = 0

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        self.calls += 1
        proposal = await operations.execute(
            scope=OperatorOperationScope(
                conversation_id=invocation.conversation_id,
                invocation_id=invocation.invocation_id,
                claim_generation=invocation.claim_generation,
            ),
            provider_call_id="task-start-proposal",
            operation_name="task_start",
            arguments={
                "workflow": "reviewed-delivery",
                "prompt": "Start only the currently confirmed retry proposal.",
            },
        )
        assert proposal.kind == "proposal"
        if self.calls == 1:
            raise OperatorProviderError("transient", is_retry_safe=True)
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The replacement proposal is ready.",
            ),
            provider_thread_id="retry-proposal-thread",
        )


class CountingMessageRunner:
    availability = MessageOperatorRunner.availability

    def __init__(self) -> None:
        self.invocation_ids: list[str] = []

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del operations
        self.invocation_ids.append(invocation.invocation_id)
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The supervised turn completed.",
            ),
            provider_thread_id=f"thread-{invocation.conversation_id}",
        )


class CountingFailureRunner:
    availability = MessageOperatorRunner.availability

    def __init__(self) -> None:
        self.invocation_ids: list[str] = []

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del operations
        self.invocation_ids.append(invocation.invocation_id)
        raise OperatorProviderError("transient", is_retry_safe=True)


async def test_startup_republishes_queued_only_when_provider_is_available(
    tmp_path: Path,
) -> None:
    initial_runner = MessageOperatorRunner()
    recovered_runner = MessageOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        initial = _services(tmp_path, session_factory, initial_runner)
        created = await initial.conversations.create_conversation(idempotency_key="create")
        await initial.conversations.submit_message(
            conversation_id=created.id,
            request=OperatorMessageRequest(text="This turn is durably queued."),
            idempotency_key="message",
        )

        unavailable = _services(tmp_path, session_factory, None)
        async with unavailable.coordinator:
            await unavailable.coordinator.drain()
            still_queued = await unavailable.conversations.read_conversation(created.id)
        assert still_queued.state == "running"

        recovered = _services(tmp_path, session_factory, recovered_runner)
        async with recovered.coordinator:
            await recovered.coordinator.drain()
            completed = await recovered.conversations.read_conversation(created.id)

    assert initial_runner.inputs == []
    assert recovered_runner.inputs == ["This turn is durably queued."]
    assert completed.state == "ready"


async def test_provider_thread_loss_is_terminal_and_exposes_only_new_conversation(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, ThreadLostOperatorRunner())
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Continue the exact provider thread."),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            failed = await services.conversations.read_conversation(created.id)

    assert failed.state == "provider_thread_lost"
    assert [action.kind for action in failed.legal_actions] == ["create_new_conversation"]
    assert failed.entries[-1].kind == "recoverable_error"
    assert failed.entries[-1].problem == "thread_lost"
    assert "provider_thread_id" not in failed.model_dump_json()


async def test_restart_never_replays_a_provider_turn_after_an_effect_boundary(
    tmp_path: Path,
) -> None:
    exiting_runner = ImmediateEffectExitRunner()
    replacement_runner = MessageOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        initial = _services(tmp_path, session_factory, exiting_runner)
        created = await initial.conversations.create_conversation(idempotency_key="create")
        await initial.conversations.submit_message(
            conversation_id=created.id,
            request=OperatorMessageRequest(text="Create the recovery draft."),
            idempotency_key="message",
        )
        async with session_factory() as session:
            invocation_id = await session.scalar(
                select(OperatorInvocationModel.invocation_id).where(
                    OperatorInvocationModel.conversation_id == created.id
                )
            )
        assert invocation_id is not None
        with pytest.raises(SimulatedProcessExit):
            await initial.coordinator.execute_provider_invocation(invocation_id)
        assert exiting_runner.tool_result is not None
        assert exiting_runner.tool_result.kind == "result"
        result = exiting_runner.tool_result.result
        assert result is not None
        draft_payload = cast(dict[str, object], result["draft"])
        draft_id = cast(str, draft_payload["draft_id"])

        restarted = _services(tmp_path, session_factory, replacement_runner)
        async with restarted.coordinator:
            await restarted.coordinator.drain()
            recovered = await restarted.conversations.read_conversation(created.id)
        async with session_factory() as session:
            invocation = await session.get(OperatorInvocationModel, invocation_id)
            draft = await read_workflow_draft(
                session,
                draft_id=draft_id,
            )

    assert replacement_runner.inputs == []
    assert recovered.state == "ready"
    assert [entry.kind for entry in recovered.entries] == [
        "user_message",
        "effect_receipt",
    ]
    assert [action.kind for action in recovered.legal_actions] == ["send_message"]
    assert invocation is not None
    assert invocation.state == "failed"
    assert invocation.is_retry_safe is False
    assert draft.workflow.id == "operator-recovery-draft"


async def test_returned_thread_mismatch_is_terminal_without_silent_fork(
    tmp_path: Path,
) -> None:
    runner = MismatchedThreadRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Create the durable thread."),
                idempotency_key="message-1",
            )
            await services.coordinator.drain()
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Continue only that thread."),
                idempotency_key="message-2",
            )
            await services.coordinator.drain()
            current = await services.conversations.read_conversation(created.id)

    assert runner.calls == 2
    assert current.state == "provider_thread_lost"
    assert current.entries[-1].kind == "recoverable_error"
    assert [action.kind for action in current.legal_actions] == ["create_new_conversation"]


async def test_explicit_thread_loss_after_effect_preserves_receipt_and_disables_thread(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, EffectThenThreadLostRunner())
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(
                    text="Commit the effect, then report the lost thread."
                ),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            current = await services.conversations.read_conversation(created.id)

    assert current.state == "provider_thread_lost"
    assert [entry.kind for entry in current.entries] == [
        "user_message",
        "effect_receipt",
        "recoverable_error",
    ]
    assert [action.kind for action in current.legal_actions] == ["create_new_conversation"]


async def test_retry_expires_prior_proposals_and_only_replacement_can_start_task(
    tmp_path: Path,
) -> None:
    runner = RetryProposalRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        created = await services.conversations.create_conversation(idempotency_key="create")
        await services.conversations.submit_message(
            conversation_id=created.id,
            request=OperatorMessageRequest(text="Prepare the run-start proposal."),
            idempotency_key="message",
        )
        async with session_factory() as session:
            first_invocation_id = await session.scalar(
                select(OperatorInvocationModel.invocation_id).where(
                    OperatorInvocationModel.conversation_id == created.id
                )
            )
        assert first_invocation_id is not None
        await services.coordinator.execute_provider_invocation(first_invocation_id)
        async with session_factory() as session:
            first_effect = await session.scalar(
                select(OperatorEffectModel).where(
                    OperatorEffectModel.invocation_id == first_invocation_id
                )
            )
        assert first_effect is not None and first_effect.confirmation_id is not None

        await services.conversations.retry_provider_invocation(
            conversation_id=created.id,
            idempotency_key="retry",
        )
        async with session_factory() as session:
            retry_invocation_id = await session.scalar(
                select(OperatorInvocationModel.invocation_id).where(
                    OperatorInvocationModel.retry_basis_invocation_id == first_invocation_id
                )
            )
        assert retry_invocation_id is not None
        await services.coordinator.execute_provider_invocation(retry_invocation_id)
        current = await services.conversations.read_conversation(created.id)
        replacement = next(
            action for action in current.legal_actions if action.kind == "confirm_effect"
        )

        with pytest.raises(OperatorServiceError) as stale:
            await services.conversations.confirm_effect(
                conversation_id=created.id,
                confirmation_id=first_effect.confirmation_id,
                idempotency_key="confirm-old",
            )
        await services.conversations.confirm_effect(
            conversation_id=created.id,
            confirmation_id=replacement.confirmation_id,
            idempotency_key="confirm-new",
        )

        async with session_factory() as session:
            live_proposals = await session.scalar(
                select(func.count())
                .select_from(OperatorEffectModel)
                .where(
                    OperatorEffectModel.conversation_id == created.id,
                    OperatorEffectModel.state == "proposed",
                    OperatorEffectModel.confirmation_state == "available",
                )
            )
            task_count = await session.scalar(select(func.count()).select_from(TaskModel))
            expired = await session.get(OperatorEffectModel, first_effect.effect_id)

    assert stale.value.response.problem.code == "operator_action_not_current"
    assert expired is not None and expired.confirmation_state == "expired"
    assert live_proposals == 0
    assert task_count == 1


@pytest.mark.parametrize("stage", ["claim", "completion", "failure"])
async def test_one_time_persistence_failure_does_not_kill_worker_or_strand_next_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    runner: CountingMessageRunner | CountingFailureRunner = (
        CountingFailureRunner() if stage == "failure" else CountingMessageRunner()
    )
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        calls = 0

        if stage == "claim":
            original_claim = services.invocations.claim_provider_invocation

            async def fail_once_then_claim(
                invocation_id: str,
            ) -> OperatorProviderInvocation | None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("one-time claim persistence injection")
                return await original_claim(invocation_id)

            monkeypatch.setattr(
                services.invocations,
                "claim_provider_invocation",
                fail_once_then_claim,
            )
        elif stage == "completion":
            original_complete = services.invocations.complete_provider_invocation

            async def fail_once_then_complete(
                invocation: OperatorProviderInvocation,
                outcome: OperatorProviderOutcome,
            ) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("one-time completion persistence injection")
                await original_complete(invocation, outcome)

            monkeypatch.setattr(
                services.invocations,
                "complete_provider_invocation",
                fail_once_then_complete,
            )
        else:
            original_failure = services.invocations.fail_provider_invocation

            async def fail_once_then_fail(
                invocation: OperatorProviderInvocation,
                failure: OperatorProviderError,
            ) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("one-time failure persistence injection")
                await original_failure(invocation, failure)

            monkeypatch.setattr(
                services.invocations,
                "fail_provider_invocation",
                fail_once_then_fail,
            )

        async with services.coordinator:
            conversation_ids: list[str] = []
            for index in range(2):
                created = await services.conversations.create_conversation(
                    idempotency_key=f"create-{index}"
                )
                conversation_ids.append(created.id)
                await services.conversations.submit_message(
                    conversation_id=created.id,
                    request=OperatorMessageRequest(text=f"Run supervised turn {index}."),
                    idempotency_key=f"message-{index}",
                )
            await services.coordinator.drain()
            views = [
                await services.conversations.read_conversation(conversation_id)
                for conversation_id in conversation_ids
            ]

    assert calls == 3
    assert len(runner.invocation_ids) == len(set(runner.invocation_ids)) == 2
    expected_state = "failed" if stage == "failure" else "ready"
    assert [view.state for view in views] == [expected_state, expected_state]


async def test_publish_rejects_a_coordinator_that_has_already_stopped(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, MessageOperatorRunner())
        async with services.coordinator:
            pass
        with pytest.raises(RuntimeError, match="worker is unavailable"):
            await services.coordinator.publish("invocation-after-shutdown")


def _services(
    tmp_path: Path,
    session_factory: AsyncSessionFactory,
    runner: (
        MessageOperatorRunner
        | ThreadLostOperatorRunner
        | ImmediateEffectExitRunner
        | MismatchedThreadRunner
        | EffectThenThreadLostRunner
        | RetryProposalRunner
        | CountingMessageRunner
        | CountingFailureRunner
        | None
    ),
) -> OperatorServices:
    dependencies = product_dispatch_dependencies(tmp_path)
    return create_operator_services(
        session_factory=session_factory,
        settings=dependencies.settings,
        dispatch_dependencies=dependencies,
        runtime_effect_publisher=None,
        provider_runner=runner,
    )
