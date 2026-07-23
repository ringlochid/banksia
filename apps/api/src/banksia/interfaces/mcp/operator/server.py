from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations.follow_on import SupportProjectionPublisher
from banksia.runtime.post_commit import RuntimeEffectPublisher

from ..mcp_operation_failures import ContractFastMCP
from ..transport import local_mcp_transport_security
from .runtime_tools import (
    register_operator_read_tools,
    register_runtime_control_tools,
    register_runtime_task_tools,
    register_runtime_wait_tools,
)
from .task_start import register_task_start_tool
from .workflow_tools import WORKFLOW_OPERATOR_TOOL_NAMES, register_workflow_tools

OPERATOR_TOOL_NAMES: tuple[str, ...] = (
    *WORKFLOW_OPERATOR_TOOL_NAMES,
    "start_task",
    "list_runtime_tasks",
    "get_runtime_task",
    "get_operator_snapshot",
    "get_operator_trace",
    "get_task_events",
    "get_human_requests",
    "resolve_human_request",
    "get_command_runs",
    "get_command_run",
    "get_command_run_log",
    "cancel_command_run",
    "pause_task",
    "continue_task",
    "cancel_task",
)
_OPERATOR_MCP_INSTRUCTIONS = (
    "Operator-safe Banksia surface.\n\n"
    "Observe first:\n"
    "- use get_runtime_task for current task status checks.\n"
    "- then use get_operator_snapshot and get_operator_trace for "
    "current state and timeline detail.\n\n"
    "Task chronology:\n"
    "- use get_task_events for bounded chronological backfill after reading "
    "current source truth. Cursors are exclusive and task-bound.\n"
    "- events explain how state changed; they never replace current state. "
    "If a cursor must reset, reread current state and restart chronology.\n\n"
    "Mutating controls:\n"
    "- pause_task, continue_task, and cancel_task change runtime state.\n"
    "- continue_task is not a status-check or polling tool and "
    "should use fresh expected_active_flow_revision_id and "
    "expected_control_revision values from a current runtime read.\n"
    "- mutation responses report committed controller truth only. Cleanup and "
    "provider start remain asynchronous; no control waits for provider stop, output, "
    "or completion.\n\n"
    "Human requests and command runs:\n"
    "- get_human_requests and resolve_human_request are the dedicated "
    "inspection and answer path for current pending requests.\n"
    "- get_command_runs, get_command_run, get_command_run_log, and "
    "cancel_command_run are the dedicated command-run inspection and "
    "control tools; they do not replace whole-task cancel.\n"
    "- resolving a request commits its answer before return; successor opening is "
    "independent. Command cancellation returns at cancellation_requested, not process "
    "exit or terminalization.\n\n"
    "Workflow authoring:\n"
    "- workflow_search, workflow_get, and workflow_authoring_options are read-only.\n"
    "- workflow_draft_create, workflow_draft_edit, workflow_draft_validate, "
    "workflow_draft_undo, workflow_draft_discard, and workflow_draft_publish "
    "operate controller-owned Workflow drafts and immutable publication.\n"
    "- draft edits and Undo use the fresh opaque ETag returned by the prior operation. "
    "Draft creation, editing, and validation never publish or start runtime work.\n\n"
    "Task start:\n"
    "- start_task loads the bounded local Task Compose bridge and commits a real Task.\n"
    "- its receipt confirms controller commit, not provider start or completion.\n\n"
    "Surface continuity:\n"
    "- runtime, operator, and chronology reads stay on this same local "
    "operator MCP surface.\n"
    "- Workflow authoring remains separate from node-tool execution."
)


@dataclass(frozen=True, slots=True)
class OperatorEffectPublishers:
    """Optional app-owned publication ports used by operator mutations."""

    runtime_effect_publisher: RuntimeEffectPublisher | None = None
    support_projection_publisher: SupportProjectionPublisher | None = None
    dispatch_opening_dependencies: DispatchOpeningDependencies | None = None


def create_operator_mcp_app(
    *,
    host: str = "127.0.0.1",
    port: int = 18125,
    allowed_origins: tuple[str, ...] = (),
    transport_security: TransportSecuritySettings | None = None,
    effect_publishers: OperatorEffectPublishers | None = None,
) -> Starlette:
    return create_operator_mcp_server(
        host=host,
        port=port,
        allowed_origins=allowed_origins,
        transport_security=transport_security,
        effect_publishers=effect_publishers,
    ).streamable_http_app()


def create_operator_mcp_server(
    *,
    host: str = "127.0.0.1",
    port: int = 18125,
    allowed_origins: tuple[str, ...] = (),
    transport_security: TransportSecuritySettings | None = None,
    effect_publishers: OperatorEffectPublishers | None = None,
) -> FastMCP:
    publishers = effect_publishers or OperatorEffectPublishers()
    server = ContractFastMCP(
        "banksia-operator",
        instructions=_OPERATOR_MCP_INSTRUCTIONS,
        json_response=True,
        stateless_http=True,
        transport_security=transport_security
        or local_mcp_transport_security(
            host=host,
            port=port,
            allowed_origins=allowed_origins,
        ),
    )
    register_workflow_tools(server)
    register_task_start_tool(
        server,
        runtime_effect_publisher=publishers.runtime_effect_publisher,
        support_projection_publisher=publishers.support_projection_publisher,
    )
    register_runtime_task_tools(server)
    register_operator_read_tools(server)
    register_runtime_wait_tools(
        server,
        runtime_effect_publisher=publishers.runtime_effect_publisher,
    )
    register_runtime_control_tools(
        server,
        runtime_effect_publisher=publishers.runtime_effect_publisher,
        dependencies=publishers.dispatch_opening_dependencies,
    )
    return server


__all__ = [
    "OPERATOR_TOOL_NAMES",
    "OperatorEffectPublishers",
    "create_operator_mcp_app",
    "create_operator_mcp_server",
]
