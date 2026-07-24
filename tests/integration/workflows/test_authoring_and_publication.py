from __future__ import annotations

from collections.abc import AsyncIterator
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.main import create_app
from banksia.persistence.session import get_db_session
from banksia.workflows import (
    AddMemberOperation,
    NewMember,
    UpdateWorkflowOperation,
    WorkflowPatch,
    WorkflowProvenance,
    parse_workflow,
)
from banksia.workflows.authoring import (
    create_workflow_draft,
    edit_workflow_draft,
    publish_workflow_draft,
    read_workflow_draft,
    undo_workflow_draft,
)
from banksia.workflows.bootstrap import STARTER_WORKFLOW_FILENAMES
from banksia.workflows.catalog import (
    list_workflow_revisions,
    read_current_published_workflow,
    read_current_workflow_provenance,
    search_workflows,
)
from banksia.workflows.publication import publish_workflow_revision
from banksia.workflows.service_errors import (
    WorkflowDraftConflictError,
    WorkflowNotFoundError,
    WorkflowStaleDraftError,
    WorkflowUndoReceiptError,
)
from tests.helpers.workflow_runtime import initialized_workflow_database

REPO_ROOT = Path(__file__).resolve().parents[3]


async def test_bootstrap_exposes_exact_portable_starter_workflow_set(tmp_path: Path) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            workflows = await search_workflows(session)

    assert tuple(item.workflow_id for item in workflows.items) == (
        "autonomous-delivery",
        "evidence-research",
        "reviewed-delivery",
    )
    assert all(item.provenance is WorkflowProvenance.STARTER_SEED for item in workflows.items)

    packaged_root = files("banksia.workflows.resources.starter_workflows")
    tracked_root = REPO_ROOT / "docs-internal/design/appendices/workflow-seeds"
    for filename in STARTER_WORKFLOW_FILENAMES:
        packaged = parse_workflow(
            packaged_root.joinpath(filename).read_bytes(), source_format="yaml"
        )
        tracked = parse_workflow((tracked_root / filename).read_bytes(), source_format="yaml")
        assert packaged == tracked
        packaged_json = packaged.model_dump_json(exclude_none=True)
        assert "provider" not in packaged_json
        assert "capabilities" not in packaged_json


async def test_draft_edit_requires_cas_and_undo_is_single_use(tmp_path: Path) -> None:
    workflow = parse_workflow(
        """
kind: workflow
id: draft-lifecycle
description: Initial description.
lead:
  id: lead
""",
        source_format="yaml",
    )
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            draft = await create_workflow_draft(session, workflow=workflow)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(WorkflowDraftConflictError):
                await create_workflow_draft(session, workflow=workflow)
            await session.rollback()

        async with session_factory() as session:
            edited = await edit_workflow_draft(
                session,
                draft_id=draft.draft_id,
                expected_etag=draft.etag,
                operation=UpdateWorkflowOperation(
                    kind="update_workflow",
                    patch=WorkflowPatch(description="Edited description."),
                ),
            )
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(WorkflowStaleDraftError) as stale:
                await edit_workflow_draft(
                    session,
                    draft_id=draft.draft_id,
                    expected_etag=draft.etag,
                    operation=UpdateWorkflowOperation(
                        kind="update_workflow",
                        patch=WorkflowPatch(description="Stale write."),
                    ),
                )
            assert stale.value.current.etag == edited.draft.etag
            await session.rollback()

        async with session_factory() as session:
            restored = await undo_workflow_draft(
                session,
                draft_id=draft.draft_id,
                expected_etag=edited.draft.etag,
                receipt_id=edited.undo_receipt,
            )
            await session.commit()
            assert restored.workflow.description == "Initial description."

        async with session_factory() as session:
            with pytest.raises(WorkflowUndoReceiptError):
                await undo_workflow_draft(
                    session,
                    draft_id=draft.draft_id,
                    expected_etag=restored.etag,
                    receipt_id=edited.undo_receipt,
                )
            await session.rollback()


async def test_publish_is_immutable_and_seed_refresh_never_replaces_user_current(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            seed = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
            user_workflow = seed.workflow.model_copy(
                update={"description": "User-owned reviewed delivery."}
            )
            user_revision = await publish_workflow_revision(
                session,
                workflow=user_workflow,
                provenance=WorkflowProvenance.USER,
                should_update_current=True,
            )
            await session.commit()

        changed_seed = seed.workflow.model_copy(
            update={"description": "Changed package-owned reviewed delivery."}
        )
        async with session_factory() as session:
            package_revision = await publish_workflow_revision(
                session,
                workflow=changed_seed,
                provenance=WorkflowProvenance.STARTER_SEED,
                should_update_current=False,
                source_path="seed://test/reviewed-delivery.yaml",
            )
            await session.commit()

        async with session_factory() as session:
            converged_revision = await publish_workflow_revision(
                session,
                workflow=changed_seed,
                provenance=WorkflowProvenance.STARTER_SEED,
                should_update_current=False,
                source_path="seed://test/reviewed-delivery.yaml",
            )
            await session.commit()
            current = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
            history = await list_workflow_revisions(
                session,
                workflow_id="reviewed-delivery",
            )
            current_provenance = await read_current_workflow_provenance(
                session,
                workflow_id="reviewed-delivery",
            )

    assert user_revision.revision_no == 2
    assert package_revision.revision_no == 3
    assert converged_revision.revision_no == 3
    assert current.revision_no == 2
    assert current_provenance is WorkflowProvenance.USER
    assert tuple(item.revision_no for item in history.items) == (3, 2, 1)


async def test_undo_never_reuses_a_controller_allocated_member_id(tmp_path: Path) -> None:
    workflow = parse_workflow(
        """
kind: workflow
id: member-id-stability
description: Member identity stability proof.
lead: {id: lead}
""",
        source_format="yaml",
    )
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            draft = await create_workflow_draft(session, workflow=workflow)
            first_add = await edit_workflow_draft(
                session,
                draft_id=draft.draft_id,
                expected_etag=draft.etag,
                operation=AddMemberOperation(
                    kind="add_member",
                    parent_member_id="lead",
                    member=NewMember(title="First allocation"),
                ),
            )
            restored = await undo_workflow_draft(
                session,
                draft_id=draft.draft_id,
                expected_etag=first_add.draft.etag,
                receipt_id=first_add.undo_receipt,
            )
            second_add = await edit_workflow_draft(
                session,
                draft_id=draft.draft_id,
                expected_etag=restored.etag,
                operation=AddMemberOperation(
                    kind="add_member",
                    parent_member_id="lead",
                    member=NewMember(title="Second allocation"),
                ),
            )
            await session.commit()

    assert first_add.draft.workflow.lead.children is not None
    assert first_add.draft.workflow.lead.children[0].id == "member-1"
    assert second_add.draft.workflow.lead.children is not None
    assert second_add.draft.workflow.lead.children[0].id == "member-2"


async def test_publish_draft_removes_only_draft_and_returns_typed_revision(tmp_path: Path) -> None:
    workflow = parse_workflow(
        """
kind: workflow
id: publish-draft
description: Publish this draft.
lead: {id: lead}
""",
        source_format="yaml",
    )
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            draft = await create_workflow_draft(session, workflow=workflow)
            await session.commit()

        async with session_factory() as session:
            published = await publish_workflow_draft(
                session,
                draft_id=draft.draft_id,
                expected_etag=draft.etag,
            )
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(WorkflowNotFoundError):
                await read_workflow_draft(session, draft_id=draft.draft_id)

    assert published.workflow_id == "publish-draft"
    assert published.revision_no == 1


async def test_http_draft_routes_enforce_etag_and_return_current_on_stale(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        app = create_app(should_enable_mcp_mounts=False)

        async def session_dependency() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = session_dependency
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url="http://127.0.0.1:8123",
        ) as client:
            created = await client.post(
                "/workflow-drafts",
                json={
                    "kind": "workflow",
                    "id": "http-authoring",
                    "description": "HTTP authoring proof.",
                    "lead": {"id": "lead"},
                },
            )
            assert created.status_code == 201, created.text
            draft = created.json()
            missing_precondition = await client.patch(
                f"/workflow-drafts/{draft['draft_id']}",
                json={
                    "kind": "update_workflow",
                    "patch": {"description": "Missing precondition."},
                },
            )
            edited = await client.patch(
                f"/workflow-drafts/{draft['draft_id']}",
                headers={"If-Match": created.headers["etag"]},
                json={
                    "kind": "update_workflow",
                    "patch": {"description": "Current edit."},
                },
            )
            stale = await client.patch(
                f"/workflow-drafts/{draft['draft_id']}",
                headers={"If-Match": created.headers["etag"]},
                json={
                    "kind": "update_workflow",
                    "patch": {"description": "Stale edit."},
                },
            )
            published = await client.post(
                f"/workflow-drafts/{draft['draft_id']}/publish",
                headers={"If-Match": edited.headers["etag"]},
            )

    assert created.status_code == 201
    assert created.headers["etag"] == draft["etag"]
    assert missing_precondition.status_code == 428
    assert edited.status_code == 200
    assert stale.status_code == 412
    assert stale.json()["detail"]["current"]["etag"] == edited.headers["etag"]
    assert published.status_code == 200
    assert published.json()["workflow"]["description"] == "Current edit."
