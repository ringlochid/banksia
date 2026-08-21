from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient

from oh_my_subagents.integrations.claude.native_identity import ClaudeIsolationMode
from oh_my_subagents.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    provider_subprocess_environment_overrides,
)
from oh_my_subagents.providers import ManagedExtensionMode
from oh_my_subagents.runtime.providers.contracts import (
    MANAGED_NODE_MCP_SERVER_NAME,
    ProviderExtensionInventory,
    ProviderMcpServerInventory,
)

CLAUDE_EXTENSION_TOOLS = ("Agent", "Artifact", "Skill", "SlashCommand")
CLAUDE_ALWAYS_DISALLOWED_TOOLS = (*CLAUDE_EXTENSION_TOOLS, "AskUserQuestion")
CLAUDE_INHERITED_DISALLOWED_TOOLS = ("Agent", "Artifact", "SlashCommand", "AskUserQuestion")
CLAUDE_MCP_STARTUP_TIMEOUT_SECONDS = 5.0
_CLAUDE_MCP_POLL_INTERVAL_SECONDS = 0.05

_COMMON_SETTINGS = {
    "attribution": {"commit": "", "pr": ""},
    "autoMemoryEnabled": False,
    "disableAgentView": True,
    "disableArtifact": True,
    "disableClaudeAiConnectors": True,
    "disableWorkflows": True,
}
_ISOLATION_SETTINGS = json.dumps(
    {
        **_COMMON_SETTINGS,
        "disableBundledSkills": True,
    },
    separators=(",", ":"),
    sort_keys=True,
)
_ISOLATION_ENVIRONMENT = {
    "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
    "CLAUDE_CODE_DISABLE_AGENT_VIEW": "1",
    "CLAUDE_CODE_DISABLE_ARTIFACT": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
    "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1",
    "CLAUDE_CODE_DISABLE_WORKFLOWS": "1",
    "CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS": "1",
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
}


class ClaudeStartupIsolationError(RuntimeError):
    """The pinned CLI could not prove the requested invocation boundary."""


def claude_isolation_settings() -> str:
    return _ISOLATION_SETTINGS


def claude_task_settings(
    extension_mode: ManagedExtensionMode,
    *,
    enabled_plugin_names: Sequence[str] = (),
) -> str:
    if extension_mode is ManagedExtensionMode.ISOLATED:
        return _ISOLATION_SETTINGS
    return json.dumps(
        {
            **_COMMON_SETTINGS,
            "disableAllHooks": True,
            "disableBundledSkills": True,
            "enabledPlugins": {name: False for name in enabled_plugin_names},
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def claude_isolation_environment(
    *,
    should_persist_session: bool,
) -> dict[str, str]:
    environment = provider_subprocess_environment_overrides(
        allowed_keys=frozenset({ANTHROPIC_API_KEY})
    )
    environment.update(_ISOLATION_ENVIRONMENT)
    if not should_persist_session:
        environment["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] = "1"
    return environment


def claude_isolation_extra_args(
    mode: ClaudeIsolationMode,
    *,
    extension_mode: ManagedExtensionMode = ManagedExtensionMode.ISOLATED,
    should_persist_session: bool,
    should_use_safe_mode: bool,
) -> dict[str, str | None]:
    arguments: dict[str, str | None] = {
        "no-chrome": None,
    }
    if extension_mode is ManagedExtensionMode.ISOLATED:
        arguments["disable-slash-commands"] = None
    if mode is ClaudeIsolationMode.BARE:
        arguments = {"bare": None, **arguments}
    elif should_use_safe_mode:
        arguments = {"safe-mode": None, **arguments}
    if not should_persist_session:
        arguments["no-session-persistence"] = None
    return arguments


def read_claude_enabled_plugin_names(workspace: Path) -> tuple[str, ...]:
    """Read only plugin keys needed to negate lower-priority plugin settings."""

    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    settings_paths = (config_dir / "settings.json", workspace / ".claude" / "settings.json")
    names: set[str] = set()
    for path in settings_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ClaudeStartupIsolationError(
                "Claude plugin configuration could not be inspected"
            ) from exc
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClaudeStartupIsolationError(
                "Claude plugin configuration could not be inspected"
            ) from exc
        if not isinstance(document, dict):
            raise ClaudeStartupIsolationError("Claude plugin configuration could not be inspected")
        enabled_plugins = document.get("enabledPlugins", {})
        if not isinstance(enabled_plugins, dict) or any(
            not isinstance(name, str) or not isinstance(enabled, bool)
            for name, enabled in enabled_plugins.items()
        ):
            raise ClaudeStartupIsolationError("Claude plugin configuration could not be inspected")
        names.update(enabled_plugins)
    return tuple(sorted(names))


async def validate_claude_startup(
    client: ClaudeSDKClient,
    *,
    external_mcp_server: str | None,
    external_mcp_tools: Sequence[str] = (),
    extension_mode: ManagedExtensionMode = ManagedExtensionMode.ISOLATED,
) -> ProviderExtensionInventory:
    """Validate only effective surfaces exposed by the pinned SDK before query."""

    server_info = await client.get_server_info()
    if not isinstance(server_info, dict):
        raise ClaudeStartupIsolationError("Claude returned no server readback")
    if extension_mode is ManagedExtensionMode.ISOLATED and server_info.get("commands") != []:
        raise ClaudeStartupIsolationError("Claude exposed ambient commands")

    mcp_status = await _read_settled_mcp_status(
        client,
        expect_server=external_mcp_server is not None,
    )
    if not isinstance(mcp_status, dict):
        raise ClaudeStartupIsolationError("Claude returned no MCP readback")
    servers = mcp_status.get("mcpServers")
    if not isinstance(servers, list):
        raise ClaudeStartupIsolationError("Claude returned an invalid MCP readback")

    context = await client.get_context_usage()
    if not isinstance(context, dict):
        raise ClaudeStartupIsolationError("Claude returned no context readback")
    if context.get("memoryFiles") != [] or context.get("agents") != []:
        raise ClaudeStartupIsolationError("Claude exposed ambient context")
    context_tools = context.get("mcpTools")
    if not isinstance(context_tools, list):
        raise ClaudeStartupIsolationError("Claude returned an invalid MCP context")
    if external_mcp_server is None:
        if servers or context_tools:
            raise ClaudeStartupIsolationError("Claude exposed an external MCP surface")
        return ProviderExtensionInventory()

    expected_tools = tuple(external_mcp_tools)
    servers_by_name = _mcp_servers_by_name(servers)
    if extension_mode is ManagedExtensionMode.ISOLATED and set(servers_by_name) != {
        external_mcp_server
    }:
        raise ClaudeStartupIsolationError("Claude exposed the wrong MCP server set")
    server = servers_by_name.get(external_mcp_server)
    if not isinstance(server, dict) or server.get("status") != "connected":
        raise ClaudeStartupIsolationError("Claude did not connect the Oh My Subagents MCP server")
    if not _has_exact_names(_mcp_status_tool_names(server.get("tools")), expected_tools):
        raise ClaudeStartupIsolationError("Claude exposed the wrong MCP tool set")
    if not _has_exact_names(
        _context_mcp_tool_names(context_tools, server_name=external_mcp_server),
        expected_tools,
    ):
        raise ClaudeStartupIsolationError("Claude loaded the wrong MCP context")
    if extension_mode is ManagedExtensionMode.ISOLATED:
        if any(
            item.get("serverName") != external_mcp_server
            for item in context_tools
            if isinstance(item, dict)
        ):
            raise ClaudeStartupIsolationError("Claude loaded an external MCP context")
        return ProviderExtensionInventory()
    return ProviderExtensionInventory(
        skills=_context_skill_names(context.get("skills")),
        mcp_servers=tuple(
            ProviderMcpServerInventory(
                name=name,
                tools=tuple(sorted(_mcp_status_tool_names(item.get("tools")))),
            )
            for name, item in sorted(servers_by_name.items())
            if name != MANAGED_NODE_MCP_SERVER_NAME and item.get("status") == "connected"
        ),
    )


async def _read_settled_mcp_status(
    client: ClaudeSDKClient,
    *,
    expect_server: bool,
) -> object:
    deadline = asyncio.get_running_loop().time() + CLAUDE_MCP_STARTUP_TIMEOUT_SECONDS
    while True:
        status = await client.get_mcp_status()
        if not expect_server or not _mcp_status_is_starting(status):
            return status
        if asyncio.get_running_loop().time() >= deadline:
            return status
        await asyncio.sleep(_CLAUDE_MCP_POLL_INTERVAL_SECONDS)


def _mcp_status_is_starting(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    servers = value.get("mcpServers")
    if not isinstance(servers, list):
        return False
    return not servers or any(
        isinstance(server, dict) and server.get("status") == "pending" for server in servers
    )


def _has_exact_names(actual: Sequence[str], expected: Sequence[str]) -> bool:
    return len(actual) == len(expected) and set(actual) == set(expected)


def _mcp_status_tool_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return ()
        names.append(item["name"])
    return tuple(names)


def _mcp_servers_by_name(value: Sequence[object]) -> dict[str, dict[str, object]]:
    servers: dict[str, dict[str, object]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ClaudeStartupIsolationError("Claude returned an invalid MCP server")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or name in servers:
            raise ClaudeStartupIsolationError("Claude returned an invalid MCP server name")
        servers[name] = item
    return servers


def _context_skill_names(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and name.strip() for name in value
    ):
        raise ClaudeStartupIsolationError("Claude returned an invalid Skill inventory")
    return tuple(sorted(value))


def _context_mcp_tool_names(
    value: Sequence[object],
    *,
    server_name: str,
) -> tuple[str, ...]:
    names: list[str] = []
    prefix = f"mcp__{server_name}__"
    for item in value:
        if not isinstance(item, dict):
            return ()
        if item.get("serverName") != server_name:
            continue
        if not isinstance(item.get("name"), str):
            return ()
        names.append(item["name"].removeprefix(prefix))
    return tuple(names)


__all__ = [
    "CLAUDE_ALWAYS_DISALLOWED_TOOLS",
    "CLAUDE_EXTENSION_TOOLS",
    "CLAUDE_INHERITED_DISALLOWED_TOOLS",
    "CLAUDE_MCP_STARTUP_TIMEOUT_SECONDS",
    "ClaudeStartupIsolationError",
    "claude_isolation_environment",
    "claude_isolation_extra_args",
    "claude_isolation_settings",
    "claude_task_settings",
    "read_claude_enabled_plugin_names",
    "validate_claude_startup",
]
