from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import (
    AbsolutePathBuf,
    AskForApproval,
    ConfigReadResponse,
    LegacyAppPathString,
    ListMcpServerStatusResponse,
    SandboxPolicy,
    SkillsListResponse,
    Thread,
)
from openai_codex.models import JsonObject
from pydantic import BaseModel, ConfigDict, Field

from banksia.platform.provider_environment import provider_subprocess_environment_overrides
from banksia.providers import ManagedSandboxMode, NetworkAccess
from banksia.runtime.providers.contracts import (
    MANAGED_NODE_MCP_SERVER_NAME,
    ManagedNodeMcpConnection,
)

_CONFIG_READ_METHOD = "config/read"
_MCP_STATUS_METHOD = "mcpServerStatus/list"
_SKILLS_LIST_METHOD = "skills/list"

# These features can add instructions, tools, agents, remote extensions, or
# provider-owned continuity. Native shell and unified exec intentionally remain.
_TASK_DISABLED_CODEX_FEATURES = frozenset(
    """
    apps artifact auth_elicitation browser_use browser_use_external
    browser_use_full_cdp_access chronicle code_mode code_mode_host code_mode_only
    computer_use current_time_reminder default_mode_request_user_input
    deferred_executor enable_fanout enable_mcp_apps exec_permission_approvals
    goals guardian_approval hooks image_generation in_app_browser memories
    multi_agent multi_agent_v2 non_prefixed_mcp_tool_names personality plugins
    plugin_sharing realtime_conversation remote_plugin request_permissions_tool
    rollout_budget shell_snapshot skill_mcp_dependency_install
    standalone_web_search terminal_visualization_instructions token_budget
    tool_call_mcp_elicitation tool_suggest web_search_cached web_search_request
    workspace_dependencies
    """.split()
)
_TASK_ENABLED_CODEX_FEATURES = frozenset({"shell_tool", "unified_exec"})
_INSTRUCTION_CONFIG_KEYS = frozenset(
    {
        "compact_prompt",
        "developer_instructions",
        "experimental_compact_prompt_file",
        "experimental_realtime_start_instructions",
        "experimental_realtime_ws_backend_prompt",
        "experimental_realtime_ws_startup_context",
        "experimental_thread_config_endpoint",
        "instructions",
        "model_instructions_file",
    }
)
_TASK_PROCESS_SCALAR_OVERRIDES = (
    "allow_login_shell=false",
    "apps._default.enabled=false",
    "check_for_update_on_startup=false",
    "include_apps_instructions=false",
    "include_collaboration_mode_instructions=false",
    "notify=[]",
    "orchestrator.mcp.enabled=false",
    "orchestrator.skills.enabled=false",
    "project_doc_max_bytes=0",
    "skills.bundled.enabled=false",
    "skills.include_instructions=false",
    "tools.experimental_request_user_input.enabled=false",
    'web_search="disabled"',
)

type CodexServerRequestHandler = Callable[[str, JsonObject | None], JsonObject]


class CodexIsolationError(RuntimeError):
    """The adapter could not prove the required invocation-local surface."""


class CodexTaskThreadStartResponse(BaseModel):
    """Experimental thread/start fields required for pre-turn verification."""

    model_config = ConfigDict(populate_by_name=True)

    approval_policy: AskForApproval = Field(alias="approvalPolicy")
    cwd: AbsolutePathBuf
    instruction_sources: list[LegacyAppPathString] = Field(alias="instructionSources")
    model: str
    runtime_workspace_roots: list[AbsolutePathBuf] = Field(alias="runtimeWorkspaceRoots")
    sandbox: SandboxPolicy
    thread: Thread


@dataclass(frozen=True, slots=True)
class CodexAmbientState:
    mcp_server_names: tuple[str, ...]
    skill_paths: tuple[Path, ...]


def build_codex_client(handler: CodexServerRequestHandler) -> CodexClient:
    """Launch against the real provider home while isolating one invocation."""

    return CodexClient(
        CodexConfig(
            config_overrides=codex_task_process_overrides(),
            env=provider_subprocess_environment_overrides(),
            experimental_api=True,
        ),
        approval_handler=handler,
    )


def codex_task_process_overrides() -> tuple[str, ...]:
    """Return fixed process-start isolation that precedes effective-config readback."""

    feature_overrides = (
        *(f"features.{feature}=false" for feature in sorted(_TASK_DISABLED_CODEX_FEATURES)),
        *(f"features.{feature}=true" for feature in sorted(_TASK_ENABLED_CODEX_FEATURES)),
    )
    return (*_TASK_PROCESS_SCALAR_OVERRIDES, *feature_overrides)


def read_codex_ambient_state(
    client: CodexClient,
    workspace: Path,
) -> CodexAmbientState:
    config_response = client.request(
        _CONFIG_READ_METHOD,
        {"cwd": str(workspace), "includeLayers": False},
        response_model=ConfigReadResponse,
    )
    effective = config_response.config.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    for key in _INSTRUCTION_CONFIG_KEYS:
        value = effective.get(key)
        if value is not None and (not isinstance(value, str) or value.strip()):
            raise CodexIsolationError("Codex has an ambient instruction-bearing configuration")

    configured_mcp = effective.get("mcp_servers", {})
    if not isinstance(configured_mcp, dict) or not all(
        isinstance(name, str) and name.strip() == name and name for name in configured_mcp
    ):
        raise CodexIsolationError("Codex returned an invalid MCP configuration")

    skills_response = client.request(
        _SKILLS_LIST_METHOD,
        {"cwds": [str(workspace)], "forceReload": True},
        response_model=SkillsListResponse,
    )
    if len(skills_response.data) != 1:
        raise CodexIsolationError("Codex returned an incomplete Skill inventory")
    entry = skills_response.data[0]
    if _canonical_path(entry.cwd) != workspace or entry.errors:
        raise CodexIsolationError("Codex could not prove its Skill inventory")

    skill_paths: set[Path] = set()
    for skill in entry.skills:
        path = _path_value(skill.path)
        if not path.is_absolute() or path.name != "SKILL.md":
            raise CodexIsolationError("Codex returned an invalid Skill path")
        skill_paths.add(path)
    return CodexAmbientState(
        mcp_server_names=tuple(sorted(configured_mcp)),
        skill_paths=tuple(sorted(skill_paths)),
    )


def build_codex_task_isolation_config(
    ambient: CodexAmbientState,
    *,
    connection: ManagedNodeMcpConnection,
    network_access: NetworkAccess,
    sandbox_mode: ManagedSandboxMode,
    workspace: Path,
) -> JsonObject:
    mcp_servers: dict[str, object] = {name: {"enabled": False} for name in ambient.mcp_server_names}
    mcp_servers[MANAGED_NODE_MCP_SERVER_NAME] = {
        "default_tools_approval_mode": "approve",
        "enabled": True,
        "enabled_tools": list(connection.enabled_tools),
        "http_headers": {"Authorization": connection.authorization_header},
        "required": True,
        "url": connection.url,
    }
    config: dict[str, object] = {
        "allow_login_shell": False,
        "apps": {"_default": {"enabled": False}},
        "check_for_update_on_startup": False,
        "features": {
            **{feature: False for feature in _TASK_DISABLED_CODEX_FEATURES},
            **{feature: True for feature in _TASK_ENABLED_CODEX_FEATURES},
        },
        "include_apps_instructions": False,
        "include_collaboration_mode_instructions": False,
        "mcp_servers": mcp_servers,
        "notify": [],
        "orchestrator": {
            "mcp": {"enabled": False},
            "skills": {"enabled": False},
        },
        "project_doc_max_bytes": 0,
        "projects": {str(workspace): {"trust_level": "untrusted"}},
        "skills": {
            "bundled": {"enabled": False},
            "config": [{"enabled": False, "path": str(path)} for path in ambient.skill_paths],
            "include_instructions": False,
        },
        "tools": {"experimental_request_user_input": {"enabled": False}},
        "web_search": "disabled",
    }
    if sandbox_mode is ManagedSandboxMode.WORKSPACE_WRITE:
        config["sandbox_workspace_write"] = {
            "network_access": network_access is NetworkAccess.ALLOW
        }
    return cast(JsonObject, config)


def require_codex_task_thread_isolation(
    response: CodexTaskThreadStartResponse,
    *,
    expected_model: str | None,
    network_access: NetworkAccess,
    sandbox_mode: ManagedSandboxMode,
    workspace: Path,
) -> None:
    if response.instruction_sources:
        raise CodexIsolationError("Codex loaded an external instruction source")
    if _canonical_path(response.cwd) != workspace:
        raise CodexIsolationError("Codex changed the Task working directory")
    if _canonical_path(response.thread.cwd) != workspace:
        raise CodexIsolationError("Codex changed the thread working directory")
    if tuple(_canonical_path(path) for path in response.runtime_workspace_roots) != (workspace,):
        raise CodexIsolationError("Codex changed the runtime workspace roots")
    if not response.thread.ephemeral:
        raise CodexIsolationError("Codex created a persistent Task thread")
    approval = getattr(response.approval_policy.root, "value", response.approval_policy.root)
    if approval != "never":
        raise CodexIsolationError("Codex changed the approval policy")
    if expected_model is not None and response.model != expected_model:
        raise CodexIsolationError("Codex changed the requested model")

    sandbox = response.sandbox.root
    expected_type = {
        ManagedSandboxMode.READ_ONLY: "readOnly",
        ManagedSandboxMode.WORKSPACE_WRITE: "workspaceWrite",
        ManagedSandboxMode.FULL_ACCESS: "dangerFullAccess",
    }[sandbox_mode]
    if getattr(sandbox, "type", None) != expected_type:
        raise CodexIsolationError("Codex changed the requested sandbox")
    if sandbox_mode is ManagedSandboxMode.WORKSPACE_WRITE:
        expected_network = network_access is NetworkAccess.ALLOW
        if getattr(sandbox, "network_access", None) is not expected_network:
            raise CodexIsolationError("Codex changed workspace network access")


def require_codex_task_mcp_isolation(
    client: CodexClient,
    *,
    enabled_tools: tuple[str, ...],
    thread_id: str,
) -> None:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    servers: dict[str, Any] = {}
    while True:
        params: JsonObject = {
            "detail": "full",
            "limit": 100,
            "threadId": thread_id,
        }
        if cursor is not None:
            params["cursor"] = cursor
        response = client.request(
            _MCP_STATUS_METHOD,
            params,
            response_model=ListMcpServerStatusResponse,
        )
        for server in response.data:
            if server.name in servers:
                raise CodexIsolationError("Codex returned duplicate MCP status")
            servers[server.name] = server
        cursor = response.next_cursor
        if cursor is None:
            break
        if cursor in seen_cursors:
            raise CodexIsolationError("Codex returned an invalid MCP status page")
        seen_cursors.add(cursor)

    active = {
        name
        for name, server in servers.items()
        if (
            server.tools
            or server.resources
            or server.resource_templates
            or server.server_info is not None
        )
    }
    if active != {MANAGED_NODE_MCP_SERVER_NAME}:
        raise CodexIsolationError("Codex exposed an inexact MCP server surface")
    node = servers[MANAGED_NODE_MCP_SERVER_NAME]
    if (
        node.server_info is None
        or set(node.tools) != set(enabled_tools)
        or node.resources
        or node.resource_templates
    ):
        raise CodexIsolationError("Codex exposed an inexact Banksia Node surface")


def deny_codex_task_server_request(
    method: str,
    params: JsonObject | None,
) -> JsonObject:
    del params
    if method in {
        "applyPatchApproval",
        "execCommandApproval",
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }:
        return {"decision": "cancel"}
    if method == "item/permissions/requestApproval":
        return {"permissions": {}}
    if method == "item/tool/requestUserInput":
        return {"answers": {}}
    if method == "mcpServer/elicitation/request":
        return {"action": "cancel"}
    raise CodexIsolationError("Codex requested an unsupported Task capability")


def _canonical_path(value: object) -> Path:
    return _path_value(value).resolve(strict=False)


def _path_value(value: object) -> Path:
    raw = getattr(value, "root", value)
    if not isinstance(raw, str) or not raw:
        raise CodexIsolationError("Codex returned an invalid path")
    return Path(raw)


__all__ = [
    "CodexAmbientState",
    "CodexIsolationError",
    "CodexServerRequestHandler",
    "CodexTaskThreadStartResponse",
    "build_codex_client",
    "build_codex_task_isolation_config",
    "codex_task_process_overrides",
    "deny_codex_task_server_request",
    "read_codex_ambient_state",
    "require_codex_task_mcp_isolation",
    "require_codex_task_thread_isolation",
]
