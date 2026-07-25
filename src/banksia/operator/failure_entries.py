from __future__ import annotations


def build_provider_failure_body(
    conversation_id: str,
    *,
    problem: str,
    explanation: str,
    is_thread_lost: bool,
) -> dict[str, object]:
    recovery_action = (
        {
            "kind": "create_new_conversation",
            "label": "Start a new conversation",
            "href": "/api/operator/conversations",
        }
        if is_thread_lost
        else {
            "kind": "retry_provider_invocation",
            "label": "Retry",
            "href": f"/api/operator/conversations/{conversation_id}/retries",
        }
    )
    return {
        "problem": problem,
        "explanation": explanation,
        "recovery_action": recovery_action,
    }


__all__ = ["build_provider_failure_body"]
