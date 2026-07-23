from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import banksia.persistence.session_operations as session_operations
import banksia.runtime.task_start as task_start_module
import httpx
import pytest
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
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_http_catalog_rediscovery_returns_active_draft_and_etag(tmp_path: Path) -> None:
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

    assert created.status_code == 201, created.text
    draft = created.json()
    item = next(item for item in catalog.json() if item["workflow_id"] == "http-draft-rediscovery")
    assert item == {
        "workflow_id": "http-draft-rediscovery",
        "description": "Draft rediscovery proof.",
        "published_revision_no": None,
        "provenance": None,
        "draft_id": draft["draft_id"],
        "draft_etag": draft["etag"],
    }
    assert detail.status_code == 200, detail.text
    assert detail.headers["etag"] == draft["etag"]
    assert detail.json() == {
        "workflow_id": "http-draft-rediscovery",
        "published": None,
        "revisions": [],
        "active_draft": draft,
    }


async def test_http_workflow_readbacks_never_expose_integrity_hashes(tmp_path: Path) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with _http_client(session_factory) as client:
            detail = await client.get("/workflows/reviewed-delivery")
            history = await client.get("/workflows/reviewed-delivery/revisions")
            exact = await client.get("/workflows/reviewed-delivery/revisions/1")

    assert detail.status_code == 200, detail.text
    assert history.status_code == 200, history.text
    assert exact.status_code == 200, exact.text
    for response in (detail, history, exact):
        assert "content_hash" not in response.text


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
                "/tasks/start",
                json=_task_start_payload(tmp_path),
            )
            missing = await client.post(
                "/tasks/start",
                json=_task_start_payload(
                    tmp_path,
                    workflow_id="missing-workflow",
                ),
            )

    assert started.status_code == 200, started.text
    assert started.json()["task_id"].startswith("t_")
    assert started.json()["status"] == "accepted"
    assert started.json()["manifest"].endswith("/manifest.md")
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "missing_resource"


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
