from __future__ import annotations

from banksia.workflows.contracts import (
    NormalizedMember,
    NormalizedWorkflow,
    RetiredOpenClawProviderSelection,
)
from banksia.workflows.errors import WorkflowInputError, WorkflowValidationIssue

_RETIRED_PROVIDER_MESSAGE = (
    "OpenClaw is retired; choose Codex, Claude, or remove the explicit provider"
)


def require_active_providers(workflow: NormalizedWorkflow) -> None:
    """Reject retired provider selections at active authoring boundaries."""

    issues = retired_provider_issues(workflow)
    if issues:
        raise WorkflowInputError(*issues)


def retired_provider_issues(
    workflow: NormalizedWorkflow,
) -> tuple[WorkflowValidationIssue, ...]:
    """Return exact readback paths for every retired provider selection."""

    issues: list[WorkflowValidationIssue] = []
    _collect_retired_provider_issues(workflow.lead, path="$.lead", issues=issues)
    return tuple(issues)


def _collect_retired_provider_issues(
    member: NormalizedMember,
    *,
    path: str,
    issues: list[WorkflowValidationIssue],
) -> None:
    if isinstance(member.provider, RetiredOpenClawProviderSelection):
        issues.append(
            WorkflowValidationIssue(
                source="provider.retired",
                path=f"{path}.provider.kind",
                message=_RETIRED_PROVIDER_MESSAGE,
            )
        )
    for index, child in enumerate(member.children or ()):
        _collect_retired_provider_issues(
            child,
            path=f"{path}.children[{index}]",
            issues=issues,
        )


__all__ = [
    "require_active_providers",
    "retired_provider_issues",
]
