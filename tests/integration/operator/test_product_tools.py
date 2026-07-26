from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from banksia.operator.tools import OperatorTool, OperatorToolName, build_operator_tools
from banksia.operator.tools.contracts import MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS
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
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    seeded_async_executor,
    seeded_task_workspace,
)
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
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


def _large_team_workflow_payload(workflow_id: str) -> dict[str, object]:
    maximum_prose = "x" * 16_384
    return {
        "kind": "workflow",
        "id": workflow_id,
        "description": "Keep a legal large team readable.",
        "lead": {
            "id": "lead",
            "children": [
                {
                    "id": f"member-{index}",
                    "title": maximum_prose,
                    "description": maximum_prose,
                }
                for index in range(10)
            ],
        },
    }


async def test_task_tools_use_current_actions_and_operator_event_provenance(
    tmp_path: Path,
) -> None:
    dependencies = product_dispatch_dependencies(tmp_path)
    publisher = _captured_publisher(dependencies)
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        tools = build_operator_tools(
            settings=dependencies.settings,
            session_factory=session_factory,
            dispatch_dependencies=dependencies,
        )
        started = await _tool(tools, OperatorToolName.TASK_START).call(
            {
                "workflow": GENERIC_WORKFLOW_ID,
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
    assert current["kind"] == "overview"
    assert paused["task"]["status"] == "paused"
    assert event is not None
    assert event.event_source == "operator"
    assert event.actor_ref == "operator"
    assert sum(isinstance(signal, DispatchCleanupRequested) for signal in publisher.signals) == 1


async def _open_direction_request(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
) -> str:
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
    return str(opened.model_dump()["request_id"])


async def _read_direction_request(
    tools: tuple[OperatorTool, ...],
    *,
    task_id: str,
    request_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    current = await _tool(tools, OperatorToolName.TASK_GET).call({"task_id": task_id})
    request_summary = next(item for item in current["human_requests"] if item["id"] == request_id)
    request_result = await _tool(tools, OperatorToolName.TASK_GET).call(
        {
            "task_id": task_id,
            "selection": {
                "kind": "human_request",
                "request_id": request_id,
            },
        }
    )
    request_files = await _tool(tools, OperatorToolName.TASK_GET).call(
        {
            "task_id": task_id,
            "selection": {
                "kind": "human_request_files",
                "request_id": request_id,
            },
        }
    )
    return request_summary, request_result, request_files


async def test_human_request_tool_uses_current_action_and_operator_provenance(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(
        tmp_path,
        suffix="operator-human-tool",
    ) as (executor, session_factory, ids, _signals):
        request_id = await _open_direction_request(executor, ids)
        dependencies = product_dispatch_dependencies(tmp_path)
        publisher = _captured_publisher(dependencies)
        tools = build_operator_tools(
            settings=dependencies.settings,
            session_factory=session_factory,
            dispatch_dependencies=dependencies,
        )
        request_summary, request_result, request_files = await _read_direction_request(
            tools,
            task_id=ids.task_id,
            request_id=request_id,
        )
        request = request_result["request"]
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

    assert request_summary["item_count"] == 1
    assert request_summary["file_count"] == 0
    assert request_files["files"] == []
    assert receipt["request"]["status"] == "answered"
    assert set(receipt["request"]) == {"id", "status", "resolution"}
    assert receipt["continuation_pending"] is True
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


async def test_large_legal_team_has_bounded_overview_and_control_receipt(
    tmp_path: Path,
) -> None:
    workflow_id = "large-team-overview"
    dependencies = product_dispatch_dependencies(tmp_path)
    async with initialized_workflow_database(tmp_path) as session_factory:
        tools = build_operator_tools(
            settings=dependencies.settings,
            session_factory=session_factory,
            dispatch_dependencies=dependencies,
        )
        created = await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_CREATE).call(
            {"workflow": _large_team_workflow_payload(workflow_id)}
        )
        await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_PUBLISH).call(
            {
                "draft_id": created["draft"]["draft_id"],
                "etag": created["draft"]["etag"],
            }
        )
        started = await _tool(tools, OperatorToolName.TASK_START).call(
            {
                "workflow": workflow_id,
                "prompt": "Coordinate the large team.",
            }
        )
        task_id = str(started["task_id"])
        overview = await _tool(tools, OperatorToolName.TASK_GET).call({"task_id": task_id})
        member = await _tool(tools, OperatorToolName.TASK_GET).call(
            {
                "task_id": task_id,
                "selection": {
                    "kind": "member",
                    "member_id": "member-0",
                },
            }
        )
        pause_action = next(action for action in overview["actions"] if action["kind"] == "pause")
        paused = await _tool(tools, OperatorToolName.TASK_CONTROL).call(
            {
                "task_id": task_id,
                "action_id": pause_action["id"],
            }
        )

    assert overview["kind"] == "overview"
    assert len(overview["team"]) == 11
    assert all(len(team_member["name"]) <= 240 for team_member in overview["team"])
    assert len(member["member"]["name"]) == 16_384
    assert set(paused["task"]) == {
        "id",
        "status",
        "status_message",
        "updated_at",
        "actions",
    }
    serialized_units = (
        len(json.dumps(paused, ensure_ascii=False, separators=(",", ":")).encode("utf-16-le")) // 2
    )
    assert serialized_units < MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS
