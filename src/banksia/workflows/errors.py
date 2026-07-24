from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowValidationIssue:
    source: str
    path: str
    message: str


class WorkflowInputError(ValueError):
    def __init__(self, *issues: WorkflowValidationIssue) -> None:
        if not issues:
            raise ValueError("WorkflowInputError requires at least one issue")
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in issues))


def workflow_input_error(*, source: str, path: str, message: str) -> WorkflowInputError:
    return WorkflowInputError(WorkflowValidationIssue(source=source, path=path, message=message))


__all__ = ["WorkflowInputError", "WorkflowValidationIssue", "workflow_input_error"]
