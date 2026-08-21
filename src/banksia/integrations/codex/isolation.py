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
from banksia.providers import ManagedExtensionMode, ManagedSandboxMode, NetworkAccess
from banksia.runtime.providers.contracts import (
    MANAGED_NODE_MCP_SERVER_NAME,
    ManagedNodeMcpConnection,
    ProviderExtensionInventory,
    ProviderMcpServerInventory,
)

_CONFIG_READ_METHOD = "config/read"
_MCP_STATUS_METHOD = "mcpServerStatus/list"
_SKILLS_LIST_METHOD = "skills/list"

# These features can add instructions, tools, agents, remote extensions, or
# provider-owned continuity. Native shell and unified exec intentionally remain.
_MANAGED_DISABLED_CODEX_FEATURES = frozenset(
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
_PROCESS_COMMON_SCALAR_OVERRIDES = (
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
    "tools.experimental_request_user_input.enabled=false",
    'web_search="disabled"',
)

type CodexServerRequestHandler = Callable[[str, JsonObject | None], JsonObject]


class CodexIsolationError(RuntimeError):
    """The adapter could not prove the required invocation-local surface."""


class _CodexThreadIsolationResponse(BaseModel):
    """Experimental thread fields required for pre-turn verification."""

    model_config = ConfigDict(populate_by_name=True)

    approval_policy: AskForApproval = Field(alias="approvalPolicy")
    cwd: AbsolutePathBuf
    instruction_sources: list[LegacyAppPathString] = Field(alias="instructionSources")
    model: str
    runtime_workspace_roots: list[AbsolutePathBuf] = Field(alias="runtimeWorkspaceRoots")
    sandbox: SandboxPolicy
    thread: Thread


class CodexTaskThreadStartResponse(_CodexThreadIsolationResponse):
    """Task thread/start readback required for pre-turn verification."""


class CodexOperatorThreadResponse(_CodexThreadIsolationResponse):
    """Operator thread start/resume readback required for pre-turn verification."""


@dataclass(frozen=True, slots=True)
class CodexAmbientSkill:
    name: str
    path: Path
    scope: str
    is_enabled: bool


@dataclass(frozen=True, slots=True)
class CodexAmbientState:
    mcp_server_names: tuple[str, ...]
    skills: tuple[CodexAmbientSkill, ...]


def build_codex_client(
    handler: CodexServerRequestHandler,
    *,
    extension_mode: ManagedExtensionMode = ManagedExtensionMode.ISOLATED,
) -> CodexClient:
    """Launch against the real provider home while isolating one invocation."""

    return CodexClient(
        CodexConfig(
            config_overrides=codex_process_isolation_overrides(extension_mode),
            env=provider_subprocess_environment_overrides(),
            experimental_api=True,
        ),
        approval_handler=handler,
    )


def codex_process_isolation_overrides(
    extension_mode: ManagedExtensionMode = ManagedExtensionMode.ISOLATED,
) -> tuple[str, ...]:
    """Return fixed process-start isolation that precedes effective-config readback."""

    feature_overrides = (
        *(f"features.{feature}=false" for feature in sorted(_MANAGED_DISABLED_CODEX_FEATURES)),
        *(f"features.{feature}=true" for feature in sorted(_TASK_ENABLED_CODEX_FEATURES)),
    )
    return (
        *_PROCESS_COMMON_SCALAR_OVERRIDES,
        (
            "skills.include_instructions=true"
            if extension_mode is ManagedExtensionMode.INHERIT
            else "skills.include_instructions=false"
        ),
        *feature_overrides,
    )


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
    if _canonical_path(entry.cwd) != _resolved_path(workspace) or entry.errors:
        raise CodexIsolationError("Codex could not prove its Skill inventory")

    skills: dict[Path, CodexAmbientSkill] = {}
    for skill in entry.skills:
        path = _path_value(skill.path)
        if not path.is_absolute() or path.name != "SKILL.md":
            raise CodexIsolationError("Codex returned an invalid Skill path")
        name = getattr(skill, "name", None)
        raw_scope = getattr(skill, "scope", None)
        scope = getattr(raw_scope, "value", raw_scope)
        is_enabled = getattr(skill, "enabled", None)
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(scope, str)
            or not isinstance(is_enabled, bool)
        ):
            raise CodexIsolationError("Codex returned invalid Skill metadata")
        skills[path] = CodexAmbientSkill(
            name=name.strip(),
            path=path,
            scope=scope,
            is_enabled=is_enabled,
        )
    return CodexAmbientState(
        mcp_server_names=tuple(sorted(configured_mcp)),
        skills=tuple(skills[path] for path in sorted(skills)),
    )


def build_codex_task_config(
    ambient: CodexAmbientState,
    *,
    connection: ManagedNodeMcpConnection,
    extension_mode: ManagedExtensionMode,
    network_access: NetworkAccess,
    sandbox_mode: ManagedSandboxMode,
    workspace: Path,
) -> JsonObject:
    config = _build_codex_isolation_config(
        ambient,
        disabled_features=_MANAGED_DISABLED_CODEX_FEATURES,
        enabled_features=_TASK_ENABLED_CODEX_FEATURES,
        extension_mode=extension_mode,
        workspace=workspace,
    )
    mcp_servers = cast(dict[str, object], config["mcp_servers"])
    mcp_servers[MANAGED_NODE_MCP_SERVER_NAME] = {
        "default_tools_approval_mode": "approve",
        "enabled": True,
        "enabled_tools": list(connection.enabled_tools),
        "http_headers": {"Authorization": connection.authorization_header},
        "required": True,
        "url": connection.url,
    }
    if sandbox_mode is ManagedSandboxMode.WORKSPACE_WRITE:
        config["sandbox_workspace_write"] = {
            "network_access": network_access is NetworkAccess.ALLOW
        }
    return cast(JsonObject, config)


def build_codex_operator_isolation_config(
    ambient: CodexAmbientState,
    *,
    workspace: Path,
) -> JsonObject:
    config = _build_codex_isolation_config(
        ambient,
        disabled_features=_MANAGED_DISABLED_CODEX_FEATURES | _TASK_ENABLED_CODEX_FEATURES,
        enabled_features=frozenset(),
        extension_mode=ManagedExtensionMode.ISOLATED,
        workspace=workspace,
    )
    config["include_environment_context"] = False
    config["include_permissions_instructions"] = False
    return cast(JsonObject, config)


def require_codex_task_thread_isolation(
    response: CodexTaskThreadStartResponse,
    *,
    expected_model: str | None,
    network_access: NetworkAccess,
    sandbox_mode: ManagedSandboxMode,
    workspace: Path,
) -> None:
    expected_type = {
        ManagedSandboxMode.READ_ONLY: "readOnly",
        ManagedSandboxMode.WORKSPACE_WRITE: "workspaceWrite",
        ManagedSandboxMode.FULL_ACCESS: "dangerFullAccess",
    }[sandbox_mode]
    _require_codex_thread_isolation(
        response,
        expected_ephemeral=True,
        expected_model=expected_model,
        expected_runtime_roots=(workspace,),
        expected_sandbox=expected_type,
        expected_thread_cwd=workspace,
        workspace=workspace,
    )
    if sandbox_mode is ManagedSandboxMode.WORKSPACE_WRITE:
        sandbox = response.sandbox.root
        expected_network = network_access is NetworkAccess.ALLOW
        if getattr(sandbox, "network_access", None) is not expected_network:
            raise CodexIsolationError("Codex changed workspace network access")


def require_codex_operator_thread_isolation(
    response: CodexOperatorThreadResponse,
    *,
    expected_model: str | None,
    expected_thread_cwd: Path | None,
    workspace: Path,
) -> None:
    _require_codex_thread_isolation(
        response,
        expected_ephemeral=False,
        expected_model=expected_model,
        expected_runtime_roots=(),
        expected_sandbox="readOnly",
        expected_thread_cwd=expected_thread_cwd,
        workspace=workspace,
    )


def validate_codex_task_extensions(
    client: CodexClient,
    *,
    ambient: CodexAmbientState,
    enabled_tools: tuple[str, ...],
    extension_mode: ManagedExtensionMode,
    thread_id: str,
) -> ProviderExtensionInventory:
    servers = _read_codex_mcp_servers(client, thread_id)
    active = {name for name, server in servers.items() if _codex_mcp_server_is_active(server)}
    if MANAGED_NODE_MCP_SERVER_NAME not in active:
        raise CodexIsolationError("Codex did not expose the Oh My Subagents Node surface")
    if extension_mode is ManagedExtensionMode.ISOLATED and active != {MANAGED_NODE_MCP_SERVER_NAME}:
        raise CodexIsolationError("Codex exposed an inexact MCP server surface")
    node = servers[MANAGED_NODE_MCP_SERVER_NAME]
    if (
        node.server_info is None
        or set(node.tools) != set(enabled_tools)
        or node.resources
        or node.resource_templates
    ):
        raise CodexIsolationError("Codex exposed an inexact Oh My Subagents Node surface")
    if extension_mode is ManagedExtensionMode.ISOLATED:
        return ProviderExtensionInventory()
    return ProviderExtensionInventory(
        skills=tuple(
            sorted(
                {
                    skill.name
                    for skill in ambient.skills
                    if skill.scope in {"user", "repo"} and skill.is_enabled
                }
            )
        ),
        mcp_servers=tuple(
            ProviderMcpServerInventory(
                name=name,
                tools=tuple(sorted(servers[name].tools)),
            )
            for name in sorted(active - {MANAGED_NODE_MCP_SERVER_NAME})
        ),
    )


def require_codex_inert_mcp_isolation(
    client: CodexClient,
    *,
    thread_id: str,
) -> None:
    if any(
        _codex_mcp_server_is_active(server)
        for server in _read_codex_mcp_servers(client, thread_id).values()
    ):
        raise CodexIsolationError("Codex exposed an external MCP surface to Operator")


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


def _build_codex_isolation_config(
    ambient: CodexAmbientState,
    *,
    disabled_features: frozenset[str],
    enabled_features: frozenset[str],
    extension_mode: ManagedExtensionMode,
    workspace: Path,
) -> dict[str, object]:
    inherited = extension_mode is ManagedExtensionMode.INHERIT
    return {
        "allow_login_shell": False,
        "apps": {"_default": {"enabled": False}},
        "check_for_update_on_startup": False,
        "features": {
            **{feature: False for feature in disabled_features},
            **{feature: True for feature in enabled_features},
        },
        "include_apps_instructions": False,
        "include_collaboration_mode_instructions": False,
        "mcp_servers": (
            {} if inherited else {name: {"enabled": False} for name in ambient.mcp_server_names}
        ),
        "notify": [],
        "orchestrator": {
            "mcp": {"enabled": False},
            "skills": {"enabled": False},
        },
        "project_doc_max_bytes": 0,
        "projects": {str(workspace): {"trust_level": "untrusted"}},
        "skills": {
            "bundled": {"enabled": False},
            "config": [
                {"enabled": False, "path": str(skill.path)}
                for skill in ambient.skills
                if not inherited or skill.scope not in {"user", "repo"}
            ],
            "include_instructions": inherited,
        },
        "tools": {"experimental_request_user_input": {"enabled": False}},
        "web_search": "disabled",
    }


def _require_codex_thread_isolation(
    response: _CodexThreadIsolationResponse,
    *,
    expected_ephemeral: bool,
    expected_model: str | None,
    expected_runtime_roots: tuple[Path, ...],
    expected_sandbox: str,
    expected_thread_cwd: Path | None = None,
    workspace: Path,
) -> None:
    if response.instruction_sources:
        raise CodexIsolationError("Codex loaded an external instruction source")
    if _canonical_path(response.cwd) != _resolved_path(workspace):
        raise CodexIsolationError("Codex changed the working directory")
    if expected_thread_cwd is not None and _canonical_path(response.thread.cwd) != _resolved_path(
        expected_thread_cwd
    ):
        raise CodexIsolationError("Codex changed the thread working directory")
    if tuple(_canonical_path(path) for path in response.runtime_workspace_roots) != tuple(
        _resolved_path(path) for path in expected_runtime_roots
    ):
        raise CodexIsolationError("Codex changed the runtime workspace roots")
    if response.thread.ephemeral is not expected_ephemeral:
        raise CodexIsolationError("Codex changed thread persistence")
    approval = getattr(response.approval_policy.root, "value", response.approval_policy.root)
    if approval != "never":
        raise CodexIsolationError("Codex changed the approval policy")
    if expected_model is not None and response.model != expected_model:
        raise CodexIsolationError("Codex changed the requested model")
    if getattr(response.sandbox.root, "type", None) != expected_sandbox:
        raise CodexIsolationError("Codex changed the requested sandbox")


def _read_codex_mcp_servers(
    client: CodexClient,
    thread_id: str,
) -> dict[str, Any]:
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
    return servers


def _codex_mcp_server_is_active(server: Any) -> bool:
    return bool(
        server.tools
        or server.resources
        or server.resource_templates
        or server.server_info is not None
    )


def _canonical_path(value: object) -> Path:
    return _path_value(value).resolve(strict=False)


def _resolved_path(path: Path) -> Path:
    return path.resolve(strict=False)


def _path_value(value: object) -> Path:
    raw = getattr(value, "root", value)
    if not isinstance(raw, str) or not raw:
        raise CodexIsolationError("Codex returned an invalid path")
    return Path(raw)


__all__ = [
    "CodexAmbientSkill",
    "CodexAmbientState",
    "CodexIsolationError",
    "CodexOperatorThreadResponse",
    "CodexServerRequestHandler",
    "CodexTaskThreadStartResponse",
    "build_codex_client",
    "build_codex_operator_isolation_config",
    "build_codex_task_config",
    "codex_process_isolation_overrides",
    "deny_codex_task_server_request",
    "read_codex_ambient_state",
    "require_codex_inert_mcp_isolation",
    "require_codex_operator_thread_isolation",
    "require_codex_task_thread_isolation",
    "validate_codex_task_extensions",
]
