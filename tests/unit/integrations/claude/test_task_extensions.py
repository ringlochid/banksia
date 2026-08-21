from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from oh_my_subagents.integrations.claude import ClaudeAdapter
from oh_my_subagents.providers import (
    ManagedExtensionMode,
    ManagedSandboxMode,
    NetworkAccess,
    ProviderNativeAccess,
)
from oh_my_subagents.runtime.providers.contracts import ProviderStopOutcome
from tests.unit.integrations.claude.task_adapter_test_support import (
    FakeClaudeClient,
    authentication,
    clear_policy,
    task_request,
)


class InheritedClaudeClient(FakeClaudeClient):
    async def get_context_usage(self) -> dict[str, object]:
        context = await super().get_context_usage()
        context["skills"] = {
            "project-review": {"tokens": 8},
            "research": {"tokens": 12},
        }
        cast(list[dict[str, object]], context["mcpTools"]).append(
            {"name": "mcp__user_docs__search", "serverName": "user_docs"}
        )
        return context

    async def get_mcp_status(self) -> dict[str, object]:
        status = await super().get_mcp_status()
        if self.mcp_status_reads > 1:
            cast(list[dict[str, object]], status["mcpServers"]).append(
                {
                    "name": "user_docs",
                    "status": "connected",
                    "tools": [{"name": "search"}],
                }
            )
        return status


@pytest.mark.asyncio
async def test_claude_inherits_user_and_project_skills_and_mcp_without_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[FakeClaudeClient] = []
    config_dir = tmp_path / "claude-home"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"user-plugin@example": True}}),
        encoding="utf-8",
    )
    project_settings = tmp_path / ".claude"
    project_settings.mkdir()
    (project_settings / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"project-plugin@example": True}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    def build_client(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = InheritedClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=authentication,
        endpoint_policy_reader=clear_policy,
    )
    request = task_request(
        working_directory=tmp_path,
        extension_mode=ManagedExtensionMode.INHERIT,
    ).model_copy(
        update={
            "sandbox_mode": ManagedSandboxMode.FULL_ACCESS,
            "provider_native_access": ProviderNativeAccess.FULL,
            "network_access": NetworkAccess.ALLOW,
        }
    )

    async with adapter.lifespan():
        accepted = await adapter.start(request)
        options = clients[0].options
        assert accepted.extension_inventory is not None
        assert accepted.extension_inventory.model_dump(mode="json") == {
            "skills": ["project-review", "research"],
            "mcp_servers": [{"name": "user_docs", "tools": ["search"]}],
        }
        assert options.setting_sources == ["user", "project"]
        assert options.skills == "all"
        assert options.plugins == []
        assert options.strict_mcp_config is False
        assert "Skill" not in options.disallowed_tools
        assert "Agent" in options.disallowed_tools
        assert "mcp__*" in options.allowed_tools
        settings = json.loads(cast(str, options.settings))
        assert settings["disableAllHooks"] is True
        assert settings["disableBundledSkills"] is True
        assert settings["enabledPlugins"] == {
            "project-plugin@example": False,
            "user-plugin@example": False,
        }
        assert options.env["CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS"] == "1"
        assert "bare" not in options.extra_args
        assert "disable-slash-commands" not in options.extra_args
        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED
