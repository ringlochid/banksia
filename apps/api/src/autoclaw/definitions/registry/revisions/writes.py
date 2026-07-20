from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from sqlalchemy import Table, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from autoclaw.definitions.registry.revisions.ids import canonical_content_hash, workflow_revision_id
from autoclaw.definitions.registry.revisions.reads import (
    load_current_definition_revision,
    load_definition_revision_by_content_hash,
)
from autoclaw.definitions.registry.revisions.types import (
    DefinitionInput,
    DefinitionModelT,
    PreparedDefinitionRevisionUpsert,
    RevisionModelT,
)
from autoclaw.persistence.models import WorkflowRevisionModel

UpsertResultT = TypeVar("UpsertResultT")


async def prepare_definition_revision_upsert(
    session: AsyncSession,
    *,
    definition: DefinitionInput,
    source_path: str | None,
    should_allow_existing_update: bool,
    definition_model: type[DefinitionModelT],
    revision_model: type[RevisionModelT],
    definition_key_column: InstrumentedAttribute[str],
    revision_key_column: InstrumentedAttribute[str],
    key_field: str,
    build_row: Callable[[], DefinitionModelT],
    build_result: Callable[[int], UpsertResultT],
    load_current: Callable[[], Awaitable[UpsertResultT]],
) -> tuple[PreparedDefinitionRevisionUpsert[DefinitionModelT] | None, UpsertResultT | None]:
    content_json = cast(dict[str, object], definition.model_dump(mode="json", exclude={"kind"}))
    content_hash = canonical_content_hash(content_json)
    current_seed_owned = False
    definition_row, created_owner = await acquire_definition_owner_row(
        session,
        definition_model,
        key_column=definition_key_column,
        key=definition.id,
        build_row=build_row,
    )
    if created_owner:
        return (
            PreparedDefinitionRevisionUpsert(
                definition_row=definition_row,
                revision_no=1,
                content_json=content_json,
                content_hash=content_hash,
                should_update_current=True,
            ),
            None,
        )

    current_revision = await load_current_definition_revision(
        session,
        cast(Any, definition_model),
        cast(Any, revision_model),
        key_column=revision_key_column,
        key_field=key_field,
        key=definition.id,
    )
    if not should_allow_existing_update:
        current_seed_owned, existing_result = await _resolve_locked_definition_upsert(
            session,
            definition_id=definition.id,
            source_path=source_path,
            current_source_path=current_revision.source_path,
            definition_row=definition_row,
            revision_model=revision_model,
            revision_key_column=revision_key_column,
            content_hash=content_hash,
            build_result=build_result,
            load_current=load_current,
        )
        if existing_result is not None:
            return None, existing_result
    elif current_revision.content_hash == content_hash:
        return None, build_result(current_revision.revision_no)

    revision_no = await next_registry_revision_no(
        session,
        revision_model,
        key_column=revision_key_column,
        key=definition.id,
    )
    return (
        PreparedDefinitionRevisionUpsert(
            definition_row=definition_row,
            revision_no=revision_no,
            content_json=content_json,
            content_hash=content_hash,
            should_update_current=should_allow_existing_update or current_seed_owned,
        ),
        None,
    )


async def insert_definition_revision(
    session: AsyncSession,
    *,
    definition_id: str,
    prepared: PreparedDefinitionRevisionUpsert[DefinitionModelT],
    revision_model: type[RevisionModelT],
    revision_key_column: InstrumentedAttribute[str],
    build_revision: Callable[[], object],
    build_result: Callable[[int], UpsertResultT],
) -> UpsertResultT | None:
    try:
        async with session.begin_nested():
            if prepared.should_update_current:
                _stage_current_revision_no(
                    session,
                    definition_row=prepared.definition_row,
                    revision_no=prepared.revision_no,
                )
            session.add(build_revision())
            await session.flush()
    except IntegrityError:
        matching_revision = await load_definition_revision_by_content_hash(
            session,
            revision_model,
            key_column=revision_key_column,
            key=definition_id,
            content_hash=prepared.content_hash,
        )
        if matching_revision is None:
            raise
        await _set_current_revision_no(
            session,
            definition_row=prepared.definition_row,
            revision_no=matching_revision.revision_no,
        )
        return build_result(matching_revision.revision_no)
    return None


async def insert_workflow_revision(
    session: AsyncSession,
    *,
    definition_id: str,
    source_path: str | None,
    prepared: PreparedDefinitionRevisionUpsert[DefinitionModelT],
    build_result: Callable[[int], UpsertResultT],
) -> UpsertResultT | None:
    try:
        async with session.begin_nested():
            if prepared.should_update_current:
                _stage_current_revision_no(
                    session,
                    definition_row=prepared.definition_row,
                    revision_no=prepared.revision_no,
                )
            session.add(
                WorkflowRevisionModel(
                    workflow_revision_id=workflow_revision_id(
                        definition_id,
                        prepared.revision_no,
                    ),
                    workflow_key=definition_id,
                    revision_no=prepared.revision_no,
                    content_hash=prepared.content_hash,
                    content_json=prepared.content_json,
                    source_path=source_path,
                )
            )
            await session.flush()
    except IntegrityError:
        matching_revision = await load_definition_revision_by_content_hash(
            session,
            WorkflowRevisionModel,
            key_column=WorkflowRevisionModel.workflow_key,
            key=definition_id,
            content_hash=prepared.content_hash,
        )
        if matching_revision is None:
            raise
        await _set_current_revision_no(
            session,
            definition_row=prepared.definition_row,
            revision_no=matching_revision.revision_no,
        )
        return build_result(matching_revision.revision_no)
    return None


async def acquire_definition_owner_row(
    session: AsyncSession,
    definition_model: type[DefinitionModelT],
    *,
    key_column: InstrumentedAttribute[str],
    key: str,
    build_row: Callable[[], DefinitionModelT],
) -> tuple[DefinitionModelT, bool]:
    await _acquire_sqlite_registry_write_transaction(
        session,
        definition_model=definition_model,
        key_column=key_column,
        key=key,
    )
    row = await load_definition_for_update(
        session,
        definition_model,
        key_column=key_column,
        key=key,
    )
    if row is not None and row.current_revision_no is not None:
        return row, False

    row = build_row()
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        row = await load_definition_for_update(
            session,
            definition_model,
            key_column=key_column,
            key=key,
        )
        if row is None:
            raise
        return row, False

    return row, True


async def load_definition_for_update(
    session: AsyncSession,
    definition_model: type[DefinitionModelT],
    *,
    key_column: InstrumentedAttribute[str],
    key: str,
) -> DefinitionModelT | None:
    row: DefinitionModelT | None = await session.scalar(
        select(definition_model).where(key_column == key).with_for_update()
    )
    return row


async def next_registry_revision_no(
    session: AsyncSession,
    revision_model: type[RevisionModelT],
    *,
    key_column: InstrumentedAttribute[str],
    key: str,
) -> int:
    revision_no = await session.scalar(
        select(func.max(revision_model.revision_no)).where(key_column == key)
    )
    return int(revision_no or 0) + 1


def seed_source_matches(
    *,
    stored_source_path: str | None,
    expected_source_path: str,
) -> bool:
    if stored_source_path is None:
        return False
    normalized_stored_path = stored_source_path.replace("\\", "/")
    if normalized_stored_path == expected_source_path:
        return True
    packaged_prefix = "seed://packaged/"
    if not expected_source_path.startswith(packaged_prefix):
        return False
    relative_seed_path = expected_source_path.removeprefix(packaged_prefix)
    return normalized_stored_path.endswith(f"/definitions/{relative_seed_path}")


async def _acquire_sqlite_registry_write_transaction(
    session: AsyncSession,
    *,
    definition_model: type[DefinitionModelT],
    key_column: InstrumentedAttribute[str],
    key: str,
) -> None:
    if session.get_bind().dialect.name != "sqlite":
        return

    definition_table = cast(Table, definition_model.__table__)
    definition_key = definition_table.c[key_column.key]
    updated_at = definition_table.c.updated_at
    await session.execute(
        update(definition_table)
        .where(definition_key == key)
        .values(
            {
                definition_key: definition_key,
                updated_at: updated_at,
            }
        )
    )


async def _resolve_locked_definition_upsert(
    session: AsyncSession,
    *,
    definition_id: str,
    source_path: str | None,
    current_source_path: str | None,
    definition_row: DefinitionModelT,
    revision_model: type[RevisionModelT],
    revision_key_column: InstrumentedAttribute[str],
    content_hash: str,
    build_result: Callable[[int], UpsertResultT],
    load_current: Callable[[], Awaitable[UpsertResultT]],
) -> tuple[bool, UpsertResultT | None]:
    if source_path is None:
        return False, await load_current()

    current_seed_owned = seed_source_matches(
        stored_source_path=current_source_path,
        expected_source_path=source_path,
    )
    matching_revision = await load_definition_revision_by_content_hash(
        session,
        revision_model,
        key_column=revision_key_column,
        key=definition_id,
        content_hash=content_hash,
    )
    if matching_revision is None:
        return current_seed_owned, None
    if current_seed_owned:
        await _set_current_revision_no(
            session,
            definition_row=definition_row,
            revision_no=matching_revision.revision_no,
        )
    return current_seed_owned, build_result(matching_revision.revision_no)


def _stage_current_revision_no(
    session: AsyncSession,
    *,
    definition_row: DefinitionModelT,
    revision_no: int,
) -> None:
    if definition_row.current_revision_no == revision_no:
        return
    definition_row.current_revision_no = revision_no
    session.add(definition_row)


async def _set_current_revision_no(
    session: AsyncSession,
    *,
    definition_row: DefinitionModelT,
    revision_no: int,
) -> None:
    if definition_row.current_revision_no == revision_no:
        return
    _stage_current_revision_no(session, definition_row=definition_row, revision_no=revision_no)
    await session.flush()
