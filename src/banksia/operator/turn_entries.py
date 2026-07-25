from __future__ import annotations

from datetime import datetime
from secrets import token_urlsafe
from uuid import uuid4

from banksia.operator.provider import OperatorTurnOutcome
from banksia.persistence.models import OperatorConversationEntryModel

_GENERIC_INTERRUPTION_EXPLANATION = (
    "The Operator turn was interrupted before Banksia could confirm a response."
)
_GENERIC_INTERRUPTION_NEXT_STEP = (
    "Review current product truth, then send a new message if it is still needed."
)
_THREAD_INTERRUPTION_EXPLANATION = (
    "This conversation can no longer continue because its provider thread is unavailable."
)
_THREAD_INTERRUPTION_NEXT_STEP = "Start a new Operator conversation."
_INTERRUPTION_DIAGNOSTIC_CATEGORIES = frozenset(
    {
        "admission_cancelled",
        "completion_cancelled",
        "completion_failed",
        "provider_failure",
        "provider_thread_unavailable",
        "startup_repair",
        "thread_identity_changed",
        "turn_cancelled",
    }
)


def build_assistant_entry(
    *,
    conversation_id: str,
    sequence: int,
    outcome: OperatorTurnOutcome,
    created_at: datetime,
) -> OperatorConversationEntryModel:
    result = outcome.result
    if result.kind == "message":
        return OperatorConversationEntryModel(
            entry_id=f"operator-entry.{uuid4().hex}",
            conversation_id=conversation_id,
            sequence=sequence,
            kind="assistant_message",
            body_json={"text": result.text},
            request_idempotency_key=None,
            request_digest=None,
            created_at=created_at,
        )

    entry_id = f"operator-question-set.{uuid4().hex}"
    questions = [
        {
            "id": f"q_{token_urlsafe(12)}",
            "header": question.header,
            "question": question.question,
            "allow_skip": question.allow_skip,
            "options": [
                {
                    "id": f"o_{token_urlsafe(12)}",
                    "label": option.label,
                    "description": option.description,
                }
                for option in question.options
            ],
        }
        for question in result.questions
    ]
    return OperatorConversationEntryModel(
        entry_id=entry_id,
        conversation_id=conversation_id,
        sequence=sequence,
        kind="assistant_question_set",
        body_json={
            "explanation": result.explanation,
            "questions": questions,
        },
        request_idempotency_key=None,
        request_digest=None,
        created_at=created_at,
    )


def build_interruption_entry(
    *,
    conversation_id: str,
    sequence: int,
    is_thread_unavailable: bool,
    diagnostic_category: str,
    created_at: datetime,
) -> OperatorConversationEntryModel:
    if diagnostic_category not in _INTERRUPTION_DIAGNOSTIC_CATEGORIES:
        raise ValueError("unknown Operator interruption diagnostic category")
    explanation = (
        _THREAD_INTERRUPTION_EXPLANATION
        if is_thread_unavailable
        else _GENERIC_INTERRUPTION_EXPLANATION
    )
    next_step = (
        _THREAD_INTERRUPTION_NEXT_STEP if is_thread_unavailable else _GENERIC_INTERRUPTION_NEXT_STEP
    )
    return OperatorConversationEntryModel(
        entry_id=f"operator-entry.{uuid4().hex}",
        conversation_id=conversation_id,
        sequence=sequence,
        kind="turn_interrupted",
        body_json={
            "explanation": explanation,
            "next_step": next_step,
            "diagnostic_category": diagnostic_category,
        },
        request_idempotency_key=None,
        request_digest=None,
        created_at=created_at,
    )


__all__ = ["build_assistant_entry", "build_interruption_entry"]
