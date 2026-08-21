from __future__ import annotations

import httpx
import pytest

from oh_my_subagents.config import (
    ClaudeSettings,
    CodexSettings,
    RuntimeSettings,
    Settings,
    get_settings,
)
from oh_my_subagents.main import create_app
from oh_my_subagents.providers import ManagedSandboxMode, NetworkAccess, ProviderKind


@pytest.mark.parametrize(
    ("settings", "expected"),
    (
        (Settings(), None),
        (
            Settings(
                runtime=RuntimeSettings(
                    default_provider=ProviderKind.CODEX,
                    managed_provider_sandbox_mode=ManagedSandboxMode.READ_ONLY,
                    managed_provider_network_access=NetworkAccess.DENY,
                ),
                codex=CodexSettings(
                    enabled=True,
                    model="gpt-controller",
                    effort="high",
                ),
            ),
            {
                "kind": "codex",
                "model": "gpt-controller",
                "effort": "high",
                "sandbox": {"mode": "read_only", "network": "deny"},
                "extension_mode": "inherit",
            },
        ),
        (
            Settings(
                runtime=RuntimeSettings(
                    default_provider=ProviderKind.CLAUDE,
                    managed_provider_sandbox_mode=ManagedSandboxMode.WORKSPACE_WRITE,
                    managed_provider_network_access=NetworkAccess.ALLOW,
                ),
                claude=ClaudeSettings(
                    enabled=True,
                    model="claude-controller",
                    effort="max",
                ),
            ),
            {
                "kind": "claude",
                "model": "claude-controller",
                "effort": "max",
                "sandbox": {"mode": "workspace_write", "network": "allow"},
                "extension_mode": "inherit",
            },
        ),
        (
            Settings(
                runtime=RuntimeSettings(default_provider=ProviderKind.OPENCLAW),
            ),
            None,
        ),
    ),
)
async def test_authoring_options_read_back_only_the_nonsecret_default_provider(
    settings: Settings,
    expected: dict[str, object] | None,
) -> None:
    admission_settings = get_settings()
    app = create_app(should_enable_mcp_mounts=False)
    app.dependency_overrides[get_settings] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url=f"http://127.0.0.1:{admission_settings.api_port}",
    ) as client:
        response = await client.get("/api/workflows/authoring-options")

    assert response.status_code == 200, response.text
    assert response.json()["default_provider"] == expected
