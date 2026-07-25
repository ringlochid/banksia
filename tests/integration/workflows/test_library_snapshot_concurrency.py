from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from banksia.workflows import UpdateWorkflowOperation, WorkflowPatch
from banksia.workflows.authoring import (
    discard_workflow_draft,
    edit_workflow_draft,
    open_workflow_draft,
    publish_workflow_draft,
    read_workflow_catalog_entry,
)
from banksia.workflows.authoring_contracts import OpenWorkflowDraftRequest, WorkflowGetResponse
from banksia.workflows.contracts import WorkflowProvenance
from banksia.workflows.publication import publish_workflow_revision
from tests.helpers.workflow_concurrency import (
    ControlledGate,
    DatabaseBackend,
    arm_statement_gate,
    install_statement_gate_interceptor,
    workflow_database,
)
from tests.helpers.workflow_runtime import AsyncSessionFactory


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
@pytest.mark.parametrize(
    "mutation_name",
    ("open", "edit", "publish", "discard"),
)
async def test_workflow_detail_semantic_core_stays_coherent_across_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
    mutation_name: str,
) -> None:
    workflow_id = f"detail-{mutation_name}-{database_backend}-{uuid4().hex}"
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        initial = await _prepare_detail_race(
            session_factory,
            workflow_id=workflow_id,
            mutation_name=mutation_name,
        )
        core_read = asyncio.Event()
        allow_history_read = asyncio.Event()
        install_statement_gate_interceptor(monkeypatch)
        detail_task = asyncio.create_task(
            _read_detail_after_core_gate(
                session_factory,
                workflow_id=workflow_id,
                core_read=core_read,
                allow_history_read=allow_history_read,
            )
        )
        await core_read.wait()

        await _apply_mutation(
            session_factory,
            mutation_name=mutation_name,
            workflow_id=workflow_id,
            draft_id=initial.active_draft.draft_id if initial.active_draft is not None else "",
            etag=initial.active_draft.etag if initial.active_draft is not None else "",
        )
        allow_history_read.set()
        detail = await detail_task

        async with session_factory() as session:
            refreshed = await read_workflow_catalog_entry(session, workflow_id=workflow_id)

    assert detail == initial
    assert all(
        revision.revision_no <= (detail.published_revision_no or 0) for revision in detail.revisions
    )
    if mutation_name == "open":
        assert detail.active_draft is None
        assert refreshed.active_draft is not None
    elif mutation_name == "edit":
        assert detail.active_draft is not None
        assert refreshed.active_draft is not None
        assert refreshed.active_draft.etag != detail.active_draft.etag
        assert refreshed.description == "Concurrent edited description."
    elif mutation_name == "publish":
        assert detail.active_draft is not None
        assert refreshed.active_draft is None
        assert refreshed.published_revision_no == (detail.published_revision_no or 0) + 1
    else:
        assert detail.active_draft is not None
        assert refreshed.active_draft is None
        assert refreshed.published_revision_no == detail.published_revision_no


async def _prepare_detail_race(
    session_factory: AsyncSessionFactory,
    *,
    workflow_id: str,
    mutation_name: str,
) -> WorkflowGetResponse:
    async with session_factory() as session:
        source = await read_workflow_catalog_entry(
            session,
            workflow_id="reviewed-delivery",
            should_include_revisions=False,
        )
        assert source.published is not None
        workflow = source.published.workflow.model_copy(
            update={
                "id": workflow_id,
                "description": "Detail race baseline.",
            }
        )
        await publish_workflow_revision(
            session,
            workflow=workflow,
            provenance=WorkflowProvenance.USER,
            should_update_current=True,
        )
        if mutation_name != "open":
            opened = await open_workflow_draft(
                session,
                request=OpenWorkflowDraftRequest(kind="open", workflow_id=workflow_id),
            )
            if mutation_name == "publish":
                await edit_workflow_draft(
                    session,
                    draft_id=opened.draft.draft_id,
                    expected_etag=opened.draft.etag,
                    operation=UpdateWorkflowOperation(
                        kind="update_workflow",
                        patch=WorkflowPatch(description="Draft publication candidate."),
                    ),
                )
        await session.commit()

    async with session_factory() as session:
        return await read_workflow_catalog_entry(session, workflow_id=workflow_id)


async def _read_detail_after_core_gate(
    session_factory: AsyncSessionFactory,
    *,
    workflow_id: str,
    core_read: asyncio.Event,
    allow_history_read: asyncio.Event,
) -> WorkflowGetResponse:
    async with session_factory() as session:
        arm_statement_gate(
            session,
            table_name="workflow_library_ids",
            waiter=ControlledGate(arrived=core_read, release=allow_history_read),
            timing="after",
        )
        return await read_workflow_catalog_entry(session, workflow_id=workflow_id)


async def _apply_mutation(
    session_factory: AsyncSessionFactory,
    *,
    mutation_name: str,
    workflow_id: str,
    draft_id: str,
    etag: str,
) -> None:
    async with session_factory() as session:
        if mutation_name == "open":
            await open_workflow_draft(
                session,
                request=OpenWorkflowDraftRequest(kind="open", workflow_id=workflow_id),
            )
        elif mutation_name == "edit":
            await edit_workflow_draft(
                session,
                draft_id=draft_id,
                expected_etag=etag,
                operation=UpdateWorkflowOperation(
                    kind="update_workflow",
                    patch=WorkflowPatch(description="Concurrent edited description."),
                ),
            )
        elif mutation_name == "publish":
            await publish_workflow_draft(
                session,
                draft_id=draft_id,
                expected_etag=etag,
            )
        else:
            await discard_workflow_draft(
                session,
                draft_id=draft_id,
                expected_etag=etag,
            )
        await session.commit()
