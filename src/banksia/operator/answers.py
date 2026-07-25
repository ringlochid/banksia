from __future__ import annotations

from xml.sax.saxutils import escape

from banksia.operator.contracts import (
    OperatorAnswerValue,
    OperatorQuestionAnswersRequest,
)
from banksia.operator.errors import invalid_operator_answers
from banksia.persistence.models import OperatorConversationEntryModel


def validate_and_render_answers(
    question_entry: OperatorConversationEntryModel,
    request: OperatorQuestionAnswersRequest,
) -> str:
    questions = question_entry.body_json.get("questions")
    if not isinstance(questions, list):
        raise RuntimeError("stored Operator question set has no question list")
    if len(questions) != len(request.answers):
        raise invalid_operator_answers(
            "answers",
            "Submit one answer for each current question, in the displayed order.",
        )
    submitted_question_ids = [submitted.question_id for submitted in request.answers]
    if len(submitted_question_ids) != len(set(submitted_question_ids)):
        raise invalid_operator_answers(
            "answers",
            "Submit each current question exactly once.",
        )
    rendered: list[str] = ['<operator_return kind="question_answer">']
    for index, (question, submitted) in enumerate(zip(questions, request.answers, strict=True)):
        if not isinstance(question, dict):
            raise RuntimeError("stored Operator question is not an object")
        question_id = question.get("id")
        if not isinstance(question_id, str):
            raise RuntimeError("stored Operator question has no controller ID")
        if submitted.question_id != question_id:
            raise invalid_operator_answers(
                f"answers[{index}].question_id",
                "Answer the current question in its displayed position.",
            )
        question_text = question.get("question")
        if not isinstance(question_text, str):
            raise RuntimeError("stored Operator question has no readable text")
        answer_text = validate_operator_answer(
            question,
            submitted.answer,
            path=f"answers[{index}].answer",
        )
        rendered.extend(
            (
                "  <question>",
                f"    <text>{escape(question_text)}</text>",
                f"    <answer>{escape(answer_text)}</answer>",
                "  </question>",
            )
        )
    rendered.append("</operator_return>")
    return "\n".join(rendered)


def validate_operator_answer(
    question: dict[str, object],
    answer: OperatorAnswerValue,
    *,
    path: str = "answer",
) -> str:
    if answer.kind == "custom":
        return answer.text
    if answer.kind == "skip":
        if question.get("allow_skip") is not True:
            raise invalid_operator_answers(
                path,
                "Skip is not allowed for this question.",
            )
        return "Skip"
    options = question.get("options")
    if not isinstance(options, list):
        raise RuntimeError("stored Operator question has no option list")
    for option in options:
        if isinstance(option, dict) and option.get("id") == answer.option_id:
            label = option.get("label")
            if isinstance(label, str):
                return label
    raise invalid_operator_answers(
        f"{path}.option_id",
        "Choose one of the current options or provide a custom answer.",
    )


__all__ = ["validate_and_render_answers", "validate_operator_answer"]
