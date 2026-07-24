from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from mcp.types import CallToolResult
from sqlalchemy.ext.asyncio import AsyncSession

import banksia.persistence.session_operations as session_operations
import banksia.runtime.task_start as task_start_module
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.interfaces.mcp.operator.server import (
    OperatorEffectPublishers,
    create_operator_mcp_server,
)
from banksia.main import create_app
from banksia.persistence.session import get_db_session
from banksia.providers import ProviderKind
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.workflows.cursors import (
    encode_workflow_revision_cursor,
    encode_workflow_search_cursor,
)
from tests.helpers.product_surface import operator_payload
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_http_catalog_hides_draft_only_workflows(tmp_path: Path) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with _http_client(session_factory) as client:
            created = await client.post(
                "/workflow-drafts",
                json={
                    "kind": "workflow",
                    "id": "http-draft-rediscovery",
                    "description": "Draft rediscovery proof.",
                    "lead": {"id": "lead"},
                },
            )
            catalog = await client.get("/workflows")
            detail = await client.get("/workflows/http-draft-rediscovery")
            draft_detail = await client.get(f"/workflow-drafts/{created.json()['draft_id']}")

    assert created.status_code == 201, created.text
    assert catalog.status_code == 200, catalog.text
    assert "http-draft-rediscovery" not in {item["workflow_id"] for item in catalog.json()["items"]}
    assert detail.status_code == 404, detail.text
    assert detail.json()["code"] == "not_found"
    assert draft_detail.status_code == 200, draft_detail.text
    assert draft_detail.headers["etag"] == created.json()["etag"]


async def test_workflow_catalog_and_history_are_bounded_and_share_cursors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with _http_client(session_factory) as client:
            current = await client.get("/workflows/reviewed-delivery")
            active_draft = await _publish_history_and_create_active_draft(client)
            hidden_search = await client.get(
                "/workflows",
                params={"q": "Hidden active draft mutation"},
            )
            http_search_first = await client.get("/workflows", params={"limit": 1})
            http_search_second = await client.get(
                "/workflows",
                params={
                    "limit": 1,
                    "cursor": http_search_first.json()["next_cursor"],
                },
            )
            http_history_first = await client.get(
                "/workflows/reviewed-delivery",
                params={"revision_limit": 1},
            )
            http_history_second = await client.get(
                "/workflows/reviewed-delivery",
                params={
                    "revision_limit": 1,
                    "revision_cursor": http_history_first.json()["revisions_next_cursor"],
                },
            )

        monkeypatch.setattr(session_operations, "get_session_factory", lambda: session_factory)
        server = create_operator_mcp_server()
        operator_search_first = await server.call_tool("workflow_search", {"limit": 1})
        operator_search_second = await server.call_tool(
            "workflow_search",
            {
                "limit": 1,
                "cursor": http_search_first.json()["next_cursor"],
            },
        )
        operator_history_first = await server.call_tool(
            "workflow_get",
            {"workflow_id": "reviewed-delivery", "revision_limit": 1},
        )
        operator_history_second = await server.call_tool(
            "workflow_get",
            {
                "workflow_id": "reviewed-delivery",
                "revision_limit": 1,
                "revision_cursor": http_history_first.json()["revisions_next_cursor"],
            },
        )

    assert current.status_code == 200, current.text
    assert active_draft.status_code == 201, active_draft.text
    assert hidden_search.status_code == 200, hidden_search.text
    assert hidden_search.json()["items"] == []
    assert http_search_first.status_code == 200, http_search_first.text
    assert http_search_first.json()["next_cursor"] is not None
    assert http_search_second.status_code == 200, http_search_second.text
    assert operator_payload(operator_search_first) == http_search_first.json()
    assert operator_payload(operator_search_second) == http_search_second.json()
    assert http_history_first.status_code == 200, http_history_first.text
    assert len(http_history_first.json()["revisions"]) == 1
    assert http_history_first.json()["revisions_next_cursor"] is not None
    assert http_history_second.status_code == 200, http_history_second.text
    assert operator_payload(operator_history_first) == http_history_first.json()
    assert operator_payload(operator_history_second) == http_history_second.json()


async def test_workflow_cursor_failures_preserve_http_operator_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_mismatched_cursor = encode_workflow_search_cursor(
        "reviewed-delivery",
        normalized_query="first query",
    )
    cross_workflow_cursor = encode_workflow_revision_cursor(
        2,
        workflow_id="reviewed-delivery",
    )
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with _http_client(session_factory) as client:
            http_results = (
                await client.get("/workflows", params={"cursor": "malformed"}),
                await client.get(
                    "/workflows",
                    params={"q": "second query", "cursor": query_mismatched_cursor},
                ),
                await client.get(
                    "/workflows/evidence-research",
                    params={"revision_cursor": cross_workflow_cursor},
                ),
            )

        monkeypatch.setattr(session_operations, "get_session_factory", lambda: session_factory)
        server = create_operator_mcp_server()
        operator_results = (
            await server.call_tool("workflow_search", {"cursor": "malformed"}),
            await server.call_tool(
                "workflow_search",
                {"query": "second query", "cursor": query_mismatched_cursor},
            ),
            await server.call_tool(
                "workflow_get",
                {
                    "workflow_id": "evidence-research",
                    "revision_cursor": cross_workflow_cursor,
                },
            ),
        )

    for http_result, operator_result in zip(http_results, operator_results, strict=True):
        assert http_result.status_code == 400, http_result.text
        assert isinstance(operator_result, CallToolResult)
        assert operator_result.isError is True
        assert operator_result.structuredContent == http_result.json()
        assert http_result.json()["code"] == "invalid_request"


async def _publish_history_and_create_active_draft(
    client: httpx.AsyncClient,
) -> httpx.Response:
    workflow = {
        "kind": "workflow",
        "id": "reviewed-delivery",
        "description": "",
        "lead": {"id": "lead"},
    }
    for description in ("Published revision two.", "Published revision three."):
        workflow["description"] = description
        draft = await client.post("/workflow-drafts", json=workflow)
        assert draft.status_code == 201, draft.text
        published = await client.post(
            f"/workflow-drafts/{draft.json()['draft_id']}/publish",
            headers={"If-Match": draft.json()["etag"]},
        )
        assert published.status_code == 200, published.text
    workflow["description"] = "Hidden active draft mutation."
    return await client.post("/workflow-drafts", json=workflow)


async def test_http_workflow_readbacks_never_expose_integrity_hashes(tmp_path: Path) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with _http_client(session_factory) as client:
            detail = await client.get("/workflows/reviewed-delivery")

    assert detail.status_code == 200, detail.text
    assert "content_hash" not in detail.text


async def test_operator_workflow_get_never_exposes_integrity_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        monkeypatch.setattr(session_operations, "get_session_factory", lambda: session_factory)
        server = create_operator_mcp_server()
        result = await server.call_tool(
            "workflow_get",
            {"workflow_id": "reviewed-delivery"},
        )

    assert isinstance(result, tuple) and len(result) == 2
    assert "content_hash" not in json.dumps(result[1], sort_keys=True)


async def test_http_task_start_commits_current_workflow_and_maps_unknown_to_404(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with _http_client(session_factory) as client:
            started = await client.post(
                "/tasks",
                json=_task_start_payload(tmp_path),
            )
            missing = await client.post(
                "/tasks",
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


async def test_operator_task_start_uses_the_same_committing_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        monkeypatch.setattr(task_start_module, "get_session_factory", lambda: session_factory)
        result = await create_operator_mcp_server(
            effect_publishers=OperatorEffectPublishers(
                dispatch_opening_dependencies=_opening_dependencies(tmp_path),
            )
        ).call_tool(
            "task_start",
            {
                "workflow": "reviewed-delivery",
                "prompt": "Complete the requested work.",
                "workspace": str(tmp_path),
            },
        )

    assert isinstance(result, tuple) and len(result) == 2
    payload = cast(dict[str, object], result[1])
    assert str(payload["task_id"]).startswith("t_")
    assert payload["status"] == "accepted"


async def test_http_and_operator_workflow_schemas_hide_private_guardrails_and_hashes() -> None:
    app = create_app(should_enable_mcp_mounts=False)
    openapi = app.openapi()
    workflow_paths = {path: value for path, value in openapi["paths"].items() if "workflow" in path}
    public_http_contract = _referenced_openapi_contract(
        workflow_paths,
        cast(Mapping[str, object], openapi["components"]["schemas"]),
    )
    _assert_no_private_workflow_fields_or_guardrails(public_http_contract)

    tools = await create_operator_mcp_server().list_tools()
    for tool in tools:
        if not tool.name.startswith("workflow_"):
            continue
        _assert_no_private_workflow_fields_or_guardrails(
            {"input": tool.inputSchema, "output": tool.outputSchema}
        )


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
    workflow_id: str = "reviewed-delivery",
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
