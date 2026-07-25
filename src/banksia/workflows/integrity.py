from __future__ import annotations

from pydantic import ValidationError

from banksia.workflows.contracts import NormalizedWorkflow
from banksia.workflows.service_errors import WorkflowIntegrityError


def read_persisted_workflow(
    payload: object,
    *,
    expected_workflow_id: str,
    source: str,
) -> NormalizedWorkflow:
    try:
        workflow = NormalizedWorkflow.model_validate(payload)
    except ValidationError as exc:
        raise WorkflowIntegrityError(f"{source} body is not a valid Workflow") from exc
    validate_persisted_workflow_identity(
        workflow.id,
        expected_workflow_id=expected_workflow_id,
        source=source,
    )
    return workflow


def validate_persisted_workflow_identity(
    workflow_id: object,
    *,
    expected_workflow_id: str,
    source: str,
) -> None:
    if workflow_id != expected_workflow_id:
        raise WorkflowIntegrityError(
            f"{source} identity does not match Workflow {expected_workflow_id!r}"
        )


__all__ = [
    "read_persisted_workflow",
    "validate_persisted_workflow_identity",
]
