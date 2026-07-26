from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from claude_agent_sdk import ClaudeSDKClient

from banksia.integrations.claude.native_identity import ClaudeIsolationMode
from banksia.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    provider_subprocess_environment_overrides,
)

CLAUDE_EXTENSION_TOOLS = ("Agent", "Artifact", "Skill", "SlashCommand")
CLAUDE_ALWAYS_DISALLOWED_TOOLS = (*CLAUDE_EXTENSION_TOOLS, "AskUserQuestion")
CLAUDE_MCP_STARTUP_TIMEOUT_SECONDS = 5.0
_CLAUDE_MCP_POLL_INTERVAL_SECONDS = 0.05

_ISOLATION_SETTINGS = json.dumps(
    {
        "attribution": {"commit": "", "pr": ""},
        "autoMemoryEnabled": False,
        "disableAgentView": True,
        "disableArtifact": True,
        "disableBundledSkills": True,
        "disableClaudeAiConnectors": True,
        "disableWorkflows": True,
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
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
}


class ClaudeStartupIsolationError(RuntimeError):
    """The pinned CLI could not prove the requested invocation boundary."""


def claude_isolation_settings() -> str:
    return _ISOLATION_SETTINGS


def claude_isolation_environment(*, should_persist_session: bool) -> dict[str, str]:
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
    should_persist_session: bool,
    should_use_safe_mode: bool,
) -> dict[str, str | None]:
    arguments: dict[str, str | None] = {
        "disable-slash-commands": None,
        "no-chrome": None,
    }
    if mode is ClaudeIsolationMode.BARE:
        arguments = {"bare": None, **arguments}
    elif should_use_safe_mode:
        arguments = {"safe-mode": None, **arguments}
    if not should_persist_session:
        arguments["no-session-persistence"] = None
    return arguments


async def validate_claude_startup(
    client: ClaudeSDKClient,
    *,
    external_mcp_server: str | None,
    external_mcp_tools: Sequence[str] = (),
) -> None:
    """Validate only effective surfaces exposed by the pinned SDK before query."""

    server_info = await client.get_server_info()
    if not isinstance(server_info, dict) or server_info.get("commands") != []:
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
        return

    expected_tools = tuple(external_mcp_tools)
    if len(servers) != 1:
        raise ClaudeStartupIsolationError("Claude exposed the wrong MCP server set")
    server = servers[0]
    if (
        not isinstance(server, dict)
        or server.get("name") != external_mcp_server
        or server.get("status") != "connected"
    ):
        raise ClaudeStartupIsolationError("Claude did not connect the Banksia MCP server")
    if not _has_exact_names(_mcp_status_tool_names(server.get("tools")), expected_tools):
        raise ClaudeStartupIsolationError("Claude exposed the wrong MCP tool set")
    if not _has_exact_names(
        _context_mcp_tool_names(context_tools, server_name=external_mcp_server),
        expected_tools,
    ):
        raise ClaudeStartupIsolationError("Claude loaded the wrong MCP context")


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


def _context_mcp_tool_names(
    value: Sequence[object],
    *,
    server_name: str,
) -> tuple[str, ...]:
    names: list[str] = []
    prefix = f"mcp__{server_name}__"
    for item in value:
        if (
            not isinstance(item, dict)
            or item.get("serverName") != server_name
            or not isinstance(item.get("name"), str)
        ):
            return ()
        names.append(item["name"].removeprefix(prefix))
    return tuple(names)


__all__ = [
    "CLAUDE_ALWAYS_DISALLOWED_TOOLS",
    "CLAUDE_EXTENSION_TOOLS",
    "CLAUDE_MCP_STARTUP_TIMEOUT_SECONDS",
    "ClaudeStartupIsolationError",
    "claude_isolation_environment",
    "claude_isolation_extra_args",
    "claude_isolation_settings",
    "validate_claude_startup",
]
