from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import ConfigReadResponse
from openai_codex.models import JsonObject
from pydantic import BaseModel

import oh_my_subagents.integrations.codex.isolation as isolation_module


class _CanonicalWorkspaceClient:
    def __init__(self, canonical_workspace: Path) -> None:
        self.canonical_workspace = canonical_workspace

    def request(
        self,
        method: str,
        params: JsonObject | None,
        *,
        response_model: type[BaseModel],
    ) -> object:
        del params, response_model
        if method == "config/read":
            return ConfigReadResponse.model_validate({"config": {"mcp_servers": {}}, "origins": {}})
        if method == "skills/list":
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        cwd=SimpleNamespace(root=str(self.canonical_workspace)),
                        errors=[],
                        skills=[],
                    )
                ]
            )
        raise AssertionError(f"unexpected request method: {method}")


def test_codex_client_applies_process_isolation_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[CodexConfig, object]] = []
    sentinel = object()

    def build_client(
        config: CodexConfig,
        *,
        approval_handler: object,
    ) -> object:
        captured.append((config, approval_handler))
        return sentinel

    def deny_request(method: str, params: JsonObject | None) -> JsonObject:
        del method, params
        return {}

    monkeypatch.setattr(isolation_module, "CodexClient", build_client)

    client = isolation_module.build_codex_client(deny_request)

    assert client is cast(CodexClient, sentinel)
    assert len(captured) == 1
    config, handler = captured[0]
    assert handler is deny_request
    assert config.experimental_api is True
    overrides = config.config_overrides
    assert len(overrides) == len(set(overrides))
    assert {
        "apps._default.enabled=false",
        "features.artifact=false",
        "features.hooks=false",
        "features.multi_agent=false",
        "features.plugins=false",
        "features.remote_plugin=false",
        "features.shell_tool=true",
        "features.unified_exec=true",
        "project_doc_max_bytes=0",
        "skills.bundled.enabled=false",
        "skills.include_instructions=false",
        'web_search="disabled"',
    } <= set(overrides)


def test_codex_skill_inventory_accepts_an_equivalent_workspace_alias(tmp_path: Path) -> None:
    canonical_workspace = tmp_path / "canonical-workspace"
    canonical_workspace.mkdir()
    workspace_alias = tmp_path / "workspace-alias"
    workspace_alias.symlink_to(canonical_workspace, target_is_directory=True)
    client = cast(CodexClient, _CanonicalWorkspaceClient(canonical_workspace))

    ambient = isolation_module.read_codex_ambient_state(client, workspace_alias)

    assert ambient.skills == ()
    assert ambient.mcp_server_names == ()
