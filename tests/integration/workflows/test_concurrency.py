from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from banksia.workflows import (
    NormalizedWorkflow,
    PublishedWorkflowRevision,
    UpdateWorkflowOperation,
    WorkflowPatch,
    WorkflowProvenance,
    normalize_workflow_object,
)
from banksia.workflows.authoring import (
    edit_workflow_draft,
    import_workflow_draft,
    publish_workflow_draft,
    read_workflow_draft,
)
from banksia.workflows.bootstrap import seed_starter_workflows
from banksia.workflows.catalog import (
    list_workflow_revisions,
    read_current_published_workflow,
)
from banksia.workflows.publication import publish_workflow_revision
from banksia.workflows.service_errors import (
    WorkflowNotFoundError,
    WorkflowStaleDraftError,
)
from tests.helpers.workflow_concurrency import (
    ControlledGate,
    DatabaseBackend,
    TwoPartyBarrier,
    arm_statement_gate,
    install_statement_gate_interceptor,
    workflow_database,
)
from tests.helpers.workflow_runtime import AsyncSessionFactory


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_concurrent_distinct_publications_allocate_ordered_revisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    workflow_id = _workflow_id("distinct-publication", database_backend)
    first = _workflow(workflow_id, description="First concurrent publication.")
    second = first.model_copy(update={"description": "Second concurrent publication."})

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        install_statement_gate_interceptor(monkeypatch)
        owner_barrier = TwoPartyBarrier()
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

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        install_statement_gate_interceptor(monkeypatch)
        owner_barrier = TwoPartyBarrier()
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

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with session_factory() as session:
            draft = (await import_workflow_draft(session, workflow=workflow)).draft
            await session.commit()

        install_statement_gate_interceptor(monkeypatch)
        draft_barrier = TwoPartyBarrier()
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

        async with session_factory() as session:
            if successful_operations == ("edit",):
                assert isinstance(rejected_operations[0], WorkflowStaleDraftError)
                current_draft = await read_workflow_draft(session, draft_id=draft.draft_id)
                assert current_draft.workflow.description == "Edited race winner."
                with pytest.raises(WorkflowNotFoundError):
                    await read_current_published_workflow(session, workflow_id=workflow_id)
            else:
                assert isinstance(rejected_operations[0], WorkflowNotFoundError)
                with pytest.raises(WorkflowNotFoundError):
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

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with session_factory() as session:
            packaged = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )

        seed_before_owner_lock = asyncio.Event()
        allow_seed_to_lock = asyncio.Event()
        install_statement_gate_interceptor(monkeypatch)
        monkeypatch.setattr(
            bootstrap_module,
            "STARTER_WORKFLOW_FILENAMES",
            ("reviewed-delivery.yaml",),
        )
        seed_gate = ControlledGate(
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

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        await _publish_and_commit(session_factory, workflow=published_workflow)
        install_statement_gate_interceptor(monkeypatch)
        async with session_factory() as session:
            outer_draft = (await import_workflow_draft(session, workflow=draft_workflow)).draft
            arm_statement_gate(
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


async def _publish_and_commit(
    session_factory: AsyncSessionFactory,
    *,
    workflow: NormalizedWorkflow,
    owner_gate: TwoPartyBarrier | ControlledGate | None = None,
) -> PublishedWorkflowRevision:
    async with session_factory() as session:
        if owner_gate is not None:
            arm_statement_gate(
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
    owner_gate: ControlledGate | None = None,
) -> None:
    async with session_factory() as session:
        if owner_gate is not None:
            arm_statement_gate(
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
    draft_gate: TwoPartyBarrier,
) -> tuple[str, Exception | None]:
    async with session_factory() as session:
        arm_statement_gate(
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
    draft_gate: TwoPartyBarrier,
) -> tuple[str, Exception | None]:
    async with session_factory() as session:
        arm_statement_gate(
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
