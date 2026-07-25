from __future__ import annotations

from pathlib import Path

from banksia.operator.contracts import (
    OperatorConversationView,
    OperatorMessageRequest,
    OperatorProviderMessageResult,
)
from banksia.operator.operations import OperatorOperationExecutor
from banksia.operator.provider import (
    OperatorProviderAvailability,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.service import create_operator_services
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import initialized_workflow_database

_AVAILABLE = OperatorProviderAvailability(
    availability="available",
    configured_provider="test",
    problem_code=None,
    explanation="The hermetic Operator provider is available.",
    setup_action=None,
    resolved_model="test-model",
    resolved_effort="high",
)


class RawExceptionRunner:
    availability = _AVAILABLE

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del invocation, operations
        raise RuntimeError("SDK transport failed with api_key=raw-secret and private stack detail")


class MissingThreadRunner:
    availability = _AVAILABLE

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del invocation, operations
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="This result omitted the durable thread identity.",
            )
        )


async def test_raw_provider_exception_text_is_never_persisted_or_exposed(
    tmp_path: Path,
) -> None:
    current = await _run_one_turn(tmp_path, RawExceptionRunner())

    assert current.state == "failed"
    error = current.entries[-1]
    assert error.kind == "recoverable_error"
    assert error.problem == "internal_protocol"
    assert error.explanation == "The Operator provider turn failed safely."
    assert "raw-secret" not in current.model_dump_json()
    assert "stack detail" not in current.model_dump_json()


async def test_missing_returned_thread_identity_is_terminal_thread_loss(
    tmp_path: Path,
) -> None:
    current = await _run_one_turn(tmp_path, MissingThreadRunner())

    assert current.state == "provider_thread_lost"
    assert [entry.kind for entry in current.entries] == [
        "user_message",
        "recoverable_error",
    ]
    assert [action.kind for action in current.legal_actions] == ["create_new_conversation"]


async def _run_one_turn(
    tmp_path: Path,
    runner: RawExceptionRunner | MissingThreadRunner,
) -> OperatorConversationView:
    async with initialized_workflow_database(tmp_path) as session_factory:
        dependencies = product_dispatch_dependencies(tmp_path)
        services = create_operator_services(
            session_factory=session_factory,
            settings=dependencies.settings,
            dispatch_dependencies=dependencies,
            runtime_effect_publisher=None,
            provider_runner=runner,
        )
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Run the provider safety boundary."),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            return await services.conversations.read_conversation(created.id)
