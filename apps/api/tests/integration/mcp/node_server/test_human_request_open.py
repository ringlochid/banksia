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


async def test_human_request_schema_differs_only_by_compatibility_scope_selectors() -> None:
    applications, registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())
    issued = issue_test_binding(
        registry,
        task_id="task.human-request-schema",
        dispatch_id="dispatch.human-request-schema",
        exposure_ceiling=(NodeOperationName.OPEN_HUMAN_REQUEST,),
    )

    async with node_mcp_client_session(
        applications.managed,
        headers=managed_headers(issued),
    ) as managed_session:
        managed_schema = tool_input_schema(
            await managed_session.list_tools(),
            "open_human_request",
        )
    async with node_mcp_client_session(applications.compatibility) as compatibility_session:
        compatibility_schema = tool_input_schema(
            await compatibility_session.list_tools(),
            "open_human_request",
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
