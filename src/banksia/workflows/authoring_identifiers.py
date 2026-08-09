from __future__ import annotations

import re
from secrets import token_urlsafe

from banksia.workflows.contracts import NormalizedWorkflow


def new_workflow_draft_etag() -> str:
    return f'"wd-{token_urlsafe(24)}"'


def new_workflow_draft_id() -> str:
    return f"workflow-draft.{token_urlsafe(24)}"


def new_workflow_undo_receipt_id() -> str:
    return f"workflow-undo.{token_urlsafe(24)}"


def next_workflow_member_sequence(workflow: NormalizedWorkflow) -> int:
    highest_sequence = 0

    def visit(member: object) -> None:
        nonlocal highest_sequence
        if not isinstance(member, dict):
            return
        member_id = member.get("id")
        if isinstance(member_id, str) and (match := re.fullmatch(r"member-(\d+)", member_id)):
            highest_sequence = max(highest_sequence, int(match.group(1)))
        children = member.get("children", ())
        if isinstance(children, (list, tuple)):
            for child in children:
                visit(child)

    visit(workflow.lead.model_dump(mode="json", exclude_none=True))
    return highest_sequence + 1


__all__ = [
    "new_workflow_draft_etag",
    "new_workflow_draft_id",
    "new_workflow_undo_receipt_id",
    "next_workflow_member_sequence",
]
