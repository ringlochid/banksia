from __future__ import annotations

from typing import cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.authoring.contracts import (
    DefinitionDraftMode,
    DefinitionDraftPublishedRevision,
)
from autoclaw.definitions.authoring.readback import CurrentDefinitionSnapshot
from autoclaw.definitions.authoring.storage import (
    StoredDefinitionDraft,
    normalize_definition_content,
)
from autoclaw.definitions.contracts import (
    DefinitionContent,
    DefinitionKind,
    PolicyDefinitionInput,
    RoleDefinitionInput,
    WorkflowDefinitionInput,
)
from autoclaw.definitions.registry.revisions.ids import (
    canonical_content_hash,
    policy_revision_id,
    role_revision_id,
    workflow_revision_id,
)
from autoclaw.definitions.registry.upsert import (
    upsert_policy_definition,
    upsert_role_definition,
    upsert_workflow_definition,
)
from autoclaw.persistence.models import (
    PolicyDefinitionModel,
    PolicyRevisionModel,
    RoleDefinitionModel,
    RoleRevisionModel,
    WorkflowDefinitionModel,
    WorkflowRevisionModel,
)
from autoclaw.runtime.errors import name_collision_error


async def publish_valid_definition_draft(
    session: AsyncSession,
    *,
    draft: StoredDefinitionDraft,
    content: DefinitionContent,
    current_snapshot: CurrentDefinitionSnapshot | None,
) -> DefinitionDraftPublishedRevision | None:
    source_path = f"definition-draft://{draft.metadata.kind.value}/{draft.metadata.key}"
    if draft.metadata.mode == DefinitionDraftMode.CREATE:
        return await publish_new_definition_revision(
            session,
            draft=draft,
            content=content,
            current_snapshot=current_snapshot,
            source_path=source_path,
        )
    return await publish_updated_definition_revision(
        session,
        draft=draft,
        content=content,
        current_snapshot=current_snapshot,
        source_path=source_path,
    )


async def publish_new_definition_revision(
    session: AsyncSession,
    *,
    draft: StoredDefinitionDraft,
    content: DefinitionContent,
    current_snapshot: CurrentDefinitionSnapshot | None,
    source_path: str,
) -> DefinitionDraftPublishedRevision:
    if current_snapshot is not None:
        raise name_collision_error(
            f"{draft.metadata.kind.value} '{draft.metadata.key}' already exists"
        )
    revision_no = await insert_first_definition_revision(
        session,
        kind=draft.metadata.kind,
        content=content,
        source_path=source_path,
    )
    return DefinitionDraftPublishedRevision(
        kind=draft.metadata.kind,
        key=draft.metadata.key,
        revision_no=revision_no,
        content_hash=canonical_content_hash(normalize_definition_content(content)),
    )


async def publish_updated_definition_revision(
    session: AsyncSession,
    *,
    draft: StoredDefinitionDraft,
    content: DefinitionContent,
    current_snapshot: CurrentDefinitionSnapshot | None,
    source_path: str,
) -> DefinitionDraftPublishedRevision | None:
    if current_snapshot is None:
        return None
    content_hash = canonical_content_hash(normalize_definition_content(content))
    if current_snapshot.content_hash == content_hash:
        return None

    if draft.metadata.kind == DefinitionKind.ROLE:
        revision_no = (
            await upsert_role_definition(
                session,
                cast(RoleDefinitionInput, content),
                source_path=source_path,
            )
        ).revision_no
    elif draft.metadata.kind == DefinitionKind.POLICY:
        revision_no = (
            await upsert_policy_definition(
                session,
                cast(PolicyDefinitionInput, content),
                source_path=source_path,
            )
        ).revision_no
    else:
        revision_no = (
            await upsert_workflow_definition(
                session,
                cast(WorkflowDefinitionInput, content),
                source_path=source_path,
            )
        ).revision_no
    return DefinitionDraftPublishedRevision(
        kind=draft.metadata.kind,
        key=draft.metadata.key,
        revision_no=revision_no,
        content_hash=content_hash,
    )


async def insert_first_definition_revision(
    session: AsyncSession,
    *,
    kind: DefinitionKind,
    content: DefinitionContent,
    source_path: str,
) -> int:
    content_json = normalize_definition_content(content)
    content_hash = canonical_content_hash(content_json)
    try:
        async with session.begin_nested():
            if kind == DefinitionKind.ROLE:
                role_definition = cast(RoleDefinitionInput, content)
                role_row = RoleDefinitionModel(
                    role_key=role_definition.id,
                    current_revision_no=None,
                )
                session.add(role_row)
                await session.flush()
                session.add(
                    RoleRevisionModel(
                        role_revision_id=role_revision_id(role_definition.id, 1),
                        role_key=role_definition.id,
                        revision_no=1,
                        content_hash=content_hash,
                        content_json=content_json,
                        source_path=source_path,
                    )
                )
                await session.flush()
                role_row.current_revision_no = 1
                session.add(role_row)
            elif kind == DefinitionKind.POLICY:
                policy_definition = cast(PolicyDefinitionInput, content)
                policy_row = PolicyDefinitionModel(
                    policy_key=policy_definition.id,
                    current_revision_no=None,
                )
                session.add(policy_row)
                await session.flush()
                session.add(
                    PolicyRevisionModel(
                        policy_revision_id=policy_revision_id(policy_definition.id, 1),
                        policy_key=policy_definition.id,
                        revision_no=1,
                        content_hash=content_hash,
                        content_json=content_json,
                        source_path=source_path,
                    )
                )
                await session.flush()
                policy_row.current_revision_no = 1
                session.add(policy_row)
            else:
                workflow_definition = cast(WorkflowDefinitionInput, content)
                workflow_row = WorkflowDefinitionModel(
                    workflow_key=workflow_definition.id,
                    current_revision_no=None,
                )
                session.add(workflow_row)
                await session.flush()
                session.add(
                    WorkflowRevisionModel(
                        workflow_revision_id=workflow_revision_id(workflow_definition.id, 1),
                        workflow_key=workflow_definition.id,
                        revision_no=1,
                        content_hash=content_hash,
                        content_json=content_json,
                        source_path=source_path,
                    )
                )
                await session.flush()
                workflow_row.current_revision_no = 1
                session.add(workflow_row)
            await session.flush()
    except IntegrityError as exc:
        raise name_collision_error(f"{kind.value} '{content.id}' already exists") from exc
    return 1


__all__ = ["publish_valid_definition_draft"]
