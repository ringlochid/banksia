from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import AsyncExitStack

from oh_my_subagents.interfaces.mcp.node import NODE_TOOL_NAMES
from oh_my_subagents.runtime.node_operations import (
    NODE_OPERATION_CATALOG,
    NodeOperationName,
)
from oh_my_subagents.runtime.work_plan import SetWorkPlanResponse
from tests.integration.mcp.node_server.transport_support import (
    RecordingNodeOperationExecutor,
    call_tool_structured,
    create_test_node_mcp_apps,
    issue_test_binding,
    managed_headers,
    mcp_session_without_lifespan,
    node_mcp_client_session,
    tool_description,
    tool_input_schema,
    tool_names,
    tool_output_schema,
)

_WORKER_CEILING = (
    NodeOperationName.GET_CURRENT_CONTEXT,
    NodeOperationName.SET_WORK_PLAN,
    NodeOperationName.CHECKPOINT,
    NodeOperationName.ADD_CHILD,
    NodeOperationName.OPEN_HUMAN_REQUEST,
    NodeOperationName.START_COMMAND_RUN,
)
_OPERATOR_ONLY_NAMES = {
    "list_runtime_tasks",
    "get_runtime_task",
    "pause_task",
    "continue_task",
    "cancel_task",
}


async def test_managed_projection_lists_only_binding_scoped_semantic_tools() -> None:
    executor = RecordingNodeOperationExecutor()
    applications, registry = create_test_node_mcp_apps(executor)
    issued = issue_test_binding(
        registry,
        task_id="task.managed-worker",
        dispatch_id="dispatch.managed-worker",
        exposure_ceiling=_WORKER_CEILING,
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as session:
        tools_result = await session.list_tools()

    assert tool_names(tools_result) == tuple(str(name) for name in _WORKER_CEILING)
    assert set(tool_names(tools_result)).isdisjoint(_OPERATOR_ONLY_NAMES)
    assert [scope.model_dump(mode="json") for scope in executor.listed_scopes] == [
        {
            "task_id": "task.managed-worker",
            "dispatch_id": "dispatch.managed-worker",
        }
    ]
    for tool_name in tool_names(tools_result):
        schema = tool_input_schema(tools_result, tool_name)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert "task_id" not in schema["properties"]
        assert "dispatch_id" not in schema["properties"]
        assert "session_key" not in schema["properties"]


async def test_managed_schemas_preserve_catalog_semantics_and_results() -> None:
    executor = RecordingNodeOperationExecutor()
    applications, registry = create_test_node_mcp_apps(executor)
    issued = issue_test_binding(
        registry,
        task_id="task.schema-parity",
        dispatch_id="dispatch.schema-parity",
        exposure_ceiling=NODE_TOOL_NAMES,
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as managed_session:
        managed_tools = await managed_session.list_tools()
    assert tool_names(managed_tools) == NODE_TOOL_NAMES
    assert len(NODE_TOOL_NAMES) == len(NODE_OPERATION_CATALOG) == 9
    descriptors_by_name = {
        str(descriptor.name): descriptor for descriptor in NODE_OPERATION_CATALOG
    }
    for tool_name in NODE_TOOL_NAMES:
        managed_schema = tool_input_schema(managed_tools, tool_name)
        assert managed_schema["type"] == "object"
        assert managed_schema["additionalProperties"] is False
        assert "task_id" not in managed_schema["properties"]
        assert "dispatch_id" not in managed_schema["properties"]
        assert tool_output_schema(managed_tools, tool_name) is not None
        assert (
            tool_description(managed_tools, tool_name) == descriptors_by_name[tool_name].description
        )

    delegate_description = tool_description(managed_tools, "delegate")
    assert "stop immediately" in delegate_description
    assert "no further tool calls or prose" in delegate_description


async def test_replan_projections_hide_recursive_controller_guardrails() -> None:
    applications, registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())
    replan_operations = (
        NodeOperationName.ADD_CHILD,
        NodeOperationName.UPDATE_CHILD,
    )
    issued = issue_test_binding(
        registry,
        task_id="task.replan-schema",
        dispatch_id="dispatch.replan-schema",
        exposure_ceiling=replan_operations,
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as managed_session:
        managed_tools = await managed_session.list_tools()
    expected_children_fields = {"add_child": 1, "update_child": 3}
    for operation in replan_operations:
        schema = tool_input_schema(managed_tools, operation.value)
        _assert_no_hidden_replan_guardrails(schema)
        children_fields = _collect_property_schemas(schema, "children")
        assert len(children_fields) == expected_children_fields[operation.value]
        assert all("maxItems" not in field for field in children_fields)


async def test_work_message_file_limits_are_hidden_from_tool_schemas() -> None:
    applications, registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())
    operations = (
        NodeOperationName.CHECKPOINT,
        NodeOperationName.OPEN_HUMAN_REQUEST,
    )
    issued = issue_test_binding(
        registry,
        task_id="task.hidden-file-limit",
        dispatch_id="dispatch.hidden-file-limit",
        exposure_ceiling=operations,
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as managed_session:
        tools = await managed_session.list_tools()

    for operation in operations:
        schema = tool_input_schema(tools, operation.value)
        files_fields = _collect_property_schemas(schema, "files")
        assert files_fields
        assert all("maxItems" not in field for field in files_fields)


async def test_managed_human_request_schema_exposes_only_allowed_kinds() -> None:
    executor = RecordingNodeOperationExecutor(human_request_kinds=("input", "review"))
    applications, registry = create_test_node_mcp_apps(executor)
    issued = issue_test_binding(
        registry,
        task_id="task.human-kinds",
        dispatch_id="dispatch.human-kinds",
        exposure_ceiling=(NodeOperationName.OPEN_HUMAN_REQUEST,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as managed_session:
        tools = await managed_session.list_tools()

    schema = tool_input_schema(tools, NodeOperationName.OPEN_HUMAN_REQUEST)
    request_schema = schema["$defs"]["HumanRequestOpenRequest"]
    assert request_schema["properties"]["kind"] == {
        "enum": ["input", "review"],
        "type": "string",
    }


async def test_managed_projection_calls_the_executor_with_semantic_arguments() -> None:
    response = SetWorkPlanResponse(changed=False, plan=None)
    executor = RecordingNodeOperationExecutor(
        results_by_name={NodeOperationName.SET_WORK_PLAN: response}
    )
    applications, registry = create_test_node_mcp_apps(executor)
    issued = issue_test_binding(
        registry,
        task_id="task.call-parity",
        dispatch_id="dispatch.call-parity",
        exposure_ceiling=(NodeOperationName.SET_WORK_PLAN,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as managed_session:
        managed_result = await call_tool_structured(
            managed_session,
            "set_work_plan",
            {},
        )
    assert managed_result == response.model_dump(mode="json")
    assert [call.scope.model_dump(mode="json") for call in executor.calls] == [
        {
            "task_id": "task.call-parity",
            "dispatch_id": "dispatch.call-parity",
        },
    ]
    assert [call.arguments for call in executor.calls] == [{}]


async def test_concurrent_managed_clients_keep_scope_and_tool_ceiling_isolated() -> None:
    executor = RecordingNodeOperationExecutor(
        listed_names_by_dispatch={
            "dispatch.concurrent-a": (
                NodeOperationName.GET_CURRENT_CONTEXT,
                NodeOperationName.SET_WORK_PLAN,
            ),
            "dispatch.concurrent-b": (
                NodeOperationName.GET_CURRENT_CONTEXT,
                NodeOperationName.CHECKPOINT,
            ),
        }
    )
    applications, registry = create_test_node_mcp_apps(executor)
    issued_a = issue_test_binding(
        registry,
        task_id="task.concurrent-a",
        dispatch_id="dispatch.concurrent-a",
        exposure_ceiling=(
            NodeOperationName.GET_CURRENT_CONTEXT,
            NodeOperationName.SET_WORK_PLAN,
        ),
    )
    issued_b = issue_test_binding(
        registry,
        task_id="task.concurrent-b",
        dispatch_id="dispatch.concurrent-b",
        exposure_ceiling=(
            NodeOperationName.GET_CURRENT_CONTEXT,
            NodeOperationName.CHECKPOINT,
        ),
    )

    async with applications.managed.router.lifespan_context(applications.managed):
        async with AsyncExitStack() as stack:
            session_a = await stack.enter_async_context(
                mcp_session_without_lifespan(
                    applications.managed,
                    headers=managed_headers(issued_a),
                )
            )
            session_b = await stack.enter_async_context(
                mcp_session_without_lifespan(
                    applications.managed,
                    headers=managed_headers(issued_b),
                )
            )
            tools_a, tools_b = await asyncio.gather(
                session_a.list_tools(),
                session_b.list_tools(),
            )

    assert set(tool_names(tools_a)) == {"get_current_context", "set_work_plan"}
    assert set(tool_names(tools_b)) == {"checkpoint", "get_current_context"}
    assert {scope.dispatch_id for scope in executor.listed_scopes} == {
        "dispatch.concurrent-a",
        "dispatch.concurrent-b",
    }


def _assert_no_hidden_replan_guardrails(value: object) -> None:
    if isinstance(value, Mapping):
        assert value.get("maxItems") not in {32, 256}
        assert value.get("maxLength") != 255
        for child in value.values():
            _assert_no_hidden_replan_guardrails(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_hidden_replan_guardrails(child)


def _collect_property_schemas(
    value: object,
    property_name: str,
) -> tuple[Mapping[str, object], ...]:
    found: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            property_schema = properties.get(property_name)
            if isinstance(property_schema, Mapping):
                found.append(property_schema)
        for child in value.values():
            found.extend(_collect_property_schemas(child, property_name))
    elif isinstance(value, list):
        for child in value:
            found.extend(_collect_property_schemas(child, property_name))
    return tuple(found)
