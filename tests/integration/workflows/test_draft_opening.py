from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

import oh_my_subagents.interfaces.cli as cli
from oh_my_subagents.config import get_settings
from oh_my_subagents.interfaces.http.openapi import build_product_openapi_document
from oh_my_subagents.main import create_app
from oh_my_subagents.persistence.session import dispose_test_db_engine
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
from tests.helpers.product_surface import product_http_client
from tests.helpers.workflow_runtime import initialized_workflow_database


def test_product_openapi_exposes_the_strict_draft_opening_union() -> None:
    document = build_product_openapi_document()
    request_schema = document["paths"]["/api/workflow-drafts"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]

    assert request_schema["discriminator"] == {
        "propertyName": "kind",
        "mapping": {
            "create": "#/components/schemas/CreateWorkflowDraftRequest",
            "open": "#/components/schemas/OpenWorkflowDraftRequest",
        },
    }
    assert request_schema["oneOf"] == [
        {"$ref": "#/components/schemas/CreateWorkflowDraftRequest"},
        {"$ref": "#/components/schemas/OpenWorkflowDraftRequest"},
    ]
    new_member = document["components"]["schemas"]["NewMember"]
    assert "id" not in new_member["properties"]
    responses = document["paths"]["/api/workflow-drafts"]["post"]["responses"]
    for status_code in ("200", "201"):
        response_schema = responses[status_code]["content"]["application/json"]["schema"]
        assert response_schema == {"$ref": "#/components/schemas/WorkflowDraftOpenResult"}
        assert "ETag" in responses[status_code]["headers"]
    assert "Location" not in responses["200"]["headers"]
    assert "Location" in responses["201"]["headers"]


async def test_create_allocates_nested_member_ids_and_never_reuses_them(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            created = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "create",
                    "workflow_id": "allocated-tree",
                    "description": "Controller allocation proof.",
                    "lead": {
                        "title": "Lead",
                        "children": [
                            {
                                "title": "Child",
                                "children": [{"title": "Grandchild"}],
                            }
                        ],
                    },
                },
            )
            duplicate = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "create",
                    "workflow_id": "allocated-tree",
                    "description": "Replacement must reject.",
                },
            )
            published_conflict = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "create",
                    "workflow_id": GENERIC_WORKFLOW_ID,
                    "description": "Published replacement must reject.",
                },
            )
            legacy_full_definition = await client.post(
                "/api/workflow-drafts",
                json={
                    "kind": "workflow",
                    "id": "legacy-browser-shape",
                    "description": "Legacy browser request.",
                    "lead": {"id": "browser-id"},
                },
            )
            draft = created.json()["draft"]
            removed = await client.patch(
                f"/api/workflow-drafts/{draft['draft_id']}",
                headers={"If-Match": draft["etag"]},
                json={"kind": "remove_member", "member_id": "member-2"},
            )
            added = await client.patch(
                f"/api/workflow-drafts/{draft['draft_id']}",
                headers={"If-Match": removed.json()["draft"]["etag"]},
                json={
                    "kind": "add_member",
                    "parent_member_id": "member-1",
                    "member": {"title": "Later child"},
                },
            )

    assert created.status_code == 201, created.text
    assert created.headers["etag"] == draft["etag"]
    assert created.headers["location"] == f"/api/workflow-drafts/{draft['draft_id']}"
    lead = draft["workflow"]["lead"]
    assert lead["id"] == "member-1"
    assert lead["children"][0]["id"] == "member-2"
    assert lead["children"][0]["children"][0]["id"] == "member-3"
    assert duplicate.status_code == 409, duplicate.text
    assert published_conflict.status_code == 409, published_conflict.text
    assert legacy_full_definition.status_code == 400, legacy_full_definition.text
    assert removed.status_code == 200, removed.text
    assert added.status_code == 200, added.text
    assert added.json()["draft"]["workflow"]["lead"]["children"][0]["id"] == "member-4"


async def test_open_is_idempotent_and_clones_the_exact_current_publication(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            published = await client.get(f"/api/workflows/{GENERIC_WORKFLOW_ID}")
            opened = await client.post(
                "/api/workflow-drafts",
                json={"kind": "open", "workflow_id": GENERIC_WORKFLOW_ID},
            )
            reopened = await client.post(
                "/api/workflow-drafts",
                json={"kind": "open", "workflow_id": GENERIC_WORKFLOW_ID},
            )
            unknown = await client.post(
                "/api/workflow-drafts",
                json={"kind": "open", "workflow_id": "unknown-workflow"},
            )
            unknown_search = await client.get(
                "/api/workflows",
                params={"q": "unknown-workflow"},
            )

    assert published.status_code == 200, published.text
    assert opened.status_code == 201, opened.text
    assert opened.headers["location"] == (
        f"/api/workflow-drafts/{opened.json()['draft']['draft_id']}"
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.headers["etag"] == reopened.json()["draft"]["etag"]
    assert "location" not in reopened.headers
    assert opened.json()["is_created"] is True
    assert reopened.json()["is_created"] is False
    assert reopened.json()["draft"] == opened.json()["draft"]
    assert opened.json()["draft"]["base_revision_no"] == published.json()["published_revision_no"]
    assert opened.json()["draft"]["workflow"] == published.json()["published"]["workflow"]
    assert unknown.status_code == 404, unknown.text
    assert unknown_search.status_code == 200, unknown_search.text
    assert unknown_search.json()["items"] == []


async def test_file_backed_application_restart_preserves_library_detail_and_open_result(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "oms-config.toml"
    data_dir = tmp_path / "oms-data"
    request_body = {
        "kind": "create",
        "workflow_id": "restart-durable",
        "description": "Durable across a fresh application and session stack.",
    }

    try:
        await cli.cmd_init(
            argparse.Namespace(
                config=str(config_path),
                data_dir=str(data_dir),
                database_url=None,
                host="127.0.0.1",
                port=8123,
                log_level="INFO",
                force=True,
                skip_db_upgrade=False,
                json=False,
            )
        )
        with cli.command_env(config_path=config_path, env="test"):
            get_settings.cache_clear()
            first_app = create_app(should_enable_mcp_mounts=False)
            async with first_app.router.lifespan_context(first_app):
                async with _application_client(first_app) as client:
                    created = await client.post("/api/workflow-drafts", json=request_body)
            get_settings.cache_clear()

            restarted_app = create_app(should_enable_mcp_mounts=False)
            async with restarted_app.router.lifespan_context(restarted_app):
                async with _application_client(restarted_app) as client:
                    search = await client.get(
                        "/api/workflows",
                        params={"q": "restart-durable"},
                    )
                    detail = await client.get("/api/workflows/restart-durable")
                    reopened = await client.post(
                        "/api/workflow-drafts",
                        json={"kind": "open", "workflow_id": "restart-durable"},
                    )
    finally:
        await dispose_test_db_engine()

    assert created.status_code == 201, created.text
    assert search.status_code == 200, search.text
    assert tuple(item["workflow_id"] for item in search.json()["items"]) == ("restart-durable",)
    assert detail.status_code == 200, detail.text
    assert detail.json()["active_draft"] == created.json()["draft"]
    assert reopened.status_code == 200, reopened.text
    assert reopened.json() == {
        "draft": created.json()["draft"],
        "is_created": False,
    }


@asynccontextmanager
async def _application_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:8123",
    ) as client:
        yield client
