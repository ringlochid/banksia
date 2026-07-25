from __future__ import annotations

from pathlib import Path

import pytest

from banksia.operator.contracts import (
    OperatorCustomAnswer,
    OperatorMessageRequest,
    OperatorOptionAnswer,
    OperatorProviderAskUserResult,
    OperatorProviderMessageResult,
    OperatorProviderQuestion,
    OperatorProviderQuestionOption,
    OperatorQuestion,
    OperatorQuestionAnswer,
    OperatorQuestionAnswersRequest,
    OperatorQuestionSetEntry,
    OperatorSkipAnswer,
)
from banksia.operator.errors import OperatorServiceError
from banksia.operator.operations import OperatorOperationExecutor
from banksia.operator.provider import (
    OperatorProviderAvailability,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.service import OperatorServices, create_operator_services
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import (
    AsyncSessionFactory,
    initialized_workflow_database,
)


class MultiQuestionOperatorRunner:
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
        if invocation.provider_input.startswith("<operator_return"):
            return OperatorProviderOutcome(
                result=OperatorProviderMessageResult(
                    kind="message",
                    text="The two answers are recorded.",
                ),
                provider_thread_id=invocation.provider_thread_id or "questions-thread",
            )
        return OperatorProviderOutcome(
            result=OperatorProviderAskUserResult(
                kind="ask_user",
                questions=(
                    OperatorProviderQuestion(
                        header="Tone",
                        question="How should A & B be described?",
                        options=(
                            OperatorProviderQuestionOption(
                                label="Plain",
                                consequence="Use plain language.",
                            ),
                            OperatorProviderQuestionOption(
                                label="Technical",
                                consequence="Use technical detail.",
                            ),
                        ),
                    ),
                    OperatorProviderQuestion.model_validate(
                        {
                            "header": "Example",
                            "question": "Should the draft include an example?",
                            "allow_skip": True,
                            "options": (
                                OperatorProviderQuestionOption(
                                    label="Include",
                                    consequence="Add one concrete example.",
                                ),
                                OperatorProviderQuestionOption(
                                    label="Omit",
                                    consequence="Keep the draft compact.",
                                ),
                            ),
                        }
                    ),
                ),
            ),
            provider_thread_id=invocation.provider_thread_id or "questions-thread",
        )


async def test_custom_and_explicit_skip_answers_form_one_fresh_provider_turn(
    tmp_path: Path,
) -> None:
    runner = MultiQuestionOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        async with services.coordinator:
            conversation_id, question_set = await _open_question_set(services)
            first, second = question_set.questions
            invalid_errors = await _collect_invalid_answer_errors(
                services,
                conversation_id=conversation_id,
                question_set_id=question_set.id,
                first=first,
                second=second,
            )
            stale_error = await _submit_valid_then_stale_answers(
                services,
                conversation_id=conversation_id,
                question_set_id=question_set.id,
                first=first,
                second=second,
            )
            await services.coordinator.drain()
            completed = await services.conversations.read_conversation(conversation_id)

    _assert_invalid_answer_errors(invalid_errors)
    assert stale_error.status_code == 409
    assert stale_error.response.problem.code == "operator_action_not_current"
    assert completed.state == "ready"
    assert runner.inputs[1] == _expected_provider_answer()


async def _open_question_set(
    services: OperatorServices,
) -> tuple[str, OperatorQuestionSetEntry]:
    created = await services.conversations.create_conversation(idempotency_key="create")
    await services.conversations.submit_message(
        conversation_id=created.id,
        request=OperatorMessageRequest(text="Draft the Workflow."),
        idempotency_key="message",
    )
    await services.coordinator.drain()
    asked = await services.conversations.read_conversation(created.id)
    question_set = asked.entries[-1]
    assert isinstance(question_set, OperatorQuestionSetEntry)
    return created.id, question_set


async def _collect_invalid_answer_errors(
    services: OperatorServices,
    *,
    conversation_id: str,
    question_set_id: str,
    first: OperatorQuestion,
    second: OperatorQuestion,
) -> tuple[OperatorServiceError, ...]:
    errors = []
    for idempotency_key, request in _invalid_answer_requests(first, second):
        with pytest.raises(OperatorServiceError) as invalid:
            await services.conversations.answer_question_set(
                conversation_id=conversation_id,
                question_set_id=question_set_id,
                request=request,
                idempotency_key=idempotency_key,
            )
        errors.append(invalid.value)
    return tuple(errors)


def _invalid_answer_requests(
    first: OperatorQuestion,
    second: OperatorQuestion,
) -> tuple[tuple[str, OperatorQuestionAnswersRequest], ...]:
    first_plain = OperatorQuestionAnswer(
        question_id=first.id,
        answer=OperatorCustomAnswer(kind="custom", text="Plain"),
    )
    second_skip = OperatorQuestionAnswer(
        question_id=second.id,
        answer=OperatorSkipAnswer(kind="skip"),
    )
    return (
        (
            "invalid-skip",
            _answers(
                OperatorQuestionAnswer(
                    question_id=first.id,
                    answer=OperatorSkipAnswer(kind="skip"),
                ),
                second_skip,
            ),
        ),
        (
            "invalid-option",
            _answers(
                OperatorQuestionAnswer(
                    question_id=first.id,
                    answer=OperatorOptionAnswer(
                        kind="option",
                        option_id="not-a-current-option",
                    ),
                ),
                second_skip,
            ),
        ),
        ("missing-answer", _answers(first_plain)),
        (
            "duplicate-answer",
            _answers(
                first_plain,
                OperatorQuestionAnswer(
                    question_id=first.id,
                    answer=OperatorCustomAnswer(kind="custom", text="Repeated"),
                ),
            ),
        ),
        (
            "wrong-question",
            _answers(
                OperatorQuestionAnswer(
                    question_id="not-a-current-question",
                    answer=OperatorCustomAnswer(kind="custom", text="Plain"),
                ),
                second_skip,
            ),
        ),
    )


async def _submit_valid_then_stale_answers(
    services: OperatorServices,
    *,
    conversation_id: str,
    question_set_id: str,
    first: OperatorQuestion,
    second: OperatorQuestion,
) -> OperatorServiceError:
    await services.conversations.answer_question_set(
        conversation_id=conversation_id,
        question_set_id=question_set_id,
        request=_custom_and_skip_answers(first, second, text="<green & clear>"),
        idempotency_key="valid-answers",
    )
    with pytest.raises(OperatorServiceError) as stale:
        await services.conversations.answer_question_set(
            conversation_id=conversation_id,
            question_set_id=question_set_id,
            request=_custom_and_skip_answers(first, second, text="A later answer"),
            idempotency_key="stale-answer",
        )
    return stale.value


def _custom_and_skip_answers(
    first: OperatorQuestion,
    second: OperatorQuestion,
    *,
    text: str,
) -> OperatorQuestionAnswersRequest:
    return _answers(
        OperatorQuestionAnswer(
            question_id=first.id,
            answer=OperatorCustomAnswer(kind="custom", text=text),
        ),
        OperatorQuestionAnswer(
            question_id=second.id,
            answer=OperatorSkipAnswer(kind="skip"),
        ),
    )


def _answers(*answers: OperatorQuestionAnswer) -> OperatorQuestionAnswersRequest:
    return OperatorQuestionAnswersRequest(answers=answers)


def _assert_invalid_answer_errors(
    errors: tuple[OperatorServiceError, ...],
) -> None:
    assert all(error.status_code == 422 for error in errors)
    assert all(error.response.problem.code == "invalid_operator_request" for error in errors)
    assert all(
        error.response.problem.message == "The Operator answers are invalid."
        and error.response.problem.field_errors
        for error in errors
    )


def _expected_provider_answer() -> str:
    return "\n".join(
        (
            '<operator_return kind="question_answer">',
            "  <question>",
            "    <text>How should A &amp; B be described?</text>",
            "    <answer>&lt;green &amp; clear&gt;</answer>",
            "  </question>",
            "  <question>",
            "    <text>Should the draft include an example?</text>",
            "    <answer>Skip</answer>",
            "  </question>",
            "</operator_return>",
        )
    )


def _services(
    tmp_path: Path,
    session_factory: AsyncSessionFactory,
    runner: MultiQuestionOperatorRunner,
) -> OperatorServices:
    dependencies = product_dispatch_dependencies(tmp_path)
    return create_operator_services(
        session_factory=session_factory,
        settings=dependencies.settings,
        dispatch_dependencies=dependencies,
        runtime_effect_publisher=None,
        provider_runner=runner,
    )
