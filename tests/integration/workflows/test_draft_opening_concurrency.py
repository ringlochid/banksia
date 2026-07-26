from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from banksia.workflows import NormalizedWorkflow, normalize_workflow_object
from banksia.workflows.authoring import (
    import_workflow_draft,
    open_workflow_draft,
    publish_workflow_draft,
    read_workflow_catalog_entry,
)
from banksia.workflows.authoring_contracts import (
    CreateWorkflowDraftRequest,
    OpenWorkflowDraftRequest,
    WorkflowDraftOpenRequest,
    WorkflowDraftOpenResult,
)
from banksia.workflows.catalog import (
    read_current_published_workflow,
    search_workflows,
)
from banksia.workflows.service_errors import (
    WorkflowDraftConflictError,
)
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
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
async def test_concurrent_product_creates_have_one_uniqueness_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    workflow_id = _workflow_id("product-create", database_backend)
    request = CreateWorkflowDraftRequest(
        kind="create",
        workflow_id=workflow_id,
        description="Concurrent product creation.",
    )

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        install_statement_gate_interceptor(monkeypatch)
        draft_barrier = TwoPartyBarrier()
        outcomes = await asyncio.gather(
            _open_draft_request_and_commit(
                session_factory,
                request=request,
                draft_gate=draft_barrier,
            ),
            _open_draft_request_and_commit(
                session_factory,
                request=request,
                draft_gate=draft_barrier,
            ),
        )

        successes = tuple(result for result, error in outcomes if error is None)
        errors = tuple(error for _result, error in outcomes if error is not None)
        async with session_factory() as session:
            catalog = await search_workflows(session, query=workflow_id)

    assert len(successes) == 1
    assert successes[0] is not None
    assert successes[0].is_created is True
    assert successes[0].draft.workflow.lead.id == "member-1"
    assert len(errors) == 1
    assert isinstance(errors[0], WorkflowDraftConflictError)
    assert tuple(item.workflow_id for item in catalog.items) == (workflow_id,)
    assert catalog.items[0].published_revision_no is None
    assert catalog.items[0].has_active_draft is True


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_concurrent_product_opens_converge_on_one_exact_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
) -> None:
    workflow_id = GENERIC_WORKFLOW_ID
    request = OpenWorkflowDraftRequest(kind="open", workflow_id=workflow_id)

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        await publish_generic_workflow(session_factory)
        install_statement_gate_interceptor(monkeypatch)
        draft_barrier = TwoPartyBarrier()
        outcomes = await asyncio.gather(
            _open_draft_request_and_commit(
                session_factory,
                request=request,
                draft_gate=draft_barrier,
            ),
            _open_draft_request_and_commit(
                session_factory,
                request=request,
                draft_gate=draft_barrier,
            ),
        )

        results = tuple(result for result, error in outcomes if error is None)
        errors = tuple(error for _result, error in outcomes if error is not None)
        async with session_factory() as session:
            published = await read_current_published_workflow(
                session,
                workflow_id=workflow_id,
            )
            catalog = await search_workflows(session, query=workflow_id)

    assert len(results) == 2
    assert errors == ()
    assert all(result is not None for result in results)
    opened = tuple(result for result in results if result is not None)
    assert sorted(result.is_created for result in opened) == [False, True]
    assert len({result.draft.draft_id for result in opened}) == 1
    assert {result.draft.base_revision_no for result in opened} == {published.revision_no}
    assert all(result.draft.workflow == published.workflow for result in opened)
    assert tuple(item.workflow_id for item in catalog.items) == (workflow_id,)
    assert catalog.items[0].published_revision_no == published.revision_no
    assert catalog.items[0].has_active_draft is True


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
@pytest.mark.parametrize("operation_order", ("open_before_publish", "publish_before_open"))
async def test_publish_and_open_race_has_deterministic_linearization_and_refetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_backend: DatabaseBackend,
    operation_order: str,
) -> None:
    workflow_id = _workflow_id("publish-open", database_backend)
    workflow = _workflow(workflow_id, description="Publish and open race.")

    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with session_factory() as session:
            initial_draft = (await import_workflow_draft(session, workflow=workflow)).draft
            await session.commit()

        install_statement_gate_interceptor(monkeypatch)
        paused_operation_arrived = asyncio.Event()
        allow_paused_operation = asyncio.Event()
        gate = ControlledGate(
            arrived=paused_operation_arrived,
            release=allow_paused_operation,
        )
        if operation_order == "open_before_publish":
            publish_task = asyncio.create_task(
                _publish_draft_and_commit(
                    session_factory,
                    draft_id=initial_draft.draft_id,
                    etag=initial_draft.etag,
                    draft_gate=gate,
                )
            )
            await paused_operation_arrived.wait()
            open_outcome = await _open_draft_request_and_commit(
                session_factory,
                request=OpenWorkflowDraftRequest(kind="open", workflow_id=workflow_id),
            )
            allow_paused_operation.set()
            publish_outcome = await publish_task
        else:
            open_task = asyncio.create_task(
                _open_draft_request_and_commit(
                    session_factory,
                    request=OpenWorkflowDraftRequest(kind="open", workflow_id=workflow_id),
                    draft_gate=gate,
                )
            )
            await paused_operation_arrived.wait()
            publish_outcome = await _publish_draft_and_commit(
                session_factory,
                draft_id=initial_draft.draft_id,
                etag=initial_draft.etag,
            )
            allow_paused_operation.set()
            open_outcome = await open_task

        async with session_factory() as session:
            published = await read_current_published_workflow(
                session,
                workflow_id=workflow_id,
            )
            detail = await read_workflow_catalog_entry(session, workflow_id=workflow_id)

    assert publish_outcome == ("publish", None)
    opened, open_error = open_outcome
    assert open_error is None
    assert opened is not None
    assert published.workflow == workflow
    if operation_order == "publish_before_open":
        assert opened.is_created is True
        assert opened.draft.base_revision_no == published.revision_no
        assert opened.draft.workflow == published.workflow
        assert detail.active_draft == opened.draft
    else:
        assert opened.is_created is False
        assert opened.draft == initial_draft
        assert detail.active_draft is None
    assert detail.published_revision_no == published.revision_no
    assert detail.published is not None
    assert detail.published.workflow == published.workflow


async def _open_draft_request_and_commit(
    session_factory: AsyncSessionFactory,
    *,
    request: WorkflowDraftOpenRequest,
    draft_gate: TwoPartyBarrier | ControlledGate | None = None,
) -> tuple[WorkflowDraftOpenResult | None, Exception | None]:
    async with session_factory() as session:
        if draft_gate is not None:
            arm_statement_gate(
                session,
                table_name="workflow_drafts",
                waiter=draft_gate,
            )
        try:
            result = await open_workflow_draft(session, request=request)
            await session.commit()
            return result, None
        except Exception as exc:
            await session.rollback()
            return None, exc


async def _publish_draft_and_commit(
    session_factory: AsyncSessionFactory,
    *,
    draft_id: str,
    etag: str,
    draft_gate: TwoPartyBarrier | ControlledGate | None = None,
) -> tuple[str, Exception | None]:
    async with session_factory() as session:
        if draft_gate is not None:
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
