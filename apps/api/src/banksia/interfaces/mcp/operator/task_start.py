from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from banksia.interfaces.mcp.mcp_operation_failures import ContractFastMCP
from banksia.interfaces.mcp.tool_teaching import (
    LOCAL_FILE_PATH_NOTE,
    RUNTIME_STATE_WARNING,
    mutating_tool_teaching,
)
from banksia.platform.file_entrypoints import task_start_request_from_path
from banksia.runtime.contracts import TaskStartResponse
from banksia.runtime.node_operations.follow_on import SupportProjectionPublisher
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.task_start import start_task as start_task_service

START_TASK_TEACHING = mutating_tool_teaching(
    name="start_task",
    summary="Load one Task Compose file and commit a real Workflow-backed Task.",
    details=(
        LOCAL_FILE_PATH_NOTE,
        RUNTIME_STATE_WARNING,
        "This is the bounded pre-WP-03 compatibility entry point, not a preview.",
        "The response means Task bootstrap and its Flow-start source committed.",
        "Root Dispatch opening and provider start happen asynchronously after that commit.",
    ),
)


def register_task_start_tool(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    support_projection_publisher: SupportProjectionPublisher | None = None,
) -> None:
    @server.tool(
        name="start_task",
        title=START_TASK_TEACHING.title,
        description=START_TASK_TEACHING.description,
        annotations=START_TASK_TEACHING.annotations,
    )
    async def start_task(task_compose_path: str) -> TaskStartResponse:
        request = task_start_request_from_path(task_compose_path)
        return await start_task_service(
            request,
            runtime_effect_publisher=runtime_effect_publisher,
            support_projection_publisher=support_projection_publisher,
        )

    if isinstance(server, ContractFastMCP):
        server.require_strict_tool_inputs(("start_task",))


__all__ = ["START_TASK_TEACHING", "register_task_start_tool"]
