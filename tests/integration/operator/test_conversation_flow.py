from __future__ import annotations

from pathlib import Path

import pytest

from oh_my_subagents.operator import (
    OperatorAnswerValidationError,
    OperatorIdempotencyConflictError,
    OperatorProviderAskUserResult,
    OperatorProviderMessageResult,
    OperatorRunnerStatus,
    OperatorTurnOutcome,
    OperatorUnavailableError,
)
from oh_my_subagents.operator.contracts import (
    OperatorAssistantQuestionSetEntry,
    OperatorMessageRequest,
    OperatorQuestionAnswersRequest,
    OperatorUserMessageEntry,
)
from tests.helpers.operator import (
    RecordingTurnRunner,
    operator_service,
)


def ask_user_outcome(
    *,
    provider_thread_id: str = "thread-1",
    question_count: int = 1,
) -> OperatorTurnOutcome:
    questions = [
        {
            "header": f"Choice {index}",
            "question": f"Which choice should Oh My Subagents use for item {index}?",
            "options": [
                {
                    "label": "First",
                    "description": "Use the first choice.",
                },
                {
                    "label": "Second",
                    "description": "Use the second choice.",
                },
            ],
        }
        for index in range(1, question_count + 1)
    ]
    return OperatorTurnOutcome(
        provider_thread_id=provider_thread_id,
        result=OperatorProviderAskUserResult.model_validate(
            {
                "kind": "ask_user",
                "questions": questions,
            }
        ),
    )


def option_answers_request(
    question_set: OperatorAssistantQuestionSetEntry,
    *,
    option_index: int = 0,
) -> OperatorQuestionAnswersRequest:
    return OperatorQuestionAnswersRequest.model_validate(
        {
            "answers": [
                {
                    "question_id": question.id,
                    "answer": {
                        "kind": "option",
                        "option_id": question.options[option_index].id,
                    },
                }
                for question in question_set.questions
            ]
        }
    )


async def test_message_question_answer_continues_the_exact_provider_thread(
    tmp_path: Path,
) -> None:
    message = OperatorTurnOutcome(
        provider_thread_id="thread-1",
        result=OperatorProviderMessageResult(kind="message", text="The draft is ready."),
    )
    runner = RecordingTurnRunner((_workflow_audience_outcome(), message))

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        awaiting = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Create a Workflow."),
            idempotency_key="message-1",
        )
        question_set = awaiting.entries[-1]
        assert isinstance(question_set, OperatorAssistantQuestionSetEntry)
        answered = await service.submit_question_answers(
            created.id,
            question_set.id,
            OperatorQuestionAnswersRequest.model_validate(
                {
                    "answers": [
                        {
                            "question_id": question_set.questions[0].id,
                            "answer": {
                                "kind": "option",
                                "option_id": question_set.questions[0].options[1].id,
                            },
                        }
                    ]
                }
            ),
            idempotency_key="answer-1",
        )

    assert awaiting.state == "awaiting_answer"
    assert answered.state == "ready"
    assert [entry.kind for entry in answered.entries] == [
        "user_message",
        "assistant_question_set",
        "user_question_answers",
        "assistant_message",
    ]
    assert runner.requests[0].provider_thread_id is None
    assert runner.requests[1].provider_thread_id == "thread-1"
    answer_input = runner.requests[1].input
    assert answer_input.model_dump(mode="json") == {
        "kind": "question_answers",
        "answers": [
            {
                "question": "Who should this Workflow serve?",
                "answer": {"kind": "option", "label": "Researchers"},
            }
        ],
    }


async def test_same_message_key_converges_and_mismatch_conflicts_without_replay(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(
        (
            OperatorTurnOutcome(
                provider_thread_id="thread-1",
                result=OperatorProviderMessageResult(kind="message", text="Done."),
            ),
        )
    )

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        first = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Do the work."),
            idempotency_key="message-1",
        )
        duplicate = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Do the work."),
            idempotency_key="message-1",
        )
        with pytest.raises(OperatorIdempotencyConflictError):
            await service.submit_message(
                created.id,
                OperatorMessageRequest(text="Do different work."),
                idempotency_key="message-1",
            )

    assert duplicate == first
    assert len(runner.requests) == 1


async def test_create_retry_resolves_before_current_provider_availability(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(())

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        runner.status = OperatorRunnerStatus(
            availability="unavailable",
            configured_provider="claude",
            model="different-model",
            effort="low",
            explanation="The configured provider is temporarily unavailable.",
        )

        duplicate = await service.create_conversation(idempotency_key="create-1")
        with pytest.raises(OperatorUnavailableError):
            await service.create_conversation(idempotency_key="create-2")

    assert duplicate == created
    assert duplicate.provider == "claude"
    assert duplicate.model == "claude-test"
    assert duplicate.effort == "high"
    assert runner.requests == []


async def test_same_answer_key_converges_and_mismatch_conflicts_without_replay(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(
        (
            ask_user_outcome(),
            OperatorTurnOutcome(
                provider_thread_id="thread-1",
                result=OperatorProviderMessageResult(kind="message", text="Done."),
            ),
        )
    )

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        awaiting = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Ask me."),
            idempotency_key="message-1",
        )
        question_set = awaiting.entries[-1]
        assert isinstance(question_set, OperatorAssistantQuestionSetEntry)
        request = option_answers_request(question_set)
        first = await service.submit_question_answers(
            created.id,
            question_set.id,
            request,
            idempotency_key="answer-1",
        )
        duplicate = await service.submit_question_answers(
            created.id,
            question_set.id,
            request,
            idempotency_key="answer-1",
        )
        mismatch = OperatorQuestionAnswersRequest.model_validate(
            {
                "answers": [
                    {
                        "question_id": question_set.questions[0].id,
                        "answer": {"kind": "custom", "text": "A different answer."},
                    }
                ]
            }
        )
        with pytest.raises(OperatorIdempotencyConflictError):
            await service.submit_question_answers(
                created.id,
                question_set.id,
                mismatch,
                idempotency_key="answer-1",
            )

    assert duplicate == first
    assert len(runner.requests) == 2


async def test_invalid_answers_roll_back_claim_without_provider_work(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner((ask_user_outcome(question_count=2),))

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        awaiting = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Ask two questions."),
            idempotency_key="message-1",
        )
        question_set = awaiting.entries[-1]
        assert isinstance(question_set, OperatorAssistantQuestionSetEntry)

        valid_request = option_answers_request(question_set)
        reversed_answers = OperatorQuestionAnswersRequest(
            answers=tuple(reversed(valid_request.answers))
        )
        invalid_option = OperatorQuestionAnswersRequest.model_validate(
            {
                "answers": [
                    {
                        "question_id": question.id,
                        "answer": {
                            "kind": "option",
                            "option_id": (
                                "not-controller-issued" if index == 0 else question.options[0].id
                            ),
                        },
                    }
                    for index, question in enumerate(question_set.questions)
                ]
            }
        )
        illegal_skip = OperatorQuestionAnswersRequest.model_validate(
            {
                "answers": [
                    {
                        "question_id": question.id,
                        "answer": (
                            {"kind": "skip"}
                            if index == 0
                            else {
                                "kind": "option",
                                "option_id": question.options[0].id,
                            }
                        ),
                    }
                    for index, question in enumerate(question_set.questions)
                ]
            }
        )

        for key, invalid_request in (
            ("answer-order", reversed_answers),
            ("answer-option", invalid_option),
            ("answer-skip", illegal_skip),
        ):
            with pytest.raises(OperatorAnswerValidationError):
                await service.submit_question_answers(
                    created.id,
                    question_set.id,
                    invalid_request,
                    idempotency_key=key,
                )
            readback = await service.read_conversation(created.id)
            assert readback.state == "awaiting_answer"
            assert [entry.kind for entry in readback.entries] == [
                "user_message",
                "assistant_question_set",
            ]

    assert len(runner.requests) == 1


async def test_provider_thread_identity_change_interrupts_instead_of_reconstructing(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(
        (
            ask_user_outcome(provider_thread_id="thread-1"),
            OperatorTurnOutcome(
                provider_thread_id="thread-2",
                result=OperatorProviderMessageResult(
                    kind="message",
                    text="This must not be committed.",
                ),
            ),
        )
    )

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        created = await service.create_conversation(idempotency_key="create-1")
        awaiting = await service.submit_message(
            created.id,
            OperatorMessageRequest(text="Ask me."),
            idempotency_key="message-1",
        )
        question_set = awaiting.entries[-1]
        assert isinstance(question_set, OperatorAssistantQuestionSetEntry)
        interrupted = await service.submit_question_answers(
            created.id,
            question_set.id,
            option_answers_request(question_set),
            idempotency_key="answer-1",
        )

    assert interrupted.state == "interrupted"
    assert [entry.kind for entry in interrupted.entries] == [
        "user_message",
        "assistant_question_set",
        "user_question_answers",
        "turn_interrupted",
    ]
    assert len(runner.requests) == 2


async def test_conversation_and_entry_readback_use_bounded_opaque_pages(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(
        (
            OperatorTurnOutcome(
                provider_thread_id="thread-1",
                result=OperatorProviderMessageResult(kind="message", text="First result."),
            ),
            OperatorTurnOutcome(
                provider_thread_id="thread-1",
                result=OperatorProviderMessageResult(kind="message", text="Second result."),
            ),
        )
    )

    async with operator_service(tmp_path, runner=runner) as (service, _session_factory):
        first_conversation = await service.create_conversation(idempotency_key="create-1")
        await service.submit_message(
            first_conversation.id,
            OperatorMessageRequest(text="First input."),
            idempotency_key="message-1",
        )
        await service.submit_message(
            first_conversation.id,
            OperatorMessageRequest(text="Second input."),
            idempotency_key="message-2",
        )
        latest_entries = await service.read_conversation(first_conversation.id, limit=2)
        assert latest_entries.older_cursor is not None
        older_entries = await service.read_conversation(
            first_conversation.id,
            cursor=latest_entries.older_cursor,
            limit=2,
        )

        second_conversation = await service.create_conversation(idempotency_key="create-2")
        third_conversation = await service.create_conversation(idempotency_key="create-3")
        latest_conversations = await service.list_conversations(limit=2)
        assert latest_conversations.next_cursor is not None
        older_conversations = await service.list_conversations(
            cursor=latest_conversations.next_cursor,
            limit=2,
        )

    assert [entry.kind for entry in latest_entries.entries] == [
        "user_message",
        "assistant_message",
    ]
    latest_user_message = latest_entries.entries[0]
    assert isinstance(latest_user_message, OperatorUserMessageEntry)
    assert latest_user_message.text == "Second input."
    assert [entry.kind for entry in older_entries.entries] == [
        "user_message",
        "assistant_message",
    ]
    older_user_message = older_entries.entries[0]
    assert isinstance(older_user_message, OperatorUserMessageEntry)
    assert older_user_message.text == "First input."
    assert older_entries.older_cursor is None
    assert {
        summary.id for summary in (*latest_conversations.items, *older_conversations.items)
    } == {
        first_conversation.id,
        second_conversation.id,
        third_conversation.id,
    }
    summaries = {
        summary.id: summary for summary in (*latest_conversations.items, *older_conversations.items)
    }
    assert summaries[first_conversation.id].preview == "First input."
    assert summaries[second_conversation.id].preview is None
    assert summaries[third_conversation.id].preview is None
    assert older_conversations.next_cursor is None


def _workflow_audience_outcome() -> OperatorTurnOutcome:
    return OperatorTurnOutcome(
        provider_thread_id="thread-1",
        result=OperatorProviderAskUserResult.model_validate(
            {
                "kind": "ask_user",
                "explanation": "The audience changes the draft.",
                "questions": [
                    {
                        "header": "Audience",
                        "question": "Who should this Workflow serve?",
                        "options": [
                            {
                                "label": "Developers",
                                "description": "Optimize the team for implementation work.",
                            },
                            {
                                "label": "Researchers",
                                "description": "Optimize the team for evidence review.",
                            },
                        ],
                    }
                ],
            }
        ),
    )
