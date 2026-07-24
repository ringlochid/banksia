from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from banksia.interfaces.mcp.mcp_operation_failures import ContractFastMCP
from banksia.interfaces.mcp.tool_teaching import (
    RUNTIME_STATE_WARNING,
    mutating_tool_teaching,
)
from banksia.runtime.contracts import FileReference, TaskStartRequest
from banksia.runtime.contracts.task import TaskStartReceipt
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.product.tasks import start_product_task

TASK_START_TEACHING = mutating_tool_teaching(
    name="task_start",
    summary="Validate and commit one real Workflow-backed Task.",
    details=(
        RUNTIME_STATE_WARNING,
        "Submit the same strict workflow, prompt, optional workspace, and files object "
        "used by HTTP and Console Task start.",
        "The accepted receipt confirms controller commit, not provider start or completion.",
    ),
)


def register_task_start_tool(
    server: FastMCP,
    *,
    dependencies: DispatchOpeningDependencies | None = None,
) -> None:
    @server.tool(
        name="task_start",
        title=TASK_START_TEACHING.title,
        description=TASK_START_TEACHING.description,
        annotations=TASK_START_TEACHING.annotations,
    )
    async def task_start(
        workflow: str,
        prompt: str,
        workspace: str | None = None,
        files: list[FileReference] | None = None,
    ) -> TaskStartReceipt:
        if dependencies is None:
            raise RuntimeError("Task-start dependencies are unavailable")
        request = TaskStartRequest(
            workflow=workflow,
            prompt=prompt,
            workspace=Path(workspace) if workspace is not None else None,
            files=tuple(files or ()),
        )
        return await start_product_task(
            request,
            dependencies=dependencies,
            default_workspace=dependencies.settings.controller_workspace,
        )

    if isinstance(server, ContractFastMCP):
        server.require_strict_tool_inputs(("task_start",))


__all__ = ["TASK_START_TEACHING", "register_task_start_tool"]
