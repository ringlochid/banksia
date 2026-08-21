from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import TurnCompletedNotification
from openai_codex.models import JsonObject, Notification


class DumpableConfig:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def model_dump(self, **_: object) -> dict[str, object]:
        return self._value


class FakeCodexClient:
    def __init__(
        self,
        *,
        handler: Callable[[str, JsonObject | None], JsonObject],
        suffix: int,
        ambient_config: dict[str, object] | None = None,
        thread_overrides: dict[str, object] | None = None,
        ambient_mcp_tool_names: tuple[str, ...] = (),
        mcp_tool_names: tuple[str, ...] = ("checkpoint", "delegate"),
        account: object | None = None,
        requires_openai_auth: bool = False,
    ) -> None:
        self.handler = handler
        self.suffix = suffix
        self.ambient_config = ambient_config or {"mcp_servers": {"ambient_docs": {"enabled": True}}}
        self.thread_overrides = thread_overrides or {}
        self.ambient_mcp_tool_names = ambient_mcp_tool_names
        self.mcp_tool_names = mcp_tool_names
        self.account_result = SimpleNamespace(
            account=account,
            requires_openai_auth=requires_openai_auth,
        )
        self.calls: list[tuple[str, JsonObject | None]] = []
        self.thread_params: JsonObject | None = None
        self.turn_params: JsonObject | None = None
        self.turn_input: str | None = None
        self.was_started = False
        self.was_initialized = False
        self.was_interrupted = False
        self.steer_messages: list[str] = []
        self.was_closed = False
        self._turn_finished = threading.Event()

    def start(self) -> None:
        self.was_started = True

    def initialize(self) -> object:
        self.was_initialized = True
        return object()

    def request(
        self,
        method: str,
        params: JsonObject | None,
        *,
        response_model: object,
    ) -> object:
        del response_model
        self.calls.append((method, params))
        if method == "config/read":
            return SimpleNamespace(config=DumpableConfig(self.ambient_config))
        if method == "skills/list":
            cwd = cast(list[str], cast(dict[str, Any], params)["cwds"])[0]
            skill_specs = (
                ("ambient-skill", ".codex/skills/ambient/SKILL.md", "user"),
                ("project-review", ".agents/skills/review/SKILL.md", "repo"),
            )
            skills = [
                SimpleNamespace(
                    enabled=True,
                    name=name,
                    path=SimpleNamespace(root=str(Path(cwd) / relative_path)),
                    scope=SimpleNamespace(value=scope),
                )
                for name, relative_path, scope in skill_specs
            ]
            return SimpleNamespace(data=[SimpleNamespace(cwd=cwd, errors=[], skills=skills)])
        if method == "thread/start":
            assert params is not None
            self.thread_params = params
            cwd = cast(str, params["cwd"])
            sandbox = cast(str, params["sandbox"])
            sandbox_type = {
                "read-only": "readOnly",
                "workspace-write": "workspaceWrite",
                "danger-full-access": "dangerFullAccess",
            }[sandbox]
            config = cast(dict[str, Any], params["config"])
            network_access = sandbox == "workspace-write" and bool(
                config["sandbox_workspace_write"]["network_access"]
            )
            response: dict[str, object] = {
                "approval_policy": SimpleNamespace(root="never"),
                "cwd": SimpleNamespace(root=cwd),
                "instruction_sources": [],
                "model": params["model"],
                "runtime_workspace_roots": [SimpleNamespace(root=cwd)],
                "sandbox": SimpleNamespace(
                    root=SimpleNamespace(type=sandbox_type, network_access=network_access)
                ),
                "thread": SimpleNamespace(
                    cwd=SimpleNamespace(root=cwd),
                    ephemeral=True,
                    id=f"thread-{self.suffix}",
                ),
            }
            response.update(self.thread_overrides)
            return SimpleNamespace(**response)
        if method == "mcpServerStatus/list":
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        name="ambient_docs",
                        resource_templates=[],
                        resources=[],
                        server_info=object() if self.ambient_mcp_tool_names else None,
                        tools={name: object() for name in self.ambient_mcp_tool_names},
                    ),
                    SimpleNamespace(
                        name="oms_node",
                        resource_templates=[],
                        resources=[],
                        server_info=object(),
                        tools={name: object() for name in self.mcp_tool_names},
                    ),
                ],
                next_cursor=None,
            )
        raise AssertionError(f"unexpected request: {method}")

    def turn_start(
        self,
        thread_id: str,
        input_items: str,
        params: JsonObject | None = None,
    ) -> object:
        assert thread_id == f"thread-{self.suffix}"
        self.turn_input = input_items
        self.turn_params = params
        return SimpleNamespace(turn=SimpleNamespace(id=f"turn-{self.suffix}"))

    def next_turn_notification(self, turn_id: str) -> Notification:
        self._turn_finished.wait()
        payload = TurnCompletedNotification.model_validate(
            {
                "threadId": f"thread-{self.suffix}",
                "turn": {
                    "id": turn_id,
                    "items": [],
                    "status": "interrupted",
                },
            }
        )
        return Notification(method="turn/completed", payload=payload)

    def unregister_turn_notifications(self, turn_id: str) -> None:
        assert turn_id == f"turn-{self.suffix}"

    def turn_interrupt(self, thread_id: str, turn_id: str) -> object:
        assert (thread_id, turn_id) == (
            f"thread-{self.suffix}",
            f"turn-{self.suffix}",
        )
        self.was_interrupted = True
        self._turn_finished.set()
        return object()

    def turn_steer(self, thread_id: str, turn_id: str, message: str) -> object:
        assert (thread_id, turn_id) == (
            f"thread-{self.suffix}",
            f"turn-{self.suffix}",
        )
        self.steer_messages.append(message)
        return object()

    def account_read(self) -> object:
        return self.account_result

    def close(self) -> None:
        self.was_closed = True
        self._turn_finished.set()


class FakeCodexClientFactory:
    def __init__(self, **client_options: Any) -> None:
        self.client_options = client_options
        self.clients: list[FakeCodexClient] = []

    def __call__(
        self,
        handler: Callable[[str, JsonObject | None], JsonObject],
    ) -> CodexClient:
        client = FakeCodexClient(
            handler=handler,
            suffix=len(self.clients) + 1,
            **self.client_options,
        )
        self.clients.append(client)
        return cast(CodexClient, client)


__all__ = ["FakeCodexClient", "FakeCodexClientFactory"]
