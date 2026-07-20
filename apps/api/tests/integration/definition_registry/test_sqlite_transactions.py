from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from threading import Event, Thread, current_thread
from typing import Any, cast

import pytest
from autoclaw.definitions.contracts.registry import RoleDefinitionInput
from autoclaw.definitions.registry import (
    load_current_role,
    seed_definition_registry,
    upsert_role_definition,
)
from autoclaw.definitions.registry.revisions.ids import canonical_content_hash, role_revision_id
from autoclaw.definitions.registry.revisions.types import PreparedDefinitionRevisionUpsert
from autoclaw.definitions.registry.revisions.writes import (
    insert_definition_revision,
    load_definition_for_update,
)
from autoclaw.persistence import RoleDefinitionModel, RoleRevisionModel
from sqlalchemy import Engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)
from tests.integration.definition_registry.concurrency_support import (
    DefinitionConcurrencyFixture,
    DefinitionInput,
    build_concurrency_fixture,
)

type SyncSessionFactory = sessionmaker[Session]


@dataclass(frozen=True)
class SyncRegistryDatabase:
    engine: Engine
    session_factory: SyncSessionFactory


def test_sqlite_released_savepoints_follow_outer_rollback_and_commit(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="outer-transaction.sqlite")
    session_factory = sessionmaker(engine, expire_on_commit=False)
    try:
        run_async(write_new_role(session_factory, should_commit=False))
        assert read_role_pointer(session_factory, role_key="transaction-role") is None

        run_async(write_new_role(session_factory, should_commit=True))
        assert read_role_pointer(session_factory, role_key="transaction-role") == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("definition_kind", ("role", "policy", "workflow"))
def test_sqlite_concurrent_new_keys_create_ordered_revisions(
    tmp_path: Path,
    definition_kind: str,
) -> None:
    with sync_registry_database(tmp_path, name=f"new-{definition_kind}.sqlite") as database:
        fixture = run_async(
            build_sync_concurrency_fixture(
                database.session_factory,
                definition_kind=definition_kind,
                definition_key=f"concurrent-{definition_kind}-definition",
                same_key_update=False,
            )
        )

        revision_numbers = run_sync_writer_race(
            database,
            definition_kind=definition_kind,
            fixture=fixture,
        )
        current_revision, current_description, history = run_async(
            read_registry_state(database.session_factory, fixture)
        )

    assert revision_numbers == (1, 2)
    assert current_revision == 2
    assert current_description == fixture.second_definition.description
    assert history == [
        (1, fixture.first_definition.description),
        (2, fixture.second_definition.description),
    ]


@pytest.mark.parametrize("definition_kind", ("role", "policy", "workflow"))
def test_sqlite_concurrent_identical_updates_reuse_one_revision(
    tmp_path: Path,
    definition_kind: str,
) -> None:
    with sync_registry_database(tmp_path, name=f"identical-{definition_kind}.sqlite") as database:
        fixture = run_async(
            build_sync_concurrency_fixture(
                database.session_factory,
                definition_kind=definition_kind,
                definition_key=None,
                same_key_update=True,
            )
        )

        revision_numbers = run_sync_writer_race(
            database,
            definition_kind=definition_kind,
            fixture=fixture,
        )
        current_revision, current_description, history = run_async(
            read_registry_state(database.session_factory, fixture)
        )

    assert revision_numbers == (2, 2)
    assert current_revision == 2
    assert current_description == fixture.second_definition.description
    assert history == [
        (1, fixture.original_description),
        (2, fixture.second_definition.description),
    ]


def test_sqlite_registry_savepoint_rollback_and_unique_convergence(
    tmp_path: Path,
) -> None:
    with sync_registry_database(tmp_path, name="savepoint.sqlite") as database:
        revision_two_definition = run_async(
            create_committed_role_revision(database.session_factory)
        )
        set_role_current_revision(database.session_factory, revision_no=1)

        converged_revision = run_async(
            collide_role_revision(
                database.session_factory,
                revision_two_definition,
                should_match_existing=True,
            )
        )
        assert converged_revision == 2
        assert read_role_pointer(database.session_factory) == 2
        assert count_role_revisions(database.session_factory) == 2

        set_role_current_revision(database.session_factory, revision_no=1)
        with pytest.raises(IntegrityError):
            run_async(
                collide_role_revision(
                    database.session_factory,
                    revision_two_definition,
                    should_match_existing=False,
                )
            )

        assert read_role_pointer(database.session_factory) == 1
        assert count_role_revisions(database.session_factory) == 2


@contextmanager
def sync_registry_database(
    tmp_path: Path,
    *,
    name: str,
) -> Iterator[SyncRegistryDatabase]:
    engine = create_runtime_schema_engine(tmp_path, name=name)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    database = SyncRegistryDatabase(engine=engine, session_factory=session_factory)
    try:
        run_async(seed_registry(session_factory))
        yield database
    finally:
        engine.dispose()


async def seed_registry(session_factory: SyncSessionFactory) -> None:
    async with SyncSessionAdapter(session_factory) as adapter:
        await seed_definition_registry(cast(AsyncSession, adapter))
        await adapter.commit()


async def write_new_role(
    session_factory: SyncSessionFactory,
    *,
    should_commit: bool,
) -> None:
    definition = RoleDefinitionInput.model_validate(
        {
            "id": "transaction-role",
            "title": "Transaction role",
            "description": "Proves the outer transaction owns released savepoints.",
            "allowed_node_kinds": ["worker"],
        }
    )
    async with SyncSessionAdapter(session_factory) as adapter:
        await upsert_role_definition(
            cast(AsyncSession, adapter),
            definition,
            source_path="test://transaction-role",
        )
        if should_commit:
            await adapter.commit()


async def build_sync_concurrency_fixture(
    session_factory: SyncSessionFactory,
    *,
    definition_kind: str,
    definition_key: str | None,
    same_key_update: bool,
) -> DefinitionConcurrencyFixture:
    async with SyncSessionAdapter(session_factory) as adapter:
        return await build_concurrency_fixture(
            cast(AsyncSession, adapter),
            definition_kind=definition_kind,
            definition_key=definition_key,
            same_key_update=same_key_update,
        )


def run_sync_writer_race(
    database: SyncRegistryDatabase,
    *,
    definition_kind: str,
    fixture: DefinitionConcurrencyFixture,
) -> tuple[int, int]:
    first_writer_flushed = Event()
    second_writer_dml_started = Event()
    release_first_writer = Event()
    results: Queue[tuple[str, int | BaseException]] = Queue()
    second_writer: Thread

    def observe_second_writer_dml(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        is_executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, is_executemany
        if current_thread() is second_writer and is_registry_dml(statement):
            second_writer_dml_started.set()

    event.listen(database.engine, "before_cursor_execute", observe_second_writer_dml)
    first_writer = Thread(
        target=run_thread_writer,
        name=f"registry-{definition_kind}-first",
        args=(
            results,
            "first",
            lambda: writer_transaction(
                database.session_factory,
                fixture=fixture,
                definition=fixture.first_definition,
                source_path=f"test://{definition_kind}-first",
                flushed=first_writer_flushed,
                release=release_first_writer,
            ),
        ),
    )
    second_writer = Thread(
        target=run_thread_writer,
        name=f"registry-{definition_kind}-second",
        args=(
            results,
            "second",
            lambda: writer_transaction(
                database.session_factory,
                fixture=fixture,
                definition=fixture.second_definition,
                source_path=f"test://{definition_kind}-second",
            ),
        ),
    )
    try:
        first_writer.start()
        require_event(first_writer_flushed, "first registry writer did not flush")
        second_writer.start()
        require_event(second_writer_dml_started, "second registry writer did not reach DML")
    finally:
        release_first_writer.set()
        first_writer.join(timeout=5)
        second_writer.join(timeout=5)
        event.remove(database.engine, "before_cursor_execute", observe_second_writer_dml)

    if first_writer.is_alive() or second_writer.is_alive():
        raise TimeoutError("registry writer threads did not stop")
    return ordered_writer_results(results)


async def writer_transaction(
    session_factory: SyncSessionFactory,
    *,
    fixture: DefinitionConcurrencyFixture,
    definition: DefinitionInput,
    source_path: str,
    flushed: Event | None = None,
    release: Event | None = None,
) -> int:
    async with SyncSessionAdapter(session_factory) as adapter:
        revision_no = await fixture.upsert_definition(
            cast(AsyncSession, adapter),
            definition,
            source_path,
        )
        if flushed is not None:
            flushed.set()
        if release is not None and not release.wait(timeout=5):
            raise TimeoutError("registry race release was not signalled")
        await adapter.commit()
        return revision_no


def run_thread_writer(
    results: Queue[tuple[str, int | BaseException]],
    label: str,
    build_transaction: Callable[[], Coroutine[Any, Any, int]],
) -> None:
    try:
        results.put((label, run_async(build_transaction())))
    except BaseException as exc:
        results.put((label, exc))


def ordered_writer_results(results: Queue[tuple[str, int | BaseException]]) -> tuple[int, int]:
    result_by_label = dict(results.get(timeout=1) for _ in range(2))
    for result in result_by_label.values():
        if isinstance(result, BaseException):
            raise result
    return cast(tuple[int, int], (result_by_label["first"], result_by_label["second"]))


def require_event(event_to_wait: Event, failure_message: str) -> None:
    if not event_to_wait.wait(timeout=5):
        raise TimeoutError(failure_message)


def is_registry_dml(statement: str) -> bool:
    normalized = statement.lstrip().upper()
    return normalized.startswith(("INSERT", "UPDATE", "DELETE")) and any(
        table_name.upper() in normalized
        for table_name in (
            "workflow_definitions",
            "workflow_revisions",
            "role_definitions",
            "role_revisions",
            "policy_definitions",
            "policy_revisions",
        )
    )


async def read_registry_state(
    session_factory: SyncSessionFactory,
    fixture: DefinitionConcurrencyFixture,
) -> tuple[int, str, list[tuple[int, str]]]:
    async with SyncSessionAdapter(session_factory) as adapter:
        session = cast(AsyncSession, adapter)
        current_revision, current_description = await fixture.load_current_definition(
            session,
            fixture.definition_key,
        )
        history = await fixture.load_revision_history(session, fixture.definition_key)
    return current_revision, current_description, history


async def create_committed_role_revision(
    session_factory: SyncSessionFactory,
) -> RoleDefinitionInput:
    async with SyncSessionAdapter(session_factory) as adapter:
        session = cast(AsyncSession, adapter)
        current = await load_current_role(session, "planning_lead")
        updated_definition = current.definition.model_copy(
            update={"description": f"{current.definition.description} revision two"}
        )
        result = await upsert_role_definition(
            session,
            updated_definition,
            source_path="test://role-revision-two",
        )
        await adapter.commit()
    assert result.revision_no == 2
    return updated_definition


async def collide_role_revision(
    session_factory: SyncSessionFactory,
    revision_two_definition: RoleDefinitionInput,
    *,
    should_match_existing: bool,
) -> int:
    content_json = cast(
        dict[str, object],
        revision_two_definition.model_dump(mode="json", exclude={"kind"}),
    )
    if not should_match_existing:
        content_json = content_json | {"description": "different colliding content"}
    content_hash = canonical_content_hash(content_json)

    async with SyncSessionAdapter(session_factory) as adapter:
        session = cast(AsyncSession, adapter)
        definition_row = await load_definition_for_update(
            session,
            RoleDefinitionModel,
            key_column=RoleDefinitionModel.role_key,
            key="planning_lead",
        )
        assert definition_row is not None
        prepared = PreparedDefinitionRevisionUpsert(
            definition_row=definition_row,
            revision_no=2,
            content_json=content_json,
            content_hash=content_hash,
            should_update_current=True,
        )
        result = await insert_definition_revision(
            session,
            definition_id="planning_lead",
            prepared=prepared,
            revision_model=RoleRevisionModel,
            revision_key_column=RoleRevisionModel.role_key,
            build_revision=lambda: RoleRevisionModel(
                role_revision_id=role_revision_id("planning_lead", 2),
                role_key="planning_lead",
                revision_no=2,
                content_hash=content_hash,
                content_json=content_json,
                source_path="test://collision",
            ),
            build_result=lambda revision_no: revision_no,
        )
        await adapter.commit()
    return result or 2


def set_role_current_revision(
    session_factory: SyncSessionFactory,
    *,
    revision_no: int,
) -> None:
    with session_factory.begin() as session:
        definition = session.get(RoleDefinitionModel, "planning_lead")
        assert definition is not None
        definition.current_revision_no = revision_no


def read_role_pointer(
    session_factory: SyncSessionFactory,
    *,
    role_key: str = "planning_lead",
) -> int | None:
    with session_factory() as session:
        return session.scalar(
            select(RoleDefinitionModel.current_revision_no).where(
                RoleDefinitionModel.role_key == role_key
            )
        )


def count_role_revisions(session_factory: SyncSessionFactory) -> int:
    with session_factory() as session:
        revision_count = session.scalar(
            select(func.count()).where(RoleRevisionModel.role_key == "planning_lead")
        )
    assert revision_count is not None
    return revision_count


def run_async[ResultT](operation: Coroutine[Any, Any, ResultT]) -> ResultT:
    return asyncio.run(operation)
