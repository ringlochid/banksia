from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from oh_my_subagents.operator.tools import OperatorTool, OperatorToolName, build_operator_tools
from oh_my_subagents.operator.tools.workflow_projection import OperatorWorkflowDraftStaleError
from oh_my_subagents.workflows.service_errors import WorkflowUndoReceiptError
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import AsyncSessionFactory, initialized_workflow_database


@dataclass(frozen=True)
class _MutationStage:
    created: dict[str, Any]
    original: dict[str, Any]
    replacement: dict[str, Any]
    updated: dict[str, Any]
    removed: dict[str, Any]
    added: dict[str, Any]
    allocated_root_id: str


@dataclass(frozen=True)
class _ReleaseStage:
    selected_lead: dict[str, Any]
    selected_root: dict[str, Any]
    validation: dict[str, Any]
    restored: dict[str, Any]
    published: dict[str, Any]
    selected_published: dict[str, Any]
    discard_candidate: dict[str, Any]
    discarded: dict[str, Any]


def _tool(tools: tuple[OperatorTool, ...], name: OperatorToolName) -> OperatorTool:
    return next(tool for tool in tools if tool.name is name)


def _workflow_payload(
    *,
    description: str = "Coordinate a reviewable delivery.",
) -> dict[str, object]:
    return {
        "kind": "workflow",
        "id": "operator-authored",
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
                },
                {
                    "id": "observer",
                    "instruction": "Observe the delivery boundary.",
                },
            ],
        },
    }


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


async def _edit_draft(
    tools: tuple[OperatorTool, ...],
    *,
    draft_id: str,
    etag: str,
    operation: dict[str, object],
) -> dict[str, Any]:
    return await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_EDIT).call(
        {
            "draft_id": draft_id,
            "etag": etag,
            "operation": operation,
        }
    )


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


async def _exercise_mutation_stage(
    tools: tuple[OperatorTool, ...],
) -> _MutationStage:
    created = await _create_draft(tools, _workflow_payload())
    original = created["draft"]
    replacement = await _create_draft(
        tools,
        _workflow_payload(description="Coordinate, review, and verify a replacement delivery."),
        etag=original["etag"],
    )
    with pytest.raises(OperatorWorkflowDraftStaleError) as caught:
        await _create_draft(
            tools,
            _workflow_payload(description="A stale replacement."),
            etag=original["etag"],
        )
    _assert_compact_stale_draft(caught.value, current_draft=replacement["draft"])

    updated = await _edit_draft(
        tools,
        draft_id=original["draft_id"],
        etag=replacement["draft"]["etag"],
        operation={
            "kind": "update_member",
            "member_id": "reviewer",
            "patch": {"title": "Independent reviewer"},
        },
    )
    removed = await _edit_draft(
        tools,
        draft_id=original["draft_id"],
        etag=updated["draft"]["etag"],
        operation={"kind": "remove_member", "member_id": "observer"},
    )
    added = await _edit_draft(
        tools,
        draft_id=original["draft_id"],
        etag=removed["draft"]["etag"],
        operation={
            "kind": "add_member",
            "parent_member_id": "lead",
            "member": {
                "title": "Allocated subtree root",
                "children": [
                    {
                        "title": "Allocated nested reviewer",
                        "children": [{"title": "Allocated evidence reader"}],
                    }
                ],
            },
        },
    )
    return _MutationStage(
        created=created,
        original=original,
        replacement=replacement,
        updated=updated,
        removed=removed,
        added=added,
        allocated_root_id=added["accepted_change"]["member_id"],
    )


async def _read_draft_member(
    tools: tuple[OperatorTool, ...],
    stage: _MutationStage,
    *,
    member_id: str | None = None,
) -> dict[str, Any]:
    selection: dict[str, object] = {
        "kind": "draft",
        "draft_id": stage.original["draft_id"],
        "etag": stage.added["draft"]["etag"],
    }
    if member_id is not None:
        selection["member_id"] = member_id
    return await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
        {
            "workflow_id": "operator-authored",
            "selection": selection,
        }
    )


async def _exercise_release_stage(
    tools: tuple[OperatorTool, ...],
    stage: _MutationStage,
) -> _ReleaseStage:
    selected_lead = await _read_draft_member(tools, stage)
    selected_root = await _read_draft_member(
        tools,
        stage,
        member_id=stage.allocated_root_id,
    )
    validation = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_VALIDATE).call(
        {"draft_id": stage.original["draft_id"]}
    )
    restored = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_UNDO).call(
        {
            "draft_id": stage.original["draft_id"],
            "etag": stage.added["draft"]["etag"],
            "receipt_id": stage.added["undo_receipt"],
        }
    )
    with pytest.raises(WorkflowUndoReceiptError):
        await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_UNDO).call(
            {
                "draft_id": stage.original["draft_id"],
                "etag": restored["draft"]["etag"],
                "receipt_id": stage.added["undo_receipt"],
            }
        )
    published = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_PUBLISH).call(
        {
            "draft_id": stage.original["draft_id"],
            "etag": restored["draft"]["etag"],
        }
    )
    selected_published = await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
        {
            "workflow_id": "operator-authored",
            "selection": {
                "kind": "published",
                "revision_no": published["revision_no"],
                "member_id": "reviewer",
            },
        }
    )
    discard_candidate = await _create_draft(
        tools,
        {
            "kind": "workflow",
            "id": "operator-discard",
            "description": "Discard this draft.",
            "lead": {"id": "lead"},
        },
    )
    discarded = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_DISCARD).call(
        {
            "draft_id": discard_candidate["draft"]["draft_id"],
            "etag": discard_candidate["draft"]["etag"],
        }
    )
    return _ReleaseStage(
        selected_lead=selected_lead,
        selected_root=selected_root,
        validation=validation,
        restored=restored,
        published=published,
        selected_published=selected_published,
        discard_candidate=discard_candidate,
        discarded=discarded,
    )


def _assert_member_projection_shape(projection: dict[str, Any]) -> None:
    assert set(projection) == {"kind", "source", "workflow", "member"}
    assert "children" not in projection["member"]


def _assert_mutation_stage(stage: _MutationStage, release: _ReleaseStage) -> None:
    assert stage.created["is_created"] is True
    assert stage.replacement["is_created"] is False
    assert stage.replacement["draft"]["draft_id"] == stage.original["draft_id"]
    assert stage.replacement["draft"]["etag"] != stage.original["etag"]
    assert stage.replacement["undo_receipt"]
    assert stage.updated["accepted_change"] == {
        "kind": "member_updated",
        "member_id": "reviewer",
    }
    assert stage.removed["accepted_change"] == {
        "kind": "member_removed",
        "member_id": "observer",
    }
    assert stage.added["accepted_change"] == {
        "kind": "member_added",
        "parent_member_id": "lead",
        "member_id": stage.allocated_root_id,
    }
    etags = {
        stage.original["etag"],
        stage.replacement["draft"]["etag"],
        stage.updated["draft"]["etag"],
        stage.removed["draft"]["etag"],
        stage.added["draft"]["etag"],
        release.restored["draft"]["etag"],
    }
    assert len(etags) == 6
    undo_receipts = {
        stage.replacement["undo_receipt"],
        stage.updated["undo_receipt"],
        stage.removed["undo_receipt"],
        stage.added["undo_receipt"],
    }
    assert None not in undo_receipts
    assert len(undo_receipts) == 4


def _assert_release_stage(stage: _MutationStage, release: _ReleaseStage) -> None:
    assert release.selected_lead["member"]["child_ids"] == [
        "reviewer",
        stage.allocated_root_id,
    ]
    nested_ids = release.selected_root["member"]["child_ids"]
    assert nested_ids is not None and len(nested_ids) == 1
    assert stage.allocated_root_id not in nested_ids
    assert release.validation == {
        "draft": stage.added["draft"],
        "is_valid": True,
        "issues": [],
    }
    assert release.restored["consumed_receipt_id"] == stage.added["undo_receipt"]
    assert release.published == {
        "workflow_id": "operator-authored",
        "revision_no": 1,
    }
    assert release.selected_published["member"]["title"] == "Independent reviewer"
    assert release.discarded == {
        "is_discarded": True,
        "draft_id": release.discard_candidate["draft"]["draft_id"],
    }
    for projection in (
        release.selected_lead,
        release.selected_root,
        release.selected_published,
    ):
        _assert_member_projection_shape(projection)


async def test_workflow_mutation_lifecycle_returns_compact_exact_receipts(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        tools = _build_tools(tmp_path, session_factory)
        stage = await _exercise_mutation_stage(tools)
        release = await _exercise_release_stage(tools, stage)

    _assert_mutation_stage(stage, release)
    _assert_release_stage(stage, release)
    for compact_result in (
        stage.created,
        stage.replacement,
        stage.updated,
        stage.removed,
        stage.added,
        release.validation,
        release.restored,
        release.published,
        release.discarded,
    ):
        _assert_no_embedded_workflow(compact_result)
