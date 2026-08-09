from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, update

from banksia.persistence.models import (
    WorkflowDefinitionModel,
    WorkflowDraftModel,
    WorkflowRevisionModel,
)
from banksia.workflows.authoring import (
    discard_workflow_draft,
    open_workflow_draft,
    read_workflow_catalog_entry,
)
from banksia.workflows.authoring_contracts import OpenWorkflowDraftRequest
from banksia.workflows.bootstrap import seed_starter_workflows
from banksia.workflows.catalog import (
    read_current_published_workflow,
    read_published_workflow_revision,
)
from banksia.workflows.contracts import WorkflowProvenance
from banksia.workflows.publication import publish_workflow_revision
from banksia.workflows.service_errors import WorkflowNotFoundError
from tests.helpers.product_surface import product_http_client
from tests.helpers.workflow_concurrency import DatabaseBackend, workflow_database


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_draft_only_workflow_is_discoverable_by_id_and_description(
    tmp_path: Path,
    database_backend: DatabaseBackend,
) -> None:
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            created = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "create",
                    "workflow_id": "durable-draft",
                    "description": "Durable draft description.",
                },
            )
            search_by_id = await client.get(
                "/api/workflows",
                params={"q": "durable-draft"},
            )
            search_by_description = await client.get(
                "/api/workflows",
                params={"q": "durable draft description"},
            )
            detail = await client.get("/api/workflows/durable-draft")

    assert created.status_code == 201, created.text
    assert search_by_id.status_code == 200, search_by_id.text
    assert search_by_description.status_code == 200, search_by_description.text
    expected_item = {
        "workflow_id": "durable-draft",
        "description": "Durable draft description.",
        "state": "draft",
        "published_revision_no": None,
        "provenance": "user",
        "has_retired_provider_selection": False,
        "available_actions": ["edit", "remove"],
    }
    assert search_by_id.json()["items"] == [
        expected_item | {"updated_at": search_by_id.json()["items"][0]["updated_at"]}
    ]
    assert search_by_description.json()["items"] == [
        expected_item | {"updated_at": search_by_description.json()["items"][0]["updated_at"]}
    ]
    assert detail.status_code == 200, detail.text
    assert detail.json()["state"] == "draft"
    assert detail.json()["published"] is None
    assert detail.json()["active_draft"] == created.json()["draft"]


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_remove_workflow_releases_identity_and_preserves_history(
    tmp_path: Path,
    database_backend: DatabaseBackend,
) -> None:
    published_id = "deep-research-and-decision-brief"
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            created = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "create",
                    "workflow_id": "unused-draft",
                    "description": "A draft that has never been published.",
                },
            )
            removed_draft = await client.delete("/api/workflows/unused-draft")
            missing_draft = await client.get("/api/workflows/unused-draft")
            reused_draft_id = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "create",
                    "workflow_id": "unused-draft",
                    "description": "The unused ID can be reclaimed.",
                },
            )

            opened = await client.post(
                "/api/workflow-drafts",
                json={"kind": "open", "workflow_id": published_id},
            )
            removed_published = await client.delete(f"/api/workflows/{published_id}")
            missing_published = await client.get(f"/api/workflows/{published_id}")
            missing_open_draft = await client.get(
                f"/api/workflow-drafts/{opened.json()['draft']['draft_id']}"
            )
            search = await client.get("/api/workflows", params={"q": published_id})

        async with session_factory() as session:
            historical = await read_published_workflow_revision(
                session,
                workflow_id=published_id,
                revision_no=1,
            )
            with pytest.raises(WorkflowNotFoundError):
                await read_current_published_workflow(session, workflow_id=published_id)
            await seed_starter_workflows(session)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(WorkflowNotFoundError):
                await read_current_published_workflow(session, workflow_id=published_id)

        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            after_reseed = await client.get("/api/workflows", params={"q": published_id})
            reused_published_id = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "create",
                    "workflow_id": published_id,
                    "description": "A deliberate reactivation with preserved history.",
                },
            )
            assert reused_published_id.status_code == 201, reused_published_id.text
            reused_draft = reused_published_id.json()["draft"]
            republished = await client.post(
                f"/api/workflow-drafts/{reused_draft['draft_id']}/publish",
                headers={"If-Match": reused_published_id.headers["etag"]},
            )

        async with session_factory() as session:
            current = await read_current_published_workflow(
                session,
                workflow_id=published_id,
            )
            preserved = await read_published_workflow_revision(
                session,
                workflow_id=published_id,
                revision_no=1,
            )
            await seed_starter_workflows(session)
            await session.commit()

        async with session_factory() as session:
            current_after_reseed = await read_current_published_workflow(
                session,
                workflow_id=published_id,
            )

    assert created.status_code == 201, created.text
    assert removed_draft.status_code == 200, removed_draft.text
    assert removed_draft.json() == {
        "is_removed": True,
        "workflow_id": "unused-draft",
    }
    assert missing_draft.status_code == 404
    assert reused_draft_id.status_code == 201, reused_draft_id.text
    assert opened.status_code == 201, opened.text
    assert removed_published.status_code == 200, removed_published.text
    assert removed_published.json() == {
        "is_removed": True,
        "workflow_id": published_id,
    }
    assert missing_published.status_code == 404
    assert missing_open_draft.status_code == 404
    assert search.json()["items"] == []
    assert historical.workflow_id == published_id
    assert historical.revision_no == 1
    assert after_reseed.json()["items"] == []
    assert reused_draft["base_revision_no"] is None
    assert republished.status_code == 200, republished.text
    assert republished.json()["revision_no"] == 2
    assert current.revision_no == 2
    assert current.workflow.description == "A deliberate reactivation with preserved history."
    assert preserved == historical
    assert current_after_reseed == current


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_library_states_current_description_pagination_and_discard(
    tmp_path: Path,
    database_backend: DatabaseBackend,
) -> None:
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            created = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "create",
                    "workflow_id": "only-draft",
                    "description": "Draft-only searchable description.",
                },
            )
            opened = await client.post(
                "/api/workflow-drafts",
                json={"kind": "open", "workflow_id": "production-feature-delivery"},
            )
            edited = await client.patch(
                f"/api/workflow-drafts/{opened.json()['draft']['draft_id']}",
                headers={"If-Match": opened.json()["draft"]["etag"]},
                json={
                    "kind": "update_workflow",
                    "patch": {"description": "Current editable description."},
                },
            )
            current_search = await client.get(
                "/api/workflows",
                params={"q": "Current editable description"},
            )
            stale_search = await client.get(
                "/api/workflows",
                params={"q": "Review and refine a bounded delivery"},
            )
            all_items = await _all_library_items(client, limit=2)
            draft_detail = await client.get("/api/workflows/only-draft")
            published_detail = await client.get("/api/workflows/deep-research-and-decision-brief")
            combined_detail = await client.get("/api/workflows/production-feature-delivery")
            draft_revision = await client.get(
                "/api/workflows/only-draft",
                params={"revision_no": 1},
            )
            discarded = await client.delete(
                f"/api/workflow-drafts/{created.json()['draft']['draft_id']}",
                headers={"If-Match": created.json()["draft"]["etag"]},
            )
            after_discard = await client.get(
                "/api/workflows",
                params={"q": "only-draft"},
            )

    assert edited.status_code == 200, edited.text
    assert current_search.json()["items"][0]["workflow_id"] == "production-feature-delivery"
    assert stale_search.json()["items"] == []
    ids = [str(item["workflow_id"]) for item in all_items]
    assert ids == sorted(ids)
    by_id = {item["workflow_id"]: item for item in all_items}
    assert by_id["only-draft"]["state"] == "draft"
    assert by_id["only-draft"]["available_actions"] == ["edit", "remove"]
    assert by_id["only-draft"]["published_revision_no"] is None
    assert by_id["deep-research-and-decision-brief"]["state"] == "published"
    assert by_id["deep-research-and-decision-brief"]["available_actions"] == [
        "edit",
        "start_run",
        "remove",
    ]
    assert by_id["production-feature-delivery"]["state"] == "published_with_draft"
    assert by_id["production-feature-delivery"]["description"] == "Current editable description."
    assert (
        by_id["production-feature-delivery"]["updated_at"] == combined_detail.json()["updated_at"]
    )
    assert by_id["production-feature-delivery"]["provenance"] == "starter_seed"
    assert draft_detail.json()["state"] == "draft"
    assert draft_detail.json()["provenance"] == "user"
    assert draft_detail.json()["published"] is None
    assert draft_detail.json()["revisions"] == []
    assert published_detail.json()["state"] == "published"
    assert published_detail.json()["active_draft"] is None
    assert combined_detail.json()["state"] == "published_with_draft"
    assert combined_detail.json()["active_draft"]["etag"] == edited.json()["draft"]["etag"]
    assert draft_revision.status_code == 404, draft_revision.text
    assert discarded.status_code == 200, discarded.text
    assert after_discard.json()["items"] == []


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_search_treats_wildcards_as_literals_and_preserves_unicode_text(
    tmp_path: Path,
    database_backend: DatabaseBackend,
) -> None:
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            for workflow_id, description in (
                ("literal-percent", "A literal 100% marker."),
                ("literal-underscore", "A literal under_score marker."),
                ("literal-control", "No wildcard marker."),
                ("unicode-search", "Research Straße patterns."),
            ):
                created = await client.post(
                    "/api/workflow-drafts",
                    json={
                        "kind": "create",
                        "workflow_id": workflow_id,
                        "description": description,
                    },
                )
                assert created.status_code == 201, created.text
            percent = await client.get("/api/workflows", params={"q": "%"})
            underscore = await client.get("/api/workflows", params={"q": "_"})
            unicode_exact = await client.get("/api/workflows", params={"q": "Straße"})
            ascii_mixed_case = await client.get(
                "/api/workflows",
                params={"q": "LITERAL-CONTROL"},
            )

    assert tuple(item["workflow_id"] for item in percent.json()["items"]) == ("literal-percent",)
    assert tuple(item["workflow_id"] for item in underscore.json()["items"]) == (
        "literal-underscore",
    )
    assert tuple(item["workflow_id"] for item in unicode_exact.json()["items"]) == (
        "unicode-search",
    )
    assert tuple(item["workflow_id"] for item in ascii_mixed_case.json()["items"]) == (
        "literal-control",
    )


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_updated_at_prefers_a_later_current_publication_over_an_older_draft(
    tmp_path: Path,
    database_backend: DatabaseBackend,
) -> None:
    old_time = datetime(2020, 1, 1, tzinfo=UTC)
    workflow_id = "production-feature-delivery"
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with session_factory() as session:
            current = await read_workflow_catalog_entry(
                session,
                workflow_id=workflow_id,
                should_include_revisions=False,
            )
            assert current.published is not None
            opened = await open_workflow_draft(
                session,
                request=OpenWorkflowDraftRequest(kind="open", workflow_id=workflow_id),
            )
            await session.execute(
                update(WorkflowDraftModel)
                .where(WorkflowDraftModel.draft_id == opened.draft.draft_id)
                .values(updated_at=old_time)
            )
            refreshed_workflow = current.published.workflow.model_copy(
                update={"description": "Refreshed package-owned publication."}
            )
            refreshed = await publish_workflow_revision(
                session,
                workflow=refreshed_workflow,
                provenance=WorkflowProvenance.STARTER_SEED,
                should_update_current=True,
                current_provenance_guard=WorkflowProvenance.STARTER_SEED,
            )
            await session.commit()

        async with session_factory() as session:
            definition_time = await session.scalar(
                select(WorkflowDefinitionModel.updated_at).where(
                    WorkflowDefinitionModel.workflow_key == workflow_id
                )
            )
            detail = await read_workflow_catalog_entry(
                session,
                workflow_id=workflow_id,
                should_include_revisions=False,
            )

    assert definition_time is not None
    assert refreshed.revision_no == 2
    assert detail.state == "published_with_draft"
    assert detail.updated_at == definition_time
    assert detail.updated_at > old_time


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_updated_at_marks_published_draft_discard(
    tmp_path: Path,
    database_backend: DatabaseBackend,
) -> None:
    old_time = datetime(2020, 1, 1, tzinfo=UTC)
    workflow_id = "production-feature-delivery"
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with session_factory() as session:
            opened = await open_workflow_draft(
                session,
                request=OpenWorkflowDraftRequest(kind="open", workflow_id=workflow_id),
            )
            await session.execute(
                update(WorkflowDefinitionModel)
                .where(WorkflowDefinitionModel.workflow_key == workflow_id)
                .values(updated_at=old_time)
            )
            await discard_workflow_draft(
                session,
                draft_id=opened.draft.draft_id,
                expected_etag=opened.draft.etag,
            )
            await session.commit()

        async with session_factory() as session:
            definition_time = await session.scalar(
                select(WorkflowDefinitionModel.updated_at).where(
                    WorkflowDefinitionModel.workflow_key == workflow_id
                )
            )
            detail = await read_workflow_catalog_entry(
                session,
                workflow_id=workflow_id,
                should_include_revisions=False,
            )

    assert definition_time is not None
    assert detail.state == "published"
    assert detail.active_draft is None
    assert detail.updated_at == definition_time
    assert detail.updated_at > old_time


@pytest.mark.parametrize("database_backend", ("sqlite", "postgresql"))
async def test_updated_at_marks_reselection_of_an_older_immutable_revision(
    tmp_path: Path,
    database_backend: DatabaseBackend,
) -> None:
    old_time = datetime(2020, 1, 1, tzinfo=UTC)
    workflow_id = "production-feature-delivery"
    async with workflow_database(tmp_path, backend=database_backend) as session_factory:
        async with session_factory() as session:
            initial = await read_workflow_catalog_entry(
                session,
                workflow_id=workflow_id,
                should_include_revisions=False,
            )
            assert initial.published is not None
            await publish_workflow_revision(
                session,
                workflow=initial.published.workflow.model_copy(
                    update={"description": "Temporary newer publication."}
                ),
                provenance=WorkflowProvenance.STARTER_SEED,
                should_update_current=True,
            )
            await session.execute(
                update(WorkflowRevisionModel)
                .where(
                    WorkflowRevisionModel.workflow_key == workflow_id,
                    WorkflowRevisionModel.revision_no == 1,
                )
                .values(created_at=old_time)
            )
            reselected = await publish_workflow_revision(
                session,
                workflow=initial.published.workflow,
                provenance=WorkflowProvenance.STARTER_SEED,
                should_update_current=True,
            )
            await session.commit()

        async with session_factory() as session:
            definition_time = await session.scalar(
                select(WorkflowDefinitionModel.updated_at).where(
                    WorkflowDefinitionModel.workflow_key == workflow_id
                )
            )
            detail = await read_workflow_catalog_entry(
                session,
                workflow_id=workflow_id,
                should_include_revisions=False,
            )

    assert definition_time is not None
    assert reselected.revision_no == 1
    assert detail.published_revision_no == 1
    assert detail.updated_at == definition_time
    assert detail.updated_at > old_time


async def _all_library_items(
    client: httpx.AsyncClient,
    *,
    limit: int,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        params = {"limit": str(limit)}
        if cursor is not None:
            params["cursor"] = cursor
        response = await client.get("/api/workflows", params=params)
        assert response.status_code == 200, response.text
        items.extend(response.json()["items"])
        cursor = response.json()["next_cursor"]
        if cursor is None:
            return items
