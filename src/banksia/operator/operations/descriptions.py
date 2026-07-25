from __future__ import annotations

from banksia.operator.operations.contracts import TaskStartOperationRequest
from banksia.runtime.contracts.task import (
    CommandRunView,
    HumanRequestView,
    ProductAction,
    TaskView,
)
from banksia.workflows.authoring_contracts import (
    WorkflowDraftReadback,
    WorkflowGetResponse,
)

_SCOPE_EXCERPT_CHARACTERS = 180


def describe_draft_undo(draft: WorkflowDraftReadback) -> tuple[str, str, str]:
    return (
        "Undo the latest Workflow change",
        _workflow_scope(draft),
        "The most recent reversible change will be removed and the Workflow will remain a draft.",
    )


def describe_draft_discard(draft: WorkflowDraftReadback) -> tuple[str, str, str]:
    return (
        "Discard this Workflow draft",
        _workflow_scope(draft),
        "All unpublished changes in this draft will be permanently removed.",
    )


def describe_draft_publish(draft: WorkflowDraftReadback) -> tuple[str, str, str]:
    return (
        "Publish this Workflow",
        _workflow_scope(draft),
        "The current draft will become a new immutable Workflow revision.",
    )


def describe_task_start(
    workflow: WorkflowGetResponse,
    request: TaskStartOperationRequest,
) -> tuple[str, str, str]:
    return (
        "Start this run",
        (
            f"New run for “{_readable_excerpt(request.prompt)}” using Workflow "
            f"“{_readable_excerpt(workflow.description)}”"
        ),
        "Banksia will create the run and begin its work asynchronously.",
    )


def describe_task_control(
    task: TaskView,
    action: ProductAction,
) -> tuple[str, str, str]:
    return (
        action.label,
        _task_scope(task),
        action.confirmation.consequence,
    )


def describe_human_response(
    task: TaskView,
    human_request: HumanRequestView,
    action: ProductAction,
) -> tuple[str, str, str]:
    return (
        action.label,
        (
            f"Request “{_readable_excerpt(human_request.summary)}” for "
            f"{_as_sentence_continuation(_task_scope(task))}"
        ),
        action.confirmation.consequence,
    )


def describe_command_cancel(
    task: TaskView,
    command: CommandRunView,
    action: ProductAction,
) -> tuple[str, str, str]:
    return (
        action.label,
        (
            f"Managed action “{_readable_excerpt(command.purpose)}” for "
            f"{_as_sentence_continuation(_task_scope(task))}"
        ),
        (
            f"{action.confirmation.consequence} "
            "Acceptance does not mean the action has already stopped."
        ),
    )


def _workflow_scope(draft: WorkflowDraftReadback) -> str:
    return f"Workflow “{_readable_excerpt(draft.workflow.description)}”"


def _task_scope(task: TaskView) -> str:
    return (
        f"Run “{_readable_excerpt(task.prompt_excerpt)}” using Workflow "
        f"“{_readable_excerpt(task.workflow.description)}”"
    )


def _readable_excerpt(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= _SCOPE_EXCERPT_CHARACTERS:
        return normalized
    return f"{normalized[: _SCOPE_EXCERPT_CHARACTERS - 1].rstrip()}…"


def _as_sentence_continuation(value: str) -> str:
    return f"{value[:1].lower()}{value[1:]}"


__all__ = [
    "describe_command_cancel",
    "describe_draft_discard",
    "describe_draft_publish",
    "describe_draft_undo",
    "describe_human_response",
    "describe_task_control",
    "describe_task_start",
]
