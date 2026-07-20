from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

from autoclaw.interfaces.mcp.node import NODE_TOOL_NAMES
from autoclaw.runtime.node_operations import (
    NODE_OPERATION_CATALOG,
    ListFilesResponse,
    NodeOperationName,
)
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
    NodeOperationName.LIST_FILES,
    NodeOperationName.READ_FILE,
    NodeOperationName.SET_WORK_PLAN,
    NodeOperationName.RECORD_CHECKPOINT,
    NodeOperationName.RETURN_BOUNDARY,
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

    assert set(tool_names(tools_result)) == {str(name) for name in _WORKER_CEILING}
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


async def test_compatibility_projection_lists_static_strict_explicit_id_catalog() -> None:
    applications, _registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())

    async with node_mcp_client_session(applications.compatibility) as session:
        tools_result = await session.list_tools()

    assert set(tool_names(tools_result)) == set(NODE_TOOL_NAMES)
    assert len(NODE_TOOL_NAMES) == len(NODE_OPERATION_CATALOG) == 16
    assert set(tool_names(tools_result)).isdisjoint(_OPERATOR_ONLY_NAMES)
    for tool_name in NODE_TOOL_NAMES:
        schema = tool_input_schema(tools_result, tool_name)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert {"task_id", "dispatch_id"} <= set(schema["required"])
        assert {"task_id", "dispatch_id"} <= set(schema["properties"])
        assert "session_key" not in schema["properties"]


async def test_managed_and_compatibility_schemas_preserve_semantic_and_result_parity() -> None:
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
    async with node_mcp_client_session(applications.compatibility) as compatibility_session:
        compatibility_tools = await compatibility_session.list_tools()

    descriptors_by_name = {
        str(descriptor.name): descriptor for descriptor in NODE_OPERATION_CATALOG
    }
    for tool_name in NODE_TOOL_NAMES:
        managed_schema = tool_input_schema(managed_tools, tool_name)
        compatibility_schema = tool_input_schema(compatibility_tools, tool_name)
        compatibility_properties = dict(compatibility_schema["properties"])
        compatibility_properties.pop("task_id")
        compatibility_properties.pop("dispatch_id")
        compatibility_required = set(compatibility_schema.get("required", ())) - {
            "task_id",
            "dispatch_id",
        }

        assert compatibility_properties == managed_schema["properties"]
        assert compatibility_required == set(managed_schema.get("required", ()))
        assert tool_output_schema(compatibility_tools, tool_name) == tool_output_schema(
            managed_tools,
            tool_name,
        )
        assert (
            tool_description(managed_tools, tool_name) == descriptors_by_name[tool_name].description
        )
        assert (
            tool_description(compatibility_tools, tool_name)
            == descriptors_by_name[tool_name].description
        )

    boundary_description = tool_description(managed_tools, "return_boundary")
    assert "stop the current outer response immediately" in boundary_description
    assert "no further tool calls or prose" in boundary_description


async def test_both_projections_call_one_executor_with_the_same_semantic_arguments() -> None:
    response = ListFilesResponse(directory="workspace", entries=())
    executor = RecordingNodeOperationExecutor(
        results_by_name={NodeOperationName.LIST_FILES: response}
    )
    applications, registry = create_test_node_mcp_apps(executor)
    issued = issue_test_binding(
        registry,
        task_id="task.call-parity",
        dispatch_id="dispatch.call-parity",
        exposure_ceiling=(NodeOperationName.LIST_FILES,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as managed_session:
        managed_result = await call_tool_structured(
            managed_session,
            "list_files",
            {"directory": "workspace"},
        )
    async with node_mcp_client_session(applications.compatibility) as compatibility_session:
        compatibility_result = await call_tool_structured(
            compatibility_session,
            "list_files",
            {
                "task_id": "task.call-parity",
                "dispatch_id": "dispatch.call-parity",
                "directory": "workspace",
            },
        )

    assert managed_result == compatibility_result == response.model_dump(mode="json")
    assert [call.scope.model_dump(mode="json") for call in executor.calls] == [
        {
            "task_id": "task.call-parity",
            "dispatch_id": "dispatch.call-parity",
        },
        {
            "task_id": "task.call-parity",
            "dispatch_id": "dispatch.call-parity",
        },
    ]
    assert [call.arguments for call in executor.calls] == [
        {"directory": "workspace"},
        {"directory": "workspace"},
    ]


async def test_concurrent_managed_clients_keep_scope_and_tool_ceiling_isolated() -> None:
    executor = RecordingNodeOperationExecutor(
        listed_names_by_dispatch={
            "dispatch.concurrent-a": (
                NodeOperationName.GET_CURRENT_CONTEXT,
                NodeOperationName.LIST_FILES,
            ),
            "dispatch.concurrent-b": (
                NodeOperationName.GET_CURRENT_CONTEXT,
                NodeOperationName.SEARCH_DEFINITIONS,
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
            NodeOperationName.LIST_FILES,
        ),
    )
    issued_b = issue_test_binding(
        registry,
        task_id="task.concurrent-b",
        dispatch_id="dispatch.concurrent-b",
        exposure_ceiling=(
            NodeOperationName.GET_CURRENT_CONTEXT,
            NodeOperationName.SEARCH_DEFINITIONS,
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

    assert set(tool_names(tools_a)) == {"get_current_context", "list_files"}
    assert set(tool_names(tools_b)) == {"get_current_context", "search_definitions"}
    assert {scope.dispatch_id for scope in executor.listed_scopes} == {
        "dispatch.concurrent-a",
        "dispatch.concurrent-b",
    }
