from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from banksia.persistence.session import create_runtime_schema_tables
from banksia.workflows import (
    NormalizedWorkflow,
    PublishedWorkflowRevision,
    UpdateWorkflowOperation,
    WorkflowPatch,
    WorkflowProvenance,
    normalize_workflow_object,
)
from banksia.workflows.authoring import (
    create_workflow_draft,
    edit_workflow_draft,
    publish_workflow_draft,
    read_workflow_draft,
)
from banksia.workflows.bootstrap import seed_starter_workflows
from banksia.workflows.catalog import (
    list_workflow_revisions,
    read_current_published_workflow,
)
from banksia.workflows.publication import publish_workflow_revision
from banksia.workflows.service_errors import WorkflowServiceError
from tests.helpers.workflow_runtime import (
    AsyncSessionFactory,
    initialized_workflow_database,
)

type DatabaseBackend = Literal["sqlite", "postgresql"]


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_concurrent_distinct_publications_allocate_ordered_revisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    workflow_id = _workflow_id("distinct-publication", database_backend)
    first = _workflow(workflow_id, description="First concurrent publication.")
    second = first.model_copy(update={"description": "Second concurrent publication."})

    async with _workflow_database(tmp_path, backend=database_backend) as session_factory:
        _install_statement_gate_interceptor(monkeypatch)
        owner_barrier = _TwoPartyBarrier()
        revisions = await asyncio.gather(
            _publish_and_commit(
                session_factory,
                workflow=first,
                owner_gate=owner_barrier,
            ),
            _publish_and_commit(
                session_factory,
                workflow=second,
                owner_gate=owner_barrier,
            ),
        )

        async with session_factory() as session:
            history = await list_workflow_revisions(session, workflow_id=workflow_id)
            current = await read_current_published_workflow(session, workflow_id=workflow_id)

    assert sorted(revision.revision_no for revision in revisions) == [1, 2]
    assert tuple(revision.revision_no for revision in history.items) == (2, 1)
    assert current.revision_no == 2
    assert current.workflow.description in {
        "First concurrent publication.",
        "Second concurrent publication.",
    }


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_concurrent_identical_publications_converge_on_one_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    workflow_id = _workflow_id("identical-publication", database_backend)
    workflow = _workflow(workflow_id, description="One canonical publication.")

    async with _workflow_database(tmp_path, backend=database_backend) as session_factory:
        _install_statement_gate_interceptor(monkeypatch)
        owner_barrier = _TwoPartyBarrier()
        revisions = await asyncio.gather(
            _publish_and_commit(
                session_factory,
                workflow=workflow,
                owner_gate=owner_barrier,
            ),
            _publish_and_commit(
                session_factory,
                workflow=workflow,
                owner_gate=owner_barrier,
            ),
        )

        async with session_factory() as session:
            history = await list_workflow_revisions(session, workflow_id=workflow_id)
            current = await read_current_published_workflow(session, workflow_id=workflow_id)

    assert tuple(revision.revision_no for revision in revisions) == (1, 1)
    assert tuple(revision.revision_no for revision in history.items) == (1,)
    assert current.revision_no == 1


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_same_etag_edit_and_publish_have_exactly_one_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    workflow_id = _workflow_id("draft-cas", database_backend)
    workflow = _workflow(workflow_id, description="Draft race baseline.")

    async with _workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with session_factory() as session:
            draft = await create_workflow_draft(session, workflow=workflow)
            await session.commit()

        _install_statement_gate_interceptor(monkeypatch)
        draft_barrier = _TwoPartyBarrier()
        outcomes = await asyncio.gather(
            _edit_and_commit(
                session_factory,
                draft_id=draft.draft_id,
                etag=draft.etag,
                draft_gate=draft_barrier,
            ),
            _publish_draft_and_commit(
                session_factory,
                draft_id=draft.draft_id,
                etag=draft.etag,
                draft_gate=draft_barrier,
            ),
        )

        successful_operations = tuple(name for name, error in outcomes if error is None)
        rejected_operations = tuple(error for _name, error in outcomes if error is not None)
        assert len(successful_operations) == 1
        assert len(rejected_operations) == 1
        assert isinstance(rejected_operations[0], WorkflowServiceError)

        async with session_factory() as session:
            if successful_operations == ("edit",):
                current_draft = await read_workflow_draft(session, draft_id=draft.draft_id)
                assert current_draft.workflow.description == "Edited race winner."
                with pytest.raises(WorkflowServiceError):
                    await read_current_published_workflow(session, workflow_id=workflow_id)
            else:
                with pytest.raises(WorkflowServiceError):
                    await read_workflow_draft(session, draft_id=draft.draft_id)
                published = await read_current_published_workflow(
                    session,
                    workflow_id=workflow_id,
                )
                assert published.workflow.description == "Draft race baseline."


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_seed_refresh_cannot_replace_concurrent_user_current_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    import banksia.workflows.bootstrap as bootstrap_module

    async with _workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with session_factory() as session:
            packaged = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )

        seed_before_owner_lock = asyncio.Event()
        allow_seed_to_lock = asyncio.Event()
        _install_statement_gate_interceptor(monkeypatch)
        monkeypatch.setattr(
            bootstrap_module,
            "STARTER_WORKFLOW_FILENAMES",
            ("reviewed-delivery.yaml",),
        )
        seed_gate = _ControlledGate(
            arrived=seed_before_owner_lock,
            release=allow_seed_to_lock,
        )
        seed_task = asyncio.create_task(
            _seed_and_commit(session_factory, owner_gate=seed_gate),
            name="seed",
        )
        await seed_before_owner_lock.wait()

        try:
            user_revision = await _publish_and_commit(
                session_factory,
                workflow=packaged.workflow.model_copy(
                    update={"description": "Concurrent user-owned Workflow."}
                ),
            )
        finally:
            allow_seed_to_lock.set()
            await asyncio.gather(seed_task, return_exceptions=True)
        await seed_task

        async with session_factory() as session:
            current = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
            history = await list_workflow_revisions(
                session,
                workflow_id="reviewed-delivery",
            )

    assert user_revision.revision_no == 2
    assert current.revision_no == user_revision.revision_no
    assert current.workflow.description == "Concurrent user-owned Workflow."
    assert tuple(revision.revision_no for revision in history.items) == (2, 1)


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_revision_collision_savepoint_preserves_outer_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    published_id = _workflow_id("savepoint-published", database_backend)
    draft_id = _workflow_id("savepoint-draft", database_backend)
    published_workflow = _workflow(published_id, description="Existing publication.")
    draft_workflow = _workflow(draft_id, description="Outer transaction draft.")

    async with _workflow_database(tmp_path, backend=database_backend) as session_factory:
        await _publish_and_commit(session_factory, workflow=published_workflow)
        _install_statement_gate_interceptor(monkeypatch)
        async with session_factory() as session:
            outer_draft = await create_workflow_draft(session, workflow=draft_workflow)
            _arm_statement_gate(
                session,
                table_name="workflow_revisions",
                should_return_none=True,
            )
            converged = await publish_workflow_revision(
                session,
                workflow=published_workflow,
                provenance=WorkflowProvenance.USER,
                should_update_current=True,
            )
            await session.commit()

        async with session_factory() as session:
            persisted_draft = await read_workflow_draft(
                session,
                draft_id=outer_draft.draft_id,
            )
            history = await list_workflow_revisions(session, workflow_id=published_id)

    assert converged.revision_no == 1
    assert persisted_draft.workflow_id == draft_id
    assert tuple(revision.revision_no for revision in history.items) == (1,)


def _install_statement_gate_interceptor(monkeypatch: pytest.MonkeyPatch) -> None:
    original_execute = AsyncSession.execute
    original_scalar = AsyncSession.scalar

    async def execute_after_gate(
        session: AsyncSession,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        await _consume_statement_gate(session, statement=statement)
        return await original_execute(session, statement, *args, **kwargs)

    async def scalar_after_gate(
        session: AsyncSession,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        should_return_none = await _consume_statement_gate(session, statement=statement)
        if should_return_none:
            return None
        return await original_scalar(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", execute_after_gate)
    monkeypatch.setattr(AsyncSession, "scalar", scalar_after_gate)


async def _consume_statement_gate(session: AsyncSession, *, statement: Any) -> bool:
    gate = session.info.get("workflow_concurrency_statement_gate")
    if not isinstance(gate, _StatementGate) or gate.table_name not in str(statement):
        return False
    session.info.pop("workflow_concurrency_statement_gate")
    if gate.waiter is not None:
        await gate.waiter.wait()
    return gate.should_return_none


def _arm_statement_gate(
    session: AsyncSession,
    *,
    table_name: str,
    waiter: _TwoPartyBarrier | _ControlledGate | None = None,
    should_return_none: bool = False,
) -> None:
    session.info["workflow_concurrency_statement_gate"] = _StatementGate(
        table_name=table_name,
        waiter=waiter,
        should_return_none=should_return_none,
    )


class _TwoPartyBarrier:
    def __init__(self) -> None:
        self._arrivals = 0
        self._release = asyncio.Event()

    async def wait(self) -> None:
        self._arrivals += 1
        if self._arrivals == 2:
            self._release.set()
        await self._release.wait()


class _ControlledGate:
    def __init__(self, *, arrived: asyncio.Event, release: asyncio.Event) -> None:
        self._arrived = arrived
        self._release = release

    async def wait(self) -> None:
        self._arrived.set()
        await self._release.wait()


class _StatementGate:
    def __init__(
        self,
        *,
        table_name: str,
        waiter: _TwoPartyBarrier | _ControlledGate | None,
        should_return_none: bool,
    ) -> None:
        self.table_name = table_name
        self.waiter = waiter
        self.should_return_none = should_return_none


async def _publish_and_commit(
    session_factory: AsyncSessionFactory,
    *,
    workflow: NormalizedWorkflow,
    owner_gate: _TwoPartyBarrier | _ControlledGate | None = None,
) -> PublishedWorkflowRevision:
    async with session_factory() as session:
        if owner_gate is not None:
            _arm_statement_gate(
                session,
                table_name="workflow_definitions",
                waiter=owner_gate,
            )
        published = await publish_workflow_revision(
            session,
            workflow=workflow,
            provenance=WorkflowProvenance.USER,
            should_update_current=True,
        )
        await session.commit()
        return published


async def _seed_and_commit(
    session_factory: AsyncSessionFactory,
    *,
    owner_gate: _ControlledGate | None = None,
) -> None:
    async with session_factory() as session:
        if owner_gate is not None:
            _arm_statement_gate(
                session,
                table_name="workflow_definitions",
                waiter=owner_gate,
            )
        await seed_starter_workflows(session)
        await session.commit()


async def _edit_and_commit(
    session_factory: AsyncSessionFactory,
    *,
    draft_id: str,
    etag: str,
    draft_gate: _TwoPartyBarrier,
) -> tuple[str, Exception | None]:
    async with session_factory() as session:
        _arm_statement_gate(
            session,
            table_name="workflow_drafts",
            waiter=draft_gate,
        )
        try:
            await edit_workflow_draft(
                session,
                draft_id=draft_id,
                expected_etag=etag,
                operation=UpdateWorkflowOperation(
                    kind="update_workflow",
                    patch=WorkflowPatch(description="Edited race winner."),
                ),
            )
            await session.commit()
            return "edit", None
        except Exception as exc:
            await session.rollback()
            return "edit", exc


async def _publish_draft_and_commit(
    session_factory: AsyncSessionFactory,
    *,
    draft_id: str,
    etag: str,
    draft_gate: _TwoPartyBarrier,
) -> tuple[str, Exception | None]:
    async with session_factory() as session:
        _arm_statement_gate(
            session,
            table_name="workflow_drafts",
            waiter=draft_gate,
        )
        try:
            await publish_workflow_draft(
                session,
                draft_id=draft_id,
                expected_etag=etag,
            )
            await session.commit()
            return "publish", None
        except Exception as exc:
            await session.rollback()
            return "publish", exc


@asynccontextmanager
async def _workflow_database(
    tmp_path: Path,
    *,
    backend: DatabaseBackend,
) -> AsyncIterator[AsyncSessionFactory]:
    if backend == "sqlite":
        async with initialized_workflow_database(tmp_path) as session_factory:
            yield session_factory
        return

    database_url = os.environ.get("BANKSIA_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("BANKSIA_TEST_POSTGRES_URL not set")
    url = make_url(database_url)
    if "test" not in (url.database or "").casefold():
        pytest.skip("Workflow concurrency requires an explicitly disposable test database")
    postgres_schema = f"banksia_workflow_concurrency_{uuid4().hex}"
    engine = create_async_engine(
        url.set(drivername="postgresql+asyncpg"),
        pool_pre_ping=True,
        execution_options={"schema_translate_map": {None: postgres_schema}},
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
    schema_created = False
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'CREATE SCHEMA "{postgres_schema}"')
            await connection.run_sync(create_runtime_schema_tables)
        schema_created = True
        await _seed_and_commit(session_factory)
        yield session_factory
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA "{postgres_schema}" CASCADE')
        await engine.dispose()


def _workflow(workflow_id: str, *, description: str) -> NormalizedWorkflow:
    return normalize_workflow_object(
        {
            "kind": "workflow",
            "id": workflow_id,
            "description": description,
            "lead": {"id": "lead"},
        }
    )


def _workflow_id(prefix: str, backend: DatabaseBackend) -> str:
    return f"{prefix}-{backend}-{uuid4().hex}"
