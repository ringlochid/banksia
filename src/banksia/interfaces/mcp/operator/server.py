from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import RuntimeEffectPublisher

from ..mcp_operation_failures import ContractFastMCP
from ..transport import local_mcp_transport_security
from .product_tools import (
    PRODUCT_OPERATOR_TOOL_NAMES,
    register_product_action_tools,
    register_product_query_tools,
)
from .task_start import register_task_start_tool
from .workflow_tools import WORKFLOW_OPERATOR_TOOL_NAMES, register_workflow_tools

OPERATOR_TOOL_NAMES: tuple[str, ...] = (
    *WORKFLOW_OPERATOR_TOOL_NAMES,
    *PRODUCT_OPERATOR_TOOL_NAMES[:2],
    "task_start",
    *PRODUCT_OPERATOR_TOOL_NAMES[2:],
)
_OPERATOR_MCP_INSTRUCTIONS = (
    "Banksia product operations for Workflow and Run Studio.\n\n"
    "Read before changing:\n"
    "- use workflow_get or task_get to read current controller truth and legal actions.\n"
    "- use only action IDs returned by the current resource.\n\n"
    "Mutation receipts:\n"
    "- a saved Human Request response does not claim that work already continued.\n"
    "- an accepted managed Action cancellation does not claim the process already stopped.\n"
    "- a Task start receipt confirms admission, not provider start or completion.\n\n"
    "Workflow authoring:\n"
    "- workflow_search, workflow_get, and workflow_authoring_options are read-only.\n"
    "- workflow_draft_create, workflow_draft_edit, workflow_draft_validate, "
    "workflow_draft_undo, workflow_draft_discard, and workflow_draft_publish "
    "operate controller-owned Workflow drafts and immutable publication.\n"
    "- draft edits and Undo use the fresh opaque ETag returned by the prior operation. "
    "Draft creation, editing, and validation never publish or start runtime work.\n\n"
    "Runs:\n"
    "- task_search and task_get return product status, Activity, attention, Result, "
    "and current legal actions.\n"
    "- task_control, human_request_respond, and command_run_cancel require a current "
    "opaque action ID. There is no generic execute-anything operation."
)


@dataclass(frozen=True, slots=True)
class OperatorEffectPublishers:
    """Optional app-owned publication ports used by operator mutations."""

    runtime_effect_publisher: RuntimeEffectPublisher | None = None
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
    register_product_query_tools(server)
    register_task_start_tool(
        server,
        dependencies=publishers.dispatch_opening_dependencies,
    )
    register_product_action_tools(
        server,
        dependencies=publishers.dispatch_opening_dependencies,
        runtime_effect_publisher=publishers.runtime_effect_publisher,
    )
    return server


__all__ = [
    "OPERATOR_TOOL_NAMES",
    "OperatorEffectPublishers",
    "create_operator_mcp_app",
    "create_operator_mcp_server",
]
