from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event

from banksia.operator.tools import OperatorTool, OperatorToolName, build_operator_tools
from banksia.operator.tools.workflow_projection import OperatorWorkflowDraftStaleError
from banksia.runtime.errors import RuntimeOperationError
from banksia.workflows.service_errors import WorkflowNotFoundError
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import AsyncSessionFactory, initialized_workflow_database


def _tool(tools: tuple[OperatorTool, ...], name: OperatorToolName) -> OperatorTool:
    return next(tool for tool in tools if tool.name is name)


def _workflow_payload(
    workflow_id: str = "operator-authored",
    *,
    description: str = "Coordinate a reviewable delivery.",
) -> dict[str, object]:
    return {
        "kind": "workflow",
        "id": workflow_id,
        "description": description,
        "note": "Keep review independent from implementation.",
        "lead": {
            "id": "lead",
            "title": "",
            "children": [
                {
                    "id": "reviewer",
                    "instruction": "Review the proposed delivery independently.",
                    "children": [],
                    "provider": {
                        "kind": "codex",
                        "effort": "medium",
                        "sandbox": {
                            "mode": "workspace_write",
                            "network": "deny",
                        },
                    },
                    "capabilities": {
                        "human_request": ["direction"],
                        "command_run": "allow",
                    },
                },
                {
                    "id": "observer",
                    "instruction": "Observe the delivery boundary.",
                },
            ],
        },
    }


def _assert_no_embedded_workflow(value: object) -> None:
    if isinstance(value, dict):
        assert "workflow" not in value
        assert "content_json" not in value
        for child in value.values():
            _assert_no_embedded_workflow(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_embedded_workflow(child)


def _assert_compact_stale_draft(
    error: OperatorWorkflowDraftStaleError,
    *,
    current_draft: dict[str, Any],
) -> None:
    current_reference = error.draft.model_dump(mode="json")
    assert current_reference == current_draft
    _assert_no_embedded_workflow(current_reference)
    assert error.__cause__ is None
    assert error.__context__ is None


def _assert_member_projection_shape(projection: dict[str, Any]) -> None:
    assert set(projection) == {"kind", "source", "workflow", "member"}
    assert set(projection["workflow"]) == {
        "kind",
        "id",
        "description",
        "note",
        "lead_member_id",
    }
    assert "children" not in projection["member"]


def _build_tools(
    tmp_path: Path,
    session_factory: AsyncSessionFactory,
) -> tuple[OperatorTool, ...]:
    dependencies = product_dispatch_dependencies(tmp_path)
    return build_operator_tools(
        settings=dependencies.settings,
        session_factory=session_factory,
        dispatch_dependencies=dependencies,
    )


async def _create_draft(
    tools: tuple[OperatorTool, ...],
    workflow: dict[str, object],
    *,
    etag: str | None = None,
) -> dict[str, Any]:
    request: dict[str, object] = {"workflow": workflow}
    if etag is not None:
        request["etag"] = etag
    return await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_CREATE).call(request)


async def _publish_complete_workflow(
    tools: tuple[OperatorTool, ...],
    *,
    workflow_id: str,
    description: str,
) -> dict[str, Any]:
    created = await _create_draft(
        tools,
        _workflow_payload(workflow_id, description=description),
    )
    return await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_PUBLISH).call(
        {
            "draft_id": created["draft"]["draft_id"],
            "etag": created["draft"]["etag"],
        }
    )


async def _capture_catalog_selects(
    tools: tuple[OperatorTool, ...],
    session_factory: AsyncSessionFactory,
    *,
    workflow_id: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    selected_sql: list[str] = []

    def capture_select(
        _connection: object,
        _cursor: object,
        statement: str,
        *_args: object,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selected_sql.append(" ".join(statement.casefold().split()))

    async with session_factory() as session:
        bind = session.get_bind()
        event.listen(bind, "before_cursor_execute", capture_select)
        try:
            result = await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
                {
                    "workflow_id": workflow_id,
                    "selection": {
                        "kind": "catalog",
                        "revision_limit": 1,
                    },
                }
            )
        finally:
            event.remove(bind, "before_cursor_execute", capture_select)
    return result, tuple(selected_sql)


async def test_workflow_catalog_reads_metadata_only_and_keeps_cursor_source_coherent(
    tmp_path: Path,
) -> None:
    workflow_id = "operator-history"
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        tools = _build_tools(tmp_path, session_factory)
        for revision_no in range(1, 4):
            published = await _publish_complete_workflow(
                tools,
                workflow_id=workflow_id,
                description=f"History revision {revision_no}.",
            )
            assert published == {
                "workflow_id": workflow_id,
                "revision_no": revision_no,
            }
        active_draft = await _create_draft(
            tools,
            _workflow_payload(workflow_id, description="Current draft description."),
        )

        first_page, selected_sql = await _capture_catalog_selects(
            tools,
            session_factory,
            workflow_id=workflow_id,
        )
        second_page = await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
            {
                "workflow_id": workflow_id,
                "selection": {
                    "kind": "catalog",
                    "revision_cursor": first_page["revisions_next_cursor"],
                    "revision_limit": 1,
                },
            }
        )
        search = await _tool(tools, OperatorToolName.WORKFLOW_SEARCH).call({"query": workflow_id})
        options = await _tool(tools, OperatorToolName.WORKFLOW_AUTHORING_OPTIONS).call({})
        with pytest.raises(RuntimeOperationError):
            await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
                {
                    "workflow_id": GENERIC_WORKFLOW_ID,
                    "selection": {
                        "kind": "catalog",
                        "revision_cursor": first_page["revisions_next_cursor"],
                    },
                }
            )

    assert len(selected_sql) == 2
    catalog_sql = next(sql for sql in selected_sql if "maximum_revision_no" in sql)
    history_sql = next(sql for sql in selected_sql if "workflow_revisions.content_hash" in sql)
    assert "json_extract(workflow_drafts.content_json" in catalog_sql
    assert "draft_content_json" not in catalog_sql
    assert "selected_content_json" not in catalog_sql
    assert "workflow_drafts.content_json as" not in catalog_sql
    assert "workflow_revisions.content_json as" not in catalog_sql
    assert "json_extract(workflow_revisions.content_json" in history_sql
    assert "workflow_revisions.content_json as" not in history_sql

    assert first_page["published"] == {
        "kind": "published",
        "workflow_id": workflow_id,
        "revision_no": 3,
    }
    assert first_page["active_draft"] == active_draft["draft"]
    assert [item["source"]["revision_no"] for item in first_page["revisions"]] == [3]
    assert [item["source"]["revision_no"] for item in second_page["revisions"]] == [2]
    for page in (first_page, second_page):
        sources = (
            page["published"],
            page["active_draft"],
            *(item["source"] for item in page["revisions"]),
        )
        assert all(source["workflow_id"] == workflow_id for source in sources)
        _assert_no_embedded_workflow(page)
    assert search["items"][0]["workflow_id"] == workflow_id
    assert options["default_provider"]["kind"] == "codex"


async def test_stale_undo_discard_and_publish_return_only_current_draft_reference(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        tools = _build_tools(tmp_path, session_factory)
        created = await _create_draft(tools, _workflow_payload("stale-mutations"))
        original = created["draft"]
        edited = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_EDIT).call(
            {
                "draft_id": original["draft_id"],
                "etag": original["etag"],
                "operation": {
                    "kind": "update_workflow",
                    "patch": {"description": "Current accepted description."},
                },
            }
        )
        stale_requests = (
            (
                OperatorToolName.WORKFLOW_DRAFT_UNDO,
                {
                    "draft_id": original["draft_id"],
                    "etag": original["etag"],
                    "receipt_id": edited["undo_receipt"],
                },
            ),
            (
                OperatorToolName.WORKFLOW_DRAFT_DISCARD,
                {
                    "draft_id": original["draft_id"],
                    "etag": original["etag"],
                },
            ),
            (
                OperatorToolName.WORKFLOW_DRAFT_PUBLISH,
                {
                    "draft_id": original["draft_id"],
                    "etag": original["etag"],
                },
            ),
        )
        for tool_name, request in stale_requests:
            with pytest.raises(OperatorWorkflowDraftStaleError) as caught:
                await _tool(tools, tool_name).call(request)
            _assert_compact_stale_draft(
                caught.value,
                current_draft=edited["draft"],
            )
        current = await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
            {
                "workflow_id": "stale-mutations",
                "selection": {
                    "kind": "draft",
                    "draft_id": original["draft_id"],
                    "etag": edited["draft"]["etag"],
                },
            }
        )

    assert current["workflow"]["description"] == "Current accepted description."
    _assert_member_projection_shape(current)


async def test_workflow_reads_fail_closed_for_missing_and_cross_source_identity(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        tools = _build_tools(tmp_path, session_factory)
        created = await _create_draft(tools, _workflow_payload("identity-owner"))
        failures = (
            {
                "workflow_id": GENERIC_WORKFLOW_ID,
                "selection": {
                    "kind": "published",
                    "revision_no": 999,
                },
            },
            {
                "workflow_id": GENERIC_WORKFLOW_ID,
                "selection": {
                    "kind": "draft",
                    "draft_id": "workflow-draft.missing",
                    "etag": '"wd-missing"',
                },
            },
            {
                "workflow_id": GENERIC_WORKFLOW_ID,
                "selection": {
                    "kind": "published",
                    "revision_no": 1,
                    "member_id": "missing-member",
                },
            },
            {
                "workflow_id": GENERIC_WORKFLOW_ID,
                "selection": {
                    "kind": "draft",
                    "draft_id": created["draft"]["draft_id"],
                    "etag": created["draft"]["etag"],
                },
            },
        )
        errors: list[WorkflowNotFoundError] = []
        for request in failures:
            with pytest.raises(WorkflowNotFoundError) as caught:
                await _tool(tools, OperatorToolName.WORKFLOW_GET).call(request)
            errors.append(caught.value)

    assert len(errors) == 4
    for error in errors:
        assert not hasattr(error, "draft")
        assert "content_json" not in str(error)
