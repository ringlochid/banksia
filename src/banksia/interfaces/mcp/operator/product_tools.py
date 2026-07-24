from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

import banksia.persistence.session_operations as session_operations
from banksia.interfaces.mcp.mcp_operation_failures import ContractFastMCP
from banksia.interfaces.mcp.tool_teaching import (
    mutating_tool_teaching,
    read_only_tool_teaching,
)
from banksia.persistence.session import get_session_factory
from banksia.runtime.contracts.primitives import (
    HumanRequestResolutionSurface,
    TaskEventSource,
)
from banksia.runtime.contracts.task import (
    CommandRunCancelReceipt,
    CommandRunCancelRequest,
    CommandRunOutputPage,
    CommandRunView,
    HumanRequestResponseInput,
    HumanRequestResponseReceipt,
    HumanRequestResponseRequest,
    TaskControlReceipt,
    TaskControlRequest,
    TaskSearchResponse,
    TaskView,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.product.command_runs import (
    cancel_product_command_run,
    read_product_command_output,
    read_product_command_run,
)
from banksia.runtime.product.human_requests import respond_to_product_human_request
from banksia.runtime.product.tasks import (
    control_product_task,
    read_product_task,
    search_product_tasks,
)

PRODUCT_OPERATOR_TOOL_NAMES: tuple[str, ...] = (
    "task_search",
    "task_get",
    "task_control",
    "human_request_respond",
    "command_run_get",
    "command_run_output_read",
    "command_run_cancel",
)
_OPERATOR_ACTOR_REF = "operator"


def register_product_query_tools(server: FastMCP) -> None:
    _register_task_search(server)
    _register_task_get(server)
    if isinstance(server, ContractFastMCP):
        server.require_strict_tool_inputs(("task_search", "task_get"))


def register_product_action_tools(
    server: FastMCP,
    *,
    dependencies: DispatchOpeningDependencies | None,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
) -> None:
    _register_task_control(
        server,
        dependencies=dependencies,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    _register_human_request_respond(
        server,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    _register_command_run_get(server)
    _register_command_run_output_read(server)
    _register_command_run_cancel(
        server,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    if isinstance(server, ContractFastMCP):
        server.require_strict_tool_inputs(PRODUCT_OPERATOR_TOOL_NAMES[2:])


def _register_task_search(server: FastMCP) -> None:
    teaching = read_only_tool_teaching(
        name="task_search",
        summary="Search runs by human status and presentation fields.",
        details=("Use task_get to read current details and legal actions.",),
    )

    @server.tool(
        name="task_search",
        title=teaching.title,
        description=teaching.description,
        annotations=teaching.annotations,
    )
    async def task_search(
        q: str | None = None,
        status: str = "any",
        cursor: str | None = None,
        limit: int = 50,
    ) -> TaskSearchResponse:
        return await session_operations.read_session_operation(
            lambda session: search_product_tasks(
                session,
                q=q,
                status=status,
                cursor=cursor,
                limit=limit,
            )
        )


def _register_task_get(server: FastMCP) -> None:
    teaching = read_only_tool_teaching(
        name="task_get",
        summary=(
            "Read one run with team, plan, attention, legal actions, Activity, "
            "managed actions, file references, and exact Result."
        ),
    )

    @server.tool(
        name="task_get",
        title=teaching.title,
        description=teaching.description,
        annotations=teaching.annotations,
    )
    async def task_get(task_id: str) -> TaskView:
        return await session_operations.read_session_operation(
            lambda session: read_product_task(session, task_id)
        )


def _register_task_control(
    server: FastMCP,
    *,
    dependencies: DispatchOpeningDependencies | None,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
) -> None:
    teaching = mutating_tool_teaching(
        name="task_control",
        summary="Apply one controller-returned pause, resume, or cancel action.",
        details=("Read task_get first and pass its current opaque action ID.",),
    )

    @server.tool(
        name="task_control",
        title=teaching.title,
        description=teaching.description,
        annotations=teaching.annotations,
    )
    async def task_control(
        task_id: str,
        action_id: str,
        confirmed: bool = False,
    ) -> TaskControlReceipt:
        active_dependencies = _require_dispatch_dependencies(dependencies)
        async with get_session_factory()() as session:
            return await control_product_task(
                session,
                task_id=task_id,
                action_id=action_id,
                request=TaskControlRequest(is_confirmed=confirmed),
                dependencies=active_dependencies,
                actor_ref=_OPERATOR_ACTOR_REF,
                event_source=TaskEventSource.OPERATOR_MCP,
                runtime_effect_publisher=runtime_effect_publisher,
            )


def _register_human_request_respond(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
) -> None:
    teaching = mutating_tool_teaching(
        name="human_request_respond",
        summary="Answer or cancel one current request using its returned action ID.",
        details=("A saved response does not claim that work already continued.",),
    )

    @server.tool(
        name="human_request_respond",
        title=teaching.title,
        description=teaching.description,
        annotations=teaching.annotations,
    )
    async def human_request_respond(
        task_id: str,
        request_id: str,
        action_id: str,
        input: HumanRequestResponseInput,
    ) -> HumanRequestResponseReceipt:
        async with get_session_factory()() as session:
            return await respond_to_product_human_request(
                session,
                task_id=task_id,
                request_id=request_id,
                request=HumanRequestResponseRequest(
                    action_id=action_id,
                    input=input,
                ),
                actor_ref=_OPERATOR_ACTOR_REF,
                resolved_by_surface=HumanRequestResolutionSurface.OPERATOR_MCP,
                runtime_effect_publisher=runtime_effect_publisher,
            )


def _register_command_run_get(server: FastMCP) -> None:
    teaching = read_only_tool_teaching(
        name="command_run_get",
        summary="Read one managed Action's human purpose, state, and legal control.",
    )

    @server.tool(
        name="command_run_get",
        title=teaching.title,
        description=teaching.description,
        annotations=teaching.annotations,
    )
    async def command_run_get(task_id: str, command_id: str) -> CommandRunView:
        return await session_operations.read_session_operation(
            lambda session: read_product_command_run(
                session,
                task_id=task_id,
                command_id=command_id,
            )
        )


def _register_command_run_output_read(server: FastMCP) -> None:
    teaching = read_only_tool_teaching(
        name="command_run_output_read",
        summary="Read one sanitized bounded Action-output page.",
        details=("The response states when the view is bounded, missing, or incomplete.",),
    )

    @server.tool(
        name="command_run_output_read",
        title=teaching.title,
        description=teaching.description,
        annotations=teaching.annotations,
    )
    async def command_run_output_read(
        task_id: str,
        command_id: str,
        cursor: str | None = None,
        limit: int = 65_536,
    ) -> CommandRunOutputPage:
        return await session_operations.read_session_operation(
            lambda session: read_product_command_output(
                session,
                task_id=task_id,
                command_id=command_id,
                cursor=cursor,
                limit=limit,
            )
        )


def _register_command_run_cancel(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
) -> None:
    teaching = mutating_tool_teaching(
        name="command_run_cancel",
        summary="Request cancellation through the managed Action's current action ID.",
        details=("Acceptance does not claim that the process already stopped.",),
    )

    @server.tool(
        name="command_run_cancel",
        title=teaching.title,
        description=teaching.description,
        annotations=teaching.annotations,
    )
    async def command_run_cancel(
        task_id: str,
        command_id: str,
        action_id: str,
        confirmed: Literal[True],
    ) -> CommandRunCancelReceipt:
        async with get_session_factory()() as session:
            return await cancel_product_command_run(
                session,
                task_id=task_id,
                command_id=command_id,
                request=CommandRunCancelRequest(
                    action_id=action_id,
                    is_confirmed=confirmed,
                ),
                actor_ref=_OPERATOR_ACTOR_REF,
                runtime_effect_publisher=runtime_effect_publisher,
            )


def _require_dispatch_dependencies(
    dependencies: DispatchOpeningDependencies | None,
) -> DispatchOpeningDependencies:
    if dependencies is None:
        raise RuntimeError("Task control is unavailable until the controller is ready.")
    return dependencies


__all__ = [
    "PRODUCT_OPERATOR_TOOL_NAMES",
    "register_product_action_tools",
    "register_product_query_tools",
]
