from __future__ import annotations

from collections.abc import Sequence
from typing import cast, overload

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, joinedload

from autoclaw.definitions.registry.revisions.types import (
    CurrentDefinitionModel,
    CurrentDefinitionRevisionRow,
    CurrentRevisionModel,
    DefinitionModelType,
    RevisionModelT,
    RevisionModelType,
)
from autoclaw.persistence.models import (
    PolicyDefinitionModel,
    PolicyRevisionModel,
    RoleDefinitionModel,
    RoleRevisionModel,
    WorkflowDefinitionModel,
    WorkflowRevisionModel,
)


@overload
async def load_current_definition_revision(
    session: AsyncSession,
    definition_model: type[WorkflowDefinitionModel],
    revision_model: type[WorkflowRevisionModel],
    *,
    key_column: InstrumentedAttribute[str],
    key_field: str,
    key: str,
) -> WorkflowRevisionModel: ...


@overload
async def load_current_definition_revision(
    session: AsyncSession,
    definition_model: type[RoleDefinitionModel],
    revision_model: type[RoleRevisionModel],
    *,
    key_column: InstrumentedAttribute[str],
    key_field: str,
    key: str,
) -> RoleRevisionModel: ...


@overload
async def load_current_definition_revision(
    session: AsyncSession,
    definition_model: type[PolicyDefinitionModel],
    revision_model: type[PolicyRevisionModel],
    *,
    key_column: InstrumentedAttribute[str],
    key_field: str,
    key: str,
) -> PolicyRevisionModel: ...


async def load_current_definition_revision(
    session: AsyncSession,
    definition_model: DefinitionModelType,
    revision_model: RevisionModelType,
    *,
    key_column: InstrumentedAttribute[str],
    key_field: str,
    key: str,
) -> CurrentRevisionModel:
    definition_key = cast(
        InstrumentedAttribute[str],
        getattr(definition_model, key_column.key),
    )
    definition = cast(
        CurrentDefinitionModel | None,
        await session.scalar(select(definition_model).where(definition_key == key)),
    )
    if definition is None:
        raise ValueError(f"unknown definition key '{key}'")
    if definition.current_revision_no is None:
        raise ValueError(f"missing current revision pointer for {key_field} '{key}'")
    revision_key = cast(
        InstrumentedAttribute[str],
        getattr(revision_model, key_column.key),
    )
    revision = await session.scalar(
        select(revision_model).where(
            revision_key == key,
            revision_model.revision_no == definition.current_revision_no,
        )
    )
    if revision is None:
        raise ValueError(
            "missing current revision for "
            f"{key_field} '{key}' at revision {definition.current_revision_no}"
        )
    return cast(CurrentRevisionModel, revision)


async def load_definition_revision_by_no(
    session: AsyncSession,
    revision_model: type[RevisionModelT],
    *,
    key_column: InstrumentedAttribute[str],
    key_field: str,
    key: str,
    revision_no: int,
) -> RevisionModelT:
    revision = await session.scalar(
        select(revision_model).where(
            key_column == key,
            revision_model.revision_no == revision_no,
        )
    )
    if revision is None:
        raise ValueError(f"missing {key_field} '{key}' revision {revision_no}")
    return revision


async def load_definition_revision_by_content_hash(
    session: AsyncSession,
    revision_model: type[RevisionModelT],
    *,
    key_column: InstrumentedAttribute[str],
    key: str,
    content_hash: str,
) -> RevisionModelT | None:
    return cast(
        RevisionModelT | None,
        await session.scalar(
            select(revision_model)
            .where(
                key_column == key,
                revision_model.content_hash == content_hash,
            )
            .order_by(revision_model.revision_no.desc())
        ),
    )


@overload
async def load_current_definition_revision_rows(
    session: AsyncSession,
    definition_model: type[WorkflowDefinitionModel],
    revision_model: type[WorkflowRevisionModel],
    *,
    definition_key: InstrumentedAttribute[str],
    revision_key: InstrumentedAttribute[str],
    current_revision_no: InstrumentedAttribute[int | None],
) -> list[tuple[WorkflowDefinitionModel, WorkflowRevisionModel]]: ...


@overload
async def load_current_definition_revision_rows(
    session: AsyncSession,
    definition_model: type[RoleDefinitionModel],
    revision_model: type[RoleRevisionModel],
    *,
    definition_key: InstrumentedAttribute[str],
    revision_key: InstrumentedAttribute[str],
    current_revision_no: InstrumentedAttribute[int | None],
) -> list[tuple[RoleDefinitionModel, RoleRevisionModel]]: ...


@overload
async def load_current_definition_revision_rows(
    session: AsyncSession,
    definition_model: type[PolicyDefinitionModel],
    revision_model: type[PolicyRevisionModel],
    *,
    definition_key: InstrumentedAttribute[str],
    revision_key: InstrumentedAttribute[str],
    current_revision_no: InstrumentedAttribute[int | None],
) -> list[tuple[PolicyDefinitionModel, PolicyRevisionModel]]: ...


async def load_current_definition_revision_rows(
    session: AsyncSession,
    definition_model: DefinitionModelType,
    revision_model: RevisionModelType,
    *,
    definition_key: InstrumentedAttribute[str],
    revision_key: InstrumentedAttribute[str],
    current_revision_no: InstrumentedAttribute[int | None],
) -> Sequence[CurrentDefinitionRevisionRow]:
    _ = revision_model, revision_key
    current_revision = definition_model.current_revision
    definitions = cast(
        list[CurrentDefinitionModel],
        (
            await session.scalars(
                select(definition_model)
                .options(joinedload(current_revision))
                .where(current_revision_no.is_not(None))
                .order_by(definition_key.asc())
            )
        )
        .unique()
        .all(),
    )

    rows: list[CurrentDefinitionRevisionRow] = []
    for definition_row in definitions:
        revision_row = definition_row.current_revision
        if revision_row is None:
            definition_id = cast(str, getattr(definition_row, definition_key.key))
            raise ValueError(
                "missing current revision for "
                f"{definition_key.key} '{definition_id}' at revision "
                f"{definition_row.current_revision_no}"
            )
        rows.append(cast(CurrentDefinitionRevisionRow, (definition_row, revision_row)))
    return rows
