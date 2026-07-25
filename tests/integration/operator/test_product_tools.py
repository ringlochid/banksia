from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from banksia.operator.tools import OperatorTool, OperatorToolName, build_operator_tools
from banksia.persistence.models import CommandRunModel, HumanRequestModel, TaskEventModel
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    CommandRunCancellationRequested,
    DispatchCleanupRequested,
    HumanRequestTerminal,
)
from banksia.workflows.service_errors import (
    WorkflowStaleDraftError,
    WorkflowUndoReceiptError,
)
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    seeded_async_executor,
    seeded_task_workspace,
)
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import initialized_workflow_database


def _tool(tools: tuple[OperatorTool, ...], name: OperatorToolName) -> OperatorTool:
    return next(tool for tool in tools if tool.name is name)


def _captured_publisher(
    dependencies: DispatchOpeningDependencies,
) -> CapturedRuntimeEffectPublisher:
    publisher = dependencies.post_commit_publisher
    assert isinstance(publisher, CapturedRuntimeEffectPublisher)
    return publisher


def _operator_workflow_payload() -> dict[str, object]:
    return {
        "kind": "workflow",
        "id": "operator-authored",
        "description": "Coordinate a reviewable delivery.",
        "note": "Keep review independent from implementation.",
        "lead": {
            "id": "lead",
            "title": "",
            "children": [
                {
                    "id": "reviewer",
                    "instruction": "Review the proposed delivery independently.",
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
                }
            ],
        },
    }


async def _create_and_edit_workflow(
    tools: tuple[OperatorTool, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    created = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_CREATE).call(
        {"workflow": _operator_workflow_payload()}
    )
    original = created["draft"]
    edited = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_EDIT).call(
        {
            "draft_id": original["draft_id"],
            "etag": original["etag"],
            "operation": {
                "kind": "update_workflow",
                "patch": {"description": "Coordinate, review, and verify a delivery."},
            },
        }
    )
    with pytest.raises(WorkflowStaleDraftError):
        await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_EDIT).call(
            {
                "draft_id": original["draft_id"],
                "etag": original["etag"],
                "operation": {
                    "kind": "update_workflow",
                    "patch": {"description": "A stale replacement."},
                },
            }
        )
    return created, edited


async def _validate_undo_and_publish_workflow(
    tools: tuple[OperatorTool, ...],
    *,
    original: dict[str, Any],
    edited: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validation = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_VALIDATE).call(
        {"draft_id": original["draft_id"]}
    )
    restored = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_UNDO).call(
        {
            "draft_id": original["draft_id"],
            "etag": edited["draft"]["etag"],
            "receipt_id": edited["undo_receipt"],
        }
    )
    with pytest.raises(WorkflowUndoReceiptError):
        await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_UNDO).call(
            {
                "draft_id": original["draft_id"],
                "etag": restored["etag"],
                "receipt_id": edited["undo_receipt"],
            }
        )
    published = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_PUBLISH).call(
        {
            "draft_id": original["draft_id"],
            "etag": restored["etag"],
        }
    )
    return validation, restored, published


async def _create_and_discard_workflow(
    tools: tuple[OperatorTool, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_CREATE).call(
        {
            "workflow": {
                "kind": "workflow",
                "id": "operator-discard",
                "description": "Discard this draft.",
                "lead": {"id": "lead"},
            }
        }
    )
    discarded = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_DISCARD).call(
        {
            "draft_id": candidate["draft"]["draft_id"],
            "etag": candidate["draft"]["etag"],
        }
    )
    return candidate, discarded


async def test_workflow_tools_use_one_authoritative_draft_lifecycle(tmp_path: Path) -> None:
    dependencies = product_dispatch_dependencies(tmp_path)
    async with initialized_workflow_database(tmp_path) as session_factory:
        tools = build_operator_tools(
            settings=dependencies.settings,
            session_factory=session_factory,
            dispatch_dependencies=dependencies,
        )

        options = await _tool(tools, OperatorToolName.WORKFLOW_AUTHORING_OPTIONS).call({})
        search = await _tool(tools, OperatorToolName.WORKFLOW_SEARCH).call(
            {"query": "reviewed-delivery"}
        )
        existing = await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
            {
                "workflow_id": "reviewed-delivery",
                "should_include_revisions": False,
            }
        )
        created, edited = await _create_and_edit_workflow(tools)
        validation, restored, published = await _validate_undo_and_publish_workflow(
            tools,
            original=created["draft"],
            edited=edited,
        )
        discard_candidate, discarded = await _create_and_discard_workflow(tools)

    assert options["default_provider"]["kind"] == "codex"
    assert search["items"][0]["workflow_id"] == "reviewed-delivery"
    assert existing["active_draft"] is None
    assert created["is_created"] is True
    assert validation["draft"]["etag"] == edited["draft"]["etag"]
    assert restored["workflow"]["description"] == "Coordinate a reviewable delivery."
    assert published["workflow_id"] == "operator-authored"
    assert published["revision_no"] == 1
    assert discarded == {
        "is_discarded": True,
        "draft_id": discard_candidate["draft"]["draft_id"],
    }


async def test_task_tools_use_current_actions_and_operator_event_provenance(
    tmp_path: Path,
) -> None:
    dependencies = product_dispatch_dependencies(tmp_path)
    publisher = _captured_publisher(dependencies)
    async with initialized_workflow_database(tmp_path) as session_factory:
        tools = build_operator_tools(
            settings=dependencies.settings,
            session_factory=session_factory,
            dispatch_dependencies=dependencies,
        )
        started = await _tool(tools, OperatorToolName.TASK_START).call(
            {
                "workflow": "reviewed-delivery",
                "prompt": "Prepare a bounded reviewable delivery.",
            }
        )
        task_id = str(started["task_id"])
        search = await _tool(tools, OperatorToolName.TASK_SEARCH).call(
            {"query": "bounded reviewable"}
        )
        current = await _tool(tools, OperatorToolName.TASK_GET).call({"task_id": task_id})
        pause_action = next(action for action in current["actions"] if action["kind"] == "pause")
        paused = await _tool(tools, OperatorToolName.TASK_CONTROL).call(
            {
                "task_id": task_id,
                "action_id": pause_action["id"],
            }
        )
        with pytest.raises(RuntimeOperationError):
            await _tool(tools, OperatorToolName.TASK_CONTROL).call(
                {
                    "task_id": task_id,
                    "action_id": pause_action["id"],
                }
            )
        async with session_factory() as session:
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.task_id == task_id,
                    TaskEventModel.event_type == "task_paused",
                )
            )

    assert started["workspace"] == str(tmp_path)
    assert search["items"][0]["id"] == task_id
    assert paused["task"]["status"] == "paused"
    assert event is not None
    assert event.event_source == "operator"
    assert event.actor_ref == "operator"
    assert sum(isinstance(signal, DispatchCleanupRequested) for signal in publisher.signals) == 1


async def test_human_request_tool_uses_current_action_and_operator_provenance(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(
        tmp_path,
        suffix="operator-human-tool",
    ) as (executor, session_factory, ids, _signals):
        opened = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="open_human_request",
            arguments={
                "request": {
                    "kind": "direction",
                    "summary": "Choose a delivery direction.",
                    "items": [
                        {
                            "id": "direction",
                            "prompt": "Which direction?",
                            "options": [
                                {"id": "a", "title": "Direction A"},
                                {"id": "b", "title": "Direction B"},
                            ],
                        }
                    ],
                }
            },
        )
        request_id = str(opened.model_dump()["request_id"])
        dependencies = product_dispatch_dependencies(tmp_path)
        publisher = _captured_publisher(dependencies)
        tools = build_operator_tools(
            settings=dependencies.settings,
            session_factory=session_factory,
            dispatch_dependencies=dependencies,
        )
        current = await _tool(tools, OperatorToolName.TASK_GET).call({"task_id": ids.task_id})
        request = next(item for item in current["human_requests"] if item["id"] == request_id)
        action_id = request["action"]["id"]
        receipt = await _tool(tools, OperatorToolName.HUMAN_REQUEST_RESPOND).call(
            {
                "task_id": ids.task_id,
                "request_id": request_id,
                "action_id": action_id,
                "input": {
                    "kind": "answer",
                    "item_responses": {"direction": {"kind": "option", "option_id": "a"}},
                },
            }
        )
        with pytest.raises(RuntimeOperationError):
            await _tool(tools, OperatorToolName.HUMAN_REQUEST_RESPOND).call(
                {
                    "task_id": ids.task_id,
                    "request_id": request_id,
                    "action_id": action_id,
                    "input": {"kind": "cancel"},
                }
            )
        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.task_id == ids.task_id,
                    TaskEventModel.event_type == "human_request_resolved",
                )
            )

    assert receipt["request"]["status"] == "answered"
    assert source is not None
    assert source.resolved_by_surface == "operator"
    assert source.resolved_by_actor_ref == "operator"
    assert event is not None and event.event_source == "operator"
    assert publisher.signals == (HumanRequestTerminal(request_id=request_id),)


async def _open_command_with_output(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    *,
    workspace: Path,
) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="start_command_run",
        arguments={
            "request": {
                "command": {"kind": "argv", "argv": ["python", "-V"]},
                "summary": "Read bounded output.",
            }
        },
    )
    command_id = str(opened.model_dump()["command_id"])
    async with session_factory() as session:
        source = await session.get(CommandRunModel, command_id)
        assert source is not None
        output_path = workspace / source.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x1b[31mred\x1b[0m output\n")
    return command_id


async def test_command_tools_read_bounded_output_and_cancel_as_operator(
    tmp_path: Path,
) -> None:
    suffix = "operator-command-tool"
    async with seeded_async_executor(
        tmp_path,
        suffix=suffix,
    ) as (executor, session_factory, ids, _signals):
        command_id = await _open_command_with_output(
            executor,
            session_factory,
            ids,
            workspace=seeded_task_workspace(tmp_path, suffix),
        )
        dependencies = product_dispatch_dependencies(tmp_path)
        publisher = _captured_publisher(dependencies)
        tools = build_operator_tools(
            settings=dependencies.settings,
            session_factory=session_factory,
            dispatch_dependencies=dependencies,
        )
        current = await _tool(tools, OperatorToolName.COMMAND_RUN_GET).call(
            {"task_id": ids.task_id, "command_id": command_id}
        )
        first_page = await _tool(tools, OperatorToolName.COMMAND_RUN_OUTPUT_READ).call(
            {
                "task_id": ids.task_id,
                "command_id": command_id,
                "limit": 10,
            }
        )
        second_page = await _tool(tools, OperatorToolName.COMMAND_RUN_OUTPUT_READ).call(
            {
                "task_id": ids.task_id,
                "command_id": command_id,
                "cursor": first_page["next_cursor"],
            }
        )
        action_id = current["cancel_action"]["id"]
        receipt = await _tool(tools, OperatorToolName.COMMAND_RUN_CANCEL).call(
            {
                "task_id": ids.task_id,
                "command_id": command_id,
                "action_id": action_id,
            }
        )
        with pytest.raises(RuntimeOperationError):
            await _tool(tools, OperatorToolName.COMMAND_RUN_CANCEL).call(
                {
                    "task_id": ids.task_id,
                    "command_id": command_id,
                    "action_id": action_id,
                }
            )
        async with session_factory() as session:
            source = await session.get(CommandRunModel, command_id)
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.task_id == ids.task_id,
                    TaskEventModel.event_type == "command_run_cancel_requested",
                )
            )

    assert first_page["content"] == "red"
    assert second_page["content"] == " output\n"
    assert receipt["command_run"]["state"] == "cancelling"
    assert source is not None
    assert source.cancellation_requested_by_actor_ref == "operator"
    assert event is not None
    assert event.event_source == "operator"
    assert event.actor_ref == "operator"
    assert publisher.signals == (
        CommandRunCancellationRequested(
            run_id=command_id,
            ownership_revision=source.ownership_revision,
        ),
    )
