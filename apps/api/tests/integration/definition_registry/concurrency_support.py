from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from autoclaw.definitions.contracts.registry import PolicyDefinitionInput, RoleDefinitionInput
from autoclaw.definitions.contracts.workflow import WorkflowDefinitionInput
from autoclaw.definitions.registry import (
    load_current_policy,
    load_current_role,
    load_current_workflow,
    upsert_policy_definition,
    upsert_role_definition,
    upsert_workflow_definition,
)
from autoclaw.persistence import PolicyRevisionModel, RoleRevisionModel, WorkflowRevisionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

type DefinitionInput = RoleDefinitionInput | PolicyDefinitionInput | WorkflowDefinitionInput
type UpsertDefinitionFn = Callable[
    [AsyncSession, DefinitionInput, str],
    Awaitable[int],
]
type LoadCurrentDefinitionFn = Callable[
    [AsyncSession, str],
    Awaitable[tuple[int, str]],
]
type LoadRevisionHistoryFn = Callable[
    [AsyncSession, str],
    Awaitable[list[tuple[int, str]]],
]


@dataclass(frozen=True)
class DefinitionConcurrencyFixture:
    definition_key: str
    original_description: str
    first_definition: DefinitionInput
    second_definition: DefinitionInput
    upsert_definition: UpsertDefinitionFn
    load_current_definition: LoadCurrentDefinitionFn
    load_revision_history: LoadRevisionHistoryFn


async def _upsert_role_revision(
    session: AsyncSession,
    definition: DefinitionInput,
    source_path: str,
) -> int:
    result = await upsert_role_definition(
        session,
        cast(RoleDefinitionInput, definition),
        source_path=source_path,
    )
    return result.revision_no


async def _load_current_role_definition(
    session: AsyncSession,
    definition_key: str,
) -> tuple[int, str]:
    current = await load_current_role(session, definition_key)
    return current.revision_no, current.definition.description


async def _load_role_revision_history(
    session: AsyncSession,
    definition_key: str,
) -> list[tuple[int, str]]:
    rows = await session.execute(
        select(
            RoleRevisionModel.revision_no,
            RoleRevisionModel.content_json,
        )
        .where(RoleRevisionModel.role_key == definition_key)
        .order_by(RoleRevisionModel.revision_no.asc())
    )
    return [
        (revision_no, str(content_json["description"])) for revision_no, content_json in rows.all()
    ]


async def _upsert_policy_revision(
    session: AsyncSession,
    definition: DefinitionInput,
    source_path: str,
) -> int:
    result = await upsert_policy_definition(
        session,
        cast(PolicyDefinitionInput, definition),
        source_path=source_path,
    )
    return result.revision_no


async def _load_current_policy_definition(
    session: AsyncSession,
    definition_key: str,
) -> tuple[int, str]:
    current = await load_current_policy(session, definition_key)
    return current.revision_no, current.definition.description


async def _load_policy_revision_history(
    session: AsyncSession,
    definition_key: str,
) -> list[tuple[int, str]]:
    rows = await session.execute(
        select(
            PolicyRevisionModel.revision_no,
            PolicyRevisionModel.content_json,
        )
        .where(PolicyRevisionModel.policy_key == definition_key)
        .order_by(PolicyRevisionModel.revision_no.asc())
    )
    return [
        (revision_no, str(content_json["description"])) for revision_no, content_json in rows.all()
    ]


async def _upsert_workflow_revision(
    session: AsyncSession,
    definition: DefinitionInput,
    source_path: str,
) -> int:
    result = await upsert_workflow_definition(
        session,
        cast(WorkflowDefinitionInput, definition),
        source_path=source_path,
    )
    return result.revision_no


async def _load_current_workflow_definition(
    session: AsyncSession,
    definition_key: str,
) -> tuple[int, str]:
    current = await load_current_workflow(session, definition_key)
    return current.revision_no, current.definition.description


async def _load_workflow_revision_history(
    session: AsyncSession,
    definition_key: str,
) -> list[tuple[int, str]]:
    rows = await session.execute(
        select(
            WorkflowRevisionModel.revision_no,
            WorkflowRevisionModel.content_json,
        )
        .where(WorkflowRevisionModel.workflow_key == definition_key)
        .order_by(WorkflowRevisionModel.revision_no.asc())
    )
    return [
        (revision_no, str(content_json["description"])) for revision_no, content_json in rows.all()
    ]


async def _build_role_concurrency_fixture(
    session: AsyncSession,
    *,
    definition_key: str | None,
    same_key_update: bool,
) -> DefinitionConcurrencyFixture:
    if same_key_update:
        current_role = await load_current_role(session, "planning_lead")
        key = current_role.definition.id
        original_description = current_role.definition.description
        first_definition = current_role.definition.model_copy(
            update={"description": f"{current_role.definition.description} v2"}
        )
    else:
        key = cast(str, definition_key)
        original_description = "Concurrent role revision 1"
        first_definition = RoleDefinitionInput.model_validate(
            {
                "id": key,
                "title": "Concurrent role",
                "description": original_description,
                "allowed_node_kinds": ["worker"],
            }
        )
    return DefinitionConcurrencyFixture(
        definition_key=key,
        original_description=original_description,
        first_definition=first_definition,
        second_definition=first_definition.model_copy(
            update={"description": "Concurrent role revision 2"}
            if not same_key_update
            else {"description": f"{original_description} v2"}
        ),
        upsert_definition=_upsert_role_revision,
        load_current_definition=_load_current_role_definition,
        load_revision_history=_load_role_revision_history,
    )


async def _build_policy_concurrency_fixture(
    session: AsyncSession,
    *,
    definition_key: str | None,
    same_key_update: bool,
) -> DefinitionConcurrencyFixture:
    if same_key_update:
        current_policy = await load_current_policy(session, "standard-worker")
        key = current_policy.definition.id
        original_description = current_policy.definition.description
        first_definition = current_policy.definition.model_copy(
            update={"description": f"{current_policy.definition.description} v2"}
        )
    else:
        key = cast(str, definition_key)
        original_description = "Concurrent policy revision 1"
        first_definition = PolicyDefinitionInput.model_validate(
            {
                "id": key,
                "title": "Concurrent policy",
                "description": original_description,
                "applies_to": ["worker"],
                "budget_spec": {"retry_limit": 1},
            }
        )
    return DefinitionConcurrencyFixture(
        definition_key=key,
        original_description=original_description,
        first_definition=first_definition,
        second_definition=first_definition.model_copy(
            update={"description": "Concurrent policy revision 2"}
            if not same_key_update
            else {"description": f"{original_description} v2"}
        ),
        upsert_definition=_upsert_policy_revision,
        load_current_definition=_load_current_policy_definition,
        load_revision_history=_load_policy_revision_history,
    )


async def _build_workflow_concurrency_fixture(
    session: AsyncSession,
    *,
    definition_key: str | None,
    same_key_update: bool,
) -> DefinitionConcurrencyFixture:
    current_workflow = await load_current_workflow(session, "bounded-change")
    original_description = current_workflow.definition.description
    key = definition_key or current_workflow.definition.id
    first_definition = current_workflow.definition.model_copy(
        update=(
            {"id": key, "description": "Concurrent workflow revision 1"}
            if not same_key_update
            else {"description": f"{current_workflow.definition.description} v2"}
        )
    )
    return DefinitionConcurrencyFixture(
        definition_key=key,
        original_description=original_description,
        first_definition=first_definition,
        second_definition=first_definition.model_copy(
            update={"description": "Concurrent workflow revision 2"}
            if not same_key_update
            else {"description": f"{original_description} v2"}
        ),
        upsert_definition=_upsert_workflow_revision,
        load_current_definition=_load_current_workflow_definition,
        load_revision_history=_load_workflow_revision_history,
    )


async def build_concurrency_fixture(
    session: AsyncSession,
    *,
    definition_kind: str,
    definition_key: str | None = None,
    same_key_update: bool,
) -> DefinitionConcurrencyFixture:
    if definition_kind == "role":
        return await _build_role_concurrency_fixture(
            session,
            definition_key=definition_key,
            same_key_update=same_key_update,
        )
    if definition_kind == "policy":
        return await _build_policy_concurrency_fixture(
            session,
            definition_key=definition_key,
            same_key_update=same_key_update,
        )
    return await _build_workflow_concurrency_fixture(
        session,
        definition_key=definition_key,
        same_key_update=same_key_update,
    )


async def run_two_writer_race(
    session_factory: Any,
    *,
    definition_kind: str,
    fixture: DefinitionConcurrencyFixture,
) -> tuple[int, int]:
    race_release = asyncio.Event()
    first_writer_flushed = asyncio.Event()

    async def first_writer() -> int:
        async with session_factory() as session:
            revision_no = await fixture.upsert_definition(
                session,
                fixture.first_definition,
                f"test://{definition_kind}-first",
            )
            first_writer_flushed.set()
            await race_release.wait()
            await session.commit()
            return revision_no

    async def second_writer() -> int:
        await first_writer_flushed.wait()
        async with session_factory() as session:
            revision_no = await fixture.upsert_definition(
                session,
                fixture.second_definition,
                f"test://{definition_kind}-second",
            )
            await session.commit()
            return revision_no

    first_task = asyncio.create_task(first_writer())
    await first_writer_flushed.wait()
    second_task = asyncio.create_task(second_writer())
    await asyncio.sleep(0.1)
    race_release.set()
    return await asyncio.gather(first_task, second_task)
