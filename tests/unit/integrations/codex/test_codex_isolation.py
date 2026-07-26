from __future__ import annotations

from typing import cast

import pytest
from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.models import JsonObject

import banksia.integrations.codex.isolation as isolation_module


def test_codex_task_client_applies_process_isolation_before_start(
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
