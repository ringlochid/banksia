from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from banksia.operator.contracts import (
    OperatorMessageRequest,
    OperatorProviderAskUserResult,
    OperatorProviderMessageResult,
    OperatorProviderQuestion,
    OperatorProviderQuestionOption,
    OperatorProviderResult,
    OperatorQuestionAnswersRequest,
    OperatorQuestionSetEntry,
)
from banksia.operator.errors import OperatorServiceError
from banksia.operator.operations import OperatorOperationExecutor, OperatorOperationScope
from banksia.operator.operations.executor import OperatorToolResult
from banksia.operator.provider import (
    OperatorProviderAvailability,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.service import OperatorServices, create_operator_services
from banksia.persistence.models import OperatorInvocationModel, TaskModel
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import (
    AsyncSessionFactory,
    initialized_workflow_database,
)


class ScriptedOperatorRunner:
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
        assert isinstance(invocation, OperatorProviderInvocation)
        self.inputs.append(invocation.provider_input)
        if invocation.provider_input.startswith("<operator_return"):
            result: OperatorProviderResult = OperatorProviderMessageResult(
                kind="message",
                text="The selected direction is recorded.",
            )
        else:
            result = OperatorProviderAskUserResult(
                kind="ask_user",
                explanation="Choose the practical direction.",
                questions=(
                    OperatorProviderQuestion(
                        header="Direction",
                        question="Which direction should the draft take?",
                        options=(
                            OperatorProviderQuestionOption(
                                label="Concise",
                                consequence="Keep the draft short.",
                            ),
                            OperatorProviderQuestionOption(
                                label="Detailed",
                                consequence="Add implementation detail.",
                            ),
                        ),
                    ),
                ),
            )
        return OperatorProviderOutcome(
            result=result,
            provider_thread_id="private-thread",
            provider_turn_reference="private-turn",
        )


class ProposalOperatorRunner:
    availability = ScriptedOperatorRunner.availability

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
            provider_call_id="call-task-start",
            operation_name="task_start",
            arguments={
                "workflow": "reviewed-delivery",
                "prompt": "Complete the confirmed work.",
            },
        )
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="I prepared the exact run-start proposal.",
            ),
            provider_thread_id=invocation.provider_thread_id or "proposal-thread",
        )


async def test_durable_two_turn_question_flow_and_idempotent_replay(
    tmp_path: Path,
) -> None:
    runner = ScriptedOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create-1")
            replayed = await services.conversations.create_conversation(idempotency_key="create-1")
            accepted = await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Help me shape a Workflow."),
                idempotency_key="message-1",
            )
            await services.coordinator.drain()
            asked = await services.conversations.read_conversation(created.id)
            question_set = asked.entries[-1]
            assert isinstance(question_set, OperatorQuestionSetEntry)
            question = question_set.questions[0]
            await services.conversations.answer_question_set(
                conversation_id=created.id,
                question_set_id=question_set.id,
                request=OperatorQuestionAnswersRequest.model_validate(
                    {
                        "answers": [
                            {
                                "question_id": question.id,
                                "answer": {
                                    "kind": "option",
                                    "option_id": question.options[0].id,
                                },
                            }
                        ]
                    }
                ),
                idempotency_key="answer-1",
            )
            await services.coordinator.drain()
            completed = await services.conversations.read_conversation(created.id)

    assert replayed.id == created.id
    assert accepted.state == "running"
    assert asked.state == "awaiting_answer"
    assert [entry.kind for entry in completed.entries] == [
        "user_message",
        "question_set",
        "question_answer",
        "assistant_message",
    ]
    assert completed.state == "ready"
    assert runner.inputs[0] == "Help me shape a Workflow."
    assert runner.inputs[1].startswith('<operator_return kind="question_answer">')
    assert "Which direction should the draft take?" in runner.inputs[1]
    assert "Concise" in runner.inputs[1]
    assert "private-thread" not in completed.model_dump_json()


async def test_stale_running_invocation_is_not_replayed_after_restart(
    tmp_path: Path,
) -> None:
    first_runner = ScriptedOperatorRunner()
    second_runner = ScriptedOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        first = _services(tmp_path, session_factory, first_runner)
        created = await first.conversations.create_conversation(idempotency_key="create")
        await first.conversations.submit_message(
            conversation_id=created.id,
            request=OperatorMessageRequest(text="This turn will be interrupted."),
            idempotency_key="message",
        )
        async with session_factory() as session:
            await session.execute(
                update(OperatorInvocationModel)
                .where(OperatorInvocationModel.conversation_id == created.id)
                .values(state="running")
            )
            await session.commit()

        restarted = _services(tmp_path, session_factory, second_runner)
        async with restarted.coordinator:
            await restarted.coordinator.drain()
            recovered = await restarted.conversations.read_conversation(created.id)
        async with session_factory() as session:
            invocation = await session.scalar(
                select(OperatorInvocationModel).where(
                    OperatorInvocationModel.conversation_id == created.id
                )
            )

    assert second_runner.inputs == []
    assert recovered.state == "failed"
    assert recovered.entries[-1].kind == "recoverable_error"
    assert [action.kind for action in recovered.legal_actions] == ["retry_provider_invocation"]
    assert invocation is not None and invocation.state == "failed"


async def test_same_message_key_with_different_body_is_a_conflict(
    tmp_path: Path,
) -> None:
    runner = ScriptedOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        created = await services.conversations.create_conversation(idempotency_key="create")
        await services.conversations.submit_message(
            conversation_id=created.id,
            request=OperatorMessageRequest(text="First body."),
            idempotency_key="same-key",
        )
        with pytest.raises(OperatorServiceError) as raised:
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Different body."),
                idempotency_key="same-key",
            )

    assert raised.value.status_code == 409
    assert raised.value.response.problem.code == "idempotency_conflict"


async def test_competing_message_admissions_leave_one_active_invocation(
    tmp_path: Path,
) -> None:
    runner = ScriptedOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        created = await services.conversations.create_conversation(idempotency_key="create")
        outcomes = await asyncio.gather(
            services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="First competing message."),
                idempotency_key="message-first",
            ),
            services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Second competing message."),
                idempotency_key="message-second",
            ),
            return_exceptions=True,
        )
        async with session_factory() as session:
            invocation_count = await session.scalar(
                select(func.count())
                .select_from(OperatorInvocationModel)
                .where(OperatorInvocationModel.conversation_id == created.id)
            )

    successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, OperatorServiceError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].response.problem.code == "operator_action_not_current"
    assert invocation_count == 1


async def test_guarded_effect_is_proposed_then_executes_once_after_confirmation(
    tmp_path: Path,
) -> None:
    runner = ProposalOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Start the reviewed-delivery run."),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            proposed = await services.conversations.read_conversation(created.id)
            confirmation = next(
                action for action in proposed.legal_actions if action.kind == "confirm_effect"
            )
            confirmed = await services.conversations.confirm_effect(
                conversation_id=created.id,
                confirmation_id=confirmation.confirmation_id or "",
                idempotency_key="confirm",
            )
            replayed = await services.conversations.confirm_effect(
                conversation_id=created.id,
                confirmation_id=confirmation.confirmation_id or "",
                idempotency_key="confirm",
            )
        async with session_factory() as session:
            task_count = await session.scalar(select(func.count()).select_from(TaskModel))

    assert runner.tool_result is not None
    assert runner.tool_result.kind == "proposal"
    assert [entry.kind for entry in proposed.entries] == [
        "user_message",
        "action_proposal",
        "assistant_message",
    ]
    assert confirmed.entries[-1].kind == "effect_receipt"
    assert replayed.entries == confirmed.entries
    assert task_count == 1


def _services(
    tmp_path: Path,
    session_factory: AsyncSessionFactory,
    runner: ScriptedOperatorRunner | ProposalOperatorRunner,
) -> OperatorServices:
    dependencies = product_dispatch_dependencies(tmp_path)
    return create_operator_services(
        session_factory=session_factory,
        settings=dependencies.settings,
        dispatch_dependencies=dependencies,
        runtime_effect_publisher=None,
        provider_runner=runner,
    )
