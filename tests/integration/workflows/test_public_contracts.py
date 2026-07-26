from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.main import create_app
from banksia.persistence.session import get_db_session
from banksia.providers import ProviderKind
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.workflows.cursors import (
    encode_workflow_revision_cursor,
    encode_workflow_search_cursor,
)
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_http_workflow_catalog_and_history_are_bounded_and_share_cursors(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with _http_client(session_factory) as client:
            current = await client.get(f"/api/workflows/{GENERIC_WORKFLOW_ID}")
            active_draft = await _publish_history_and_create_active_draft(client)
            hidden_search = await client.get(
                "/api/workflows",
                params={"q": "Hidden active draft mutation"},
            )
            http_search_first = await client.get("/api/workflows", params={"limit": 1})
            http_search_second = await client.get(
                "/api/workflows",
                params={
                    "limit": 1,
                    "cursor": http_search_first.json()["next_cursor"],
                },
            )
            http_history_first = await client.get(
                f"/api/workflows/{GENERIC_WORKFLOW_ID}",
                params={"revision_limit": 1},
            )
            http_history_second = await client.get(
                f"/api/workflows/{GENERIC_WORKFLOW_ID}",
                params={
                    "revision_limit": 1,
                    "revision_cursor": http_history_first.json()["revisions_next_cursor"],
                },
            )
    assert current.status_code == 200, current.text
    assert active_draft.status_code == 200, active_draft.text
    assert hidden_search.status_code == 200, hidden_search.text
    assert tuple(item["workflow_id"] for item in hidden_search.json()["items"]) == (
        GENERIC_WORKFLOW_ID,
    )
    assert current.json()["provenance"] == "user"
    assert http_search_first.status_code == 200, http_search_first.text
    assert http_search_first.json()["next_cursor"] is not None
    assert http_search_second.status_code == 200, http_search_second.text
    assert http_history_first.status_code == 200, http_history_first.text
    assert len(http_history_first.json()["revisions"]) == 1
    assert http_history_first.json()["revisions_next_cursor"] is not None
    assert http_history_second.status_code == 200, http_history_second.text


async def test_http_workflow_cursor_failures_use_product_error_contract(
    tmp_path: Path,
) -> None:
    query_mismatched_cursor = encode_workflow_search_cursor(
        GENERIC_WORKFLOW_ID,
        normalized_query="first query",
    )
    cross_workflow_cursor = encode_workflow_revision_cursor(
        2,
        workflow_id="cursor-source-workflow",
    )
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with _http_client(session_factory) as client:
            http_results = (
                await client.get("/api/workflows", params={"cursor": "malformed"}),
                await client.get(
                    "/api/workflows",
                    params={"q": "second query", "cursor": query_mismatched_cursor},
                ),
                await client.get(
                    f"/api/workflows/{GENERIC_WORKFLOW_ID}",
                    params={"revision_cursor": cross_workflow_cursor},
                ),
            )
    for http_result in http_results:
        assert http_result.status_code == 400, http_result.text
        assert http_result.json()["code"] == "invalid_request"


async def _publish_history_and_create_active_draft(
    client: httpx.AsyncClient,
) -> httpx.Response:
    for description in ("Published revision two.", "Published revision three."):
        opened = await client.post(
            "/api/workflow-drafts",
            json={"kind": "open", "workflow_id": GENERIC_WORKFLOW_ID},
        )
        assert opened.status_code == 201, opened.text
        draft = opened.json()["draft"]
        edited = await client.patch(
            f"/api/workflow-drafts/{draft['draft_id']}",
            headers={"If-Match": draft["etag"]},
            json={
                "kind": "update_workflow",
                "patch": {"description": description},
            },
        )
        assert edited.status_code == 200, edited.text
        published = await client.post(
            f"/api/workflow-drafts/{draft['draft_id']}/publish",
            headers={"If-Match": edited.json()["draft"]["etag"]},
        )
        assert published.status_code == 200, published.text
    opened = await client.post(
        "/api/workflow-drafts",
        json={"kind": "open", "workflow_id": GENERIC_WORKFLOW_ID},
    )
    assert opened.status_code == 201, opened.text
    draft = opened.json()["draft"]
    return await client.patch(
        f"/api/workflow-drafts/{draft['draft_id']}",
        headers={"If-Match": draft["etag"]},
        json={
            "kind": "update_workflow",
            "patch": {"description": "Hidden active draft mutation."},
        },
    )


async def test_http_workflow_readbacks_never_expose_integrity_hashes(tmp_path: Path) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with _http_client(session_factory) as client:
            detail = await client.get(f"/api/workflows/{GENERIC_WORKFLOW_ID}")

    assert detail.status_code == 200, detail.text
    assert "content_hash" not in detail.text


async def test_http_task_start_commits_current_workflow_and_maps_unknown_to_404(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        async with _http_client(session_factory) as client:
            started = await client.post(
                "/api/tasks",
                json=_task_start_payload(tmp_path),
            )
            missing = await client.post(
                "/api/tasks",
                json=_task_start_payload(
                    tmp_path,
                    workflow_id="missing-workflow",
                ),
            )

    assert started.status_code == 202, started.text
    assert started.json()["task_id"].startswith("t_")
    assert started.json()["status"] == "accepted"
    assert started.json()["manifest"].endswith("/manifest.md")
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "not_found"


async def test_http_workflow_schemas_hide_private_guardrails_and_hashes() -> None:
    app = create_app(should_enable_mcp_mounts=False)
    openapi = app.openapi()
    workflow_paths = {path: value for path, value in openapi["paths"].items() if "workflow" in path}
    public_http_contract = _referenced_openapi_contract(
        workflow_paths,
        cast(Mapping[str, object], openapi["components"]["schemas"]),
    )
    _assert_no_private_workflow_fields_or_guardrails(public_http_contract)


def _referenced_openapi_contract(
    roots: Mapping[str, object],
    components: Mapping[str, object],
) -> dict[str, object]:
    selected: dict[str, object] = {}
    pending = list(_schema_refs(roots))
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        schema = components[name]
        selected[name] = schema
        pending.extend(_schema_refs(schema))
    return {"paths": dict(roots), "schemas": selected}


def _schema_refs(value: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str):
                prefix = "#/components/schemas/"
                if child.startswith(prefix):
                    refs.add(child.removeprefix(prefix))
            else:
                refs.update(_schema_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_schema_refs(child))
    return refs


def _assert_no_private_workflow_fields_or_guardrails(value: object) -> None:
    serialized = json.dumps(value, sort_keys=True)
    assert "content_hash" not in serialized
    assert not _contains_schema_keyword(value, keyword="maxItems", expected=32)
    assert not _contains_schema_keyword(value, keyword="maxLength", expected=255)


def _contains_schema_keyword(
    value: object,
    *,
    keyword: str,
    expected: int,
) -> bool:
    if isinstance(value, Mapping):
        if value.get(keyword) == expected:
            return True
        return any(
            _contains_schema_keyword(child, keyword=keyword, expected=expected)
            for child in value.values()
        )
    if isinstance(value, list):
        return any(
            _contains_schema_keyword(child, keyword=keyword, expected=expected) for child in value
        )
    return False


def _task_start_payload(
    workspace: Path,
    *,
    workflow_id: str = GENERIC_WORKFLOW_ID,
) -> dict[str, object]:
    return {
        "workflow": workflow_id,
        "prompt": "Exercise the exact Task start contract.",
        "workspace": str(workspace),
    }


@asynccontextmanager
async def _http_client(session_factory: Any) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(should_enable_mcp_mounts=False)
    app.state.dispatch_opening_dependencies = _opening_dependencies(Path("/"))

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = session_dependency
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:8123",
    ) as client:
        yield client


def _opening_dependencies(workspace: Path) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            controller_workspace=workspace,
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
