from __future__ import annotations

import pytest
from pydantic import ValidationError

from banksia.operator.contracts import (
    OPERATOR_PROVIDER_RESULT_ADAPTER,
    OperatorMessageRequest,
    OperatorProviderAskUserResult,
    OperatorQuestionAnswersRequest,
)


def test_message_request_is_strict_and_preserves_normalized_exact_text() -> None:
    request = OperatorMessageRequest.model_validate({"text": "first\r\nsecond\rthird  "})

    assert request.text == "first\nsecond\nthird  "
    with pytest.raises(ValidationError):
        OperatorMessageRequest.model_validate({"text": "hello", "unexpected": True})
    with pytest.raises(ValidationError):
        OperatorMessageRequest.model_validate({"text": " \n\t "})


def test_question_answers_are_a_closed_tagged_union() -> None:
    request = OperatorQuestionAnswersRequest.model_validate(
        {
            "answers": [
                {
                    "question_id": "q_one",
                    "answer": {"kind": "option", "option_id": "o_first"},
                },
                {
                    "question_id": "q_two",
                    "answer": {"kind": "custom", "text": "My own answer"},
                },
                {
                    "question_id": "q_three",
                    "answer": {"kind": "skip"},
                },
            ]
        }
    )

    assert tuple(answer.answer.kind for answer in request.answers) == (
        "option",
        "custom",
        "skip",
    )
    with pytest.raises(ValidationError):
        OperatorQuestionAnswersRequest.model_validate(
            {
                "answers": [
                    {
                        "question_id": "q_one",
                        "answer": {"kind": "option", "label": "First"},
                    }
                ]
            }
        )


def test_provider_result_is_exactly_message_or_ask_user() -> None:
    message = OPERATOR_PROVIDER_RESULT_ADAPTER.validate_python({"kind": "message", "text": "Done."})
    questions = OPERATOR_PROVIDER_RESULT_ADAPTER.validate_python(
        {
            "kind": "ask_user",
            "explanation": "One choice changes the draft.",
            "questions": [
                {
                    "header": "Approach",
                    "question": "Which approach should I use?",
                    "options": [
                        {
                            "label": "Small",
                            "description": "Keep the first draft narrowly scoped.",
                        },
                        {
                            "label": "Broad",
                            "description": "Include the related workflows now.",
                        },
                    ],
                }
            ],
        }
    )

    assert message.kind == "message"
    assert isinstance(questions, OperatorProviderAskUserResult)
    assert questions.questions[0].allow_skip is False
    with pytest.raises(ValidationError):
        OPERATOR_PROVIDER_RESULT_ADAPTER.validate_python(
            {"kind": "operator_return", "text": "not part of the contract"}
        )


def test_provider_question_rejects_browser_owned_other_option() -> None:
    with pytest.raises(ValidationError, match="browser owns"):
        OperatorProviderAskUserResult.model_validate(
            {
                "kind": "ask_user",
                "questions": [
                    {
                        "header": "Approach",
                        "question": "Which approach?",
                        "options": [
                            {
                                "label": "Small",
                                "description": "Keep the first draft narrow.",
                            },
                            {
                                "label": "Something else",
                                "description": "Enter a custom response.",
                            },
                        ],
                    }
                ],
            }
        )
