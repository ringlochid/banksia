from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.authoring.contracts import (
    DefinitionDraftMode,
    DefinitionDraftValidationIssue,
    DefinitionDraftValidationResponse,
)
from autoclaw.definitions.authoring.readback import (
    CurrentDefinitionSnapshot,
    definition_draft_is_stale,
    load_current_definition_snapshot,
    parse_definition_body_for_storage,
)
from autoclaw.definitions.authoring.storage import StoredDefinitionDraft
from autoclaw.definitions.compiler import WorkflowRevisionMetadata, compile_workflow
from autoclaw.definitions.contracts import (
    DefinitionContent,
    DefinitionKind,
    WorkflowDefinitionInput,
)
from autoclaw.definitions.registry.current import build_workflow_role_policy_lookup


@dataclass(frozen=True)
class DraftValidationOutcome:
    response: DefinitionDraftValidationResponse
    content: DefinitionContent | None
    current_snapshot: CurrentDefinitionSnapshot | None


async def validate_definition_draft(
    session: AsyncSession,
    *,
    draft: StoredDefinitionDraft,
) -> DraftValidationOutcome:
    metadata = draft.metadata
    current_snapshot = await load_current_definition_snapshot(
        session,
        kind=metadata.kind,
        key=metadata.key,
    )
    errors: list[DefinitionDraftValidationIssue] = []
    parsed = parse_definition_body_for_storage(
        kind=metadata.kind,
        key=metadata.key,
        body=draft.body,
    )
    content = parsed.content
    if parsed.error is not None:
        errors.append(
            DefinitionDraftValidationIssue(
                code="invalid_definition_body",
                message=parsed.error,
                path=metadata.draft_path,
                kind="schema",
            )
        )
    elif content is not None and metadata.kind == DefinitionKind.WORKFLOW:
        errors.extend(await workflow_cross_reference_errors(session, draft=draft, content=content))

    collision_error = definition_name_collision_error(draft, current_snapshot=current_snapshot)
    if collision_error is not None:
        errors.append(collision_error)
    elif definition_draft_is_stale(metadata, current_snapshot=current_snapshot):
        errors.append(
            DefinitionDraftValidationIssue(
                code="stale_baseline",
                message=(
                    f"definition draft '{metadata.key}' is based on registry truth that changed"
                ),
                path=metadata.draft_path,
                kind="stale",
            )
        )

    return DraftValidationOutcome(
        response=DefinitionDraftValidationResponse(
            kind=metadata.kind,
            key=metadata.key,
            status=validation_status(errors),
            errors=tuple(errors),
            warnings=(),
        ),
        content=content if parsed.error is None else None,
        current_snapshot=current_snapshot,
    )


def definition_name_collision_error(
    draft: StoredDefinitionDraft,
    *,
    current_snapshot: CurrentDefinitionSnapshot | None,
) -> DefinitionDraftValidationIssue | None:
    if draft.metadata.mode != DefinitionDraftMode.CREATE or current_snapshot is None:
        return None
    return DefinitionDraftValidationIssue(
        code="name_collision",
        message=f"{draft.metadata.kind.value} '{draft.metadata.key}' already exists",
        path=draft.metadata.draft_path,
        kind="collision",
    )


async def workflow_cross_reference_errors(
    session: AsyncSession,
    *,
    draft: StoredDefinitionDraft,
    content: DefinitionContent,
) -> list[DefinitionDraftValidationIssue]:
    try:
        workflow = cast(WorkflowDefinitionInput, content)
        lookup = await build_workflow_role_policy_lookup(session, workflow)
        compile_workflow(
            workflow=workflow,
            workflow_revision=WorkflowRevisionMetadata(
                workflow_key=draft.metadata.key,
                definition_revision_no=draft.metadata.based_on.revision_no or 1,
            ),
            compiler_version="definition-authoring-validate",
            lookup=lookup,
        )
    except ValueError as exc:
        return [
            DefinitionDraftValidationIssue(
                code="workflow_cross_reference_invalid",
                message=str(exc),
                path=draft.metadata.draft_path,
                kind="cross_reference",
            )
        ]
    return []


def validation_status(
    errors: list[DefinitionDraftValidationIssue],
) -> Literal["valid", "invalid", "stale", "name_collision"]:
    if any(error.kind == "collision" for error in errors):
        return "name_collision"
    if any(error.kind == "stale" for error in errors):
        return "stale"
    if errors:
        return "invalid"
    return "valid"


__all__ = ["DraftValidationOutcome", "validate_definition_draft"]
