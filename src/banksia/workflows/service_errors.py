from __future__ import annotations

from banksia.workflows.authoring_contracts import WorkflowDraftReadback


class WorkflowServiceError(ValueError):
    pass


class WorkflowIntegrityError(WorkflowServiceError):
    pass


class WorkflowNotFoundError(WorkflowServiceError):
    pass


class WorkflowDraftConflictError(WorkflowServiceError):
    pass


class WorkflowPreconditionRequiredError(WorkflowServiceError):
    pass


class WorkflowStaleDraftError(WorkflowServiceError):
    def __init__(self, current: WorkflowDraftReadback) -> None:
        self.current = current
        super().__init__("draft precondition is stale")


class WorkflowUndoReceiptError(WorkflowServiceError):
    pass


__all__ = [
    "WorkflowDraftConflictError",
    "WorkflowIntegrityError",
    "WorkflowNotFoundError",
    "WorkflowPreconditionRequiredError",
    "WorkflowServiceError",
    "WorkflowStaleDraftError",
    "WorkflowUndoReceiptError",
]
