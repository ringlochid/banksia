from __future__ import annotations

from autoclaw.runtime.node_operations import NodeOperationName
from tests.integration.mcp.node_server.transport_support import (
    RecordingNodeOperationExecutor,
    create_test_node_mcp_apps,
    issue_test_binding,
    managed_headers,
    node_mcp_client_session,
    tool_input_schema,
)


async def test_command_run_schema_differs_only_by_compatibility_scope_selectors() -> None:
    applications, registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())
    issued = issue_test_binding(
        registry,
        task_id="task.command-run-schema",
        dispatch_id="dispatch.command-run-schema",
        exposure_ceiling=(NodeOperationName.START_COMMAND_RUN,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as managed_session:
        managed_schema = tool_input_schema(
            await managed_session.list_tools(),
            "start_command_run",
        )
    async with node_mcp_client_session(applications.compatibility) as compatibility_session:
        compatibility_schema = tool_input_schema(
            await compatibility_session.list_tools(),
            "start_command_run",
        )

    assert set(managed_schema["properties"]) == {"request"}
    assert set(managed_schema["required"]) == {"request"}
    assert set(compatibility_schema["properties"]) == {
        "task_id",
        "dispatch_id",
        "request",
    }
    assert set(compatibility_schema["required"]) == {
        "task_id",
        "dispatch_id",
        "request",
    }
    assert compatibility_schema["properties"]["request"] == managed_schema["properties"]["request"]
