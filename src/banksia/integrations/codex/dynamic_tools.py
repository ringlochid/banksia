from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Sequence
from concurrent.futures import Future

from openai_codex.models import JsonObject

from banksia.operator.provider import OperatorProviderUnavailableError
from banksia.operator.tools import OperatorTool

_DYNAMIC_TOOL_METHOD = "item/tool/call"
_TOOL_FAILURE_RESULT = json.dumps(
    {
        "error": "operator_operation_outcome_uncertain",
        "message": (
            "The Banksia operation did not return an accepted result. "
            "Do not repeat it automatically; refetch current product truth."
        ),
    },
    separators=(",", ":"),
)


class CodexDynamicToolBridge:
    """Bridge sync SDK callbacks while retaining the real async task for cleanup."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        tools: Sequence[OperatorTool],
    ) -> None:
        self._loop = loop
        self._tools = {tool.name.value: tool for tool in tools}
        self._pending_tasks: set[asyncio.Task[JsonObject]] = set()
        self._lock = threading.Lock()
        self._is_active = True

    def __call__(self, method: str, params: JsonObject | None) -> JsonObject:
        if method != _DYNAMIC_TOOL_METHOD:
            return _deny_server_request(method)
        result: Future[JsonObject] = Future()
        with self._lock:
            if not self._is_active:
                return _tool_failure_response()
            try:
                self._loop.call_soon_threadsafe(self._start_tool_call, params, result)
            except RuntimeError:
                return _tool_failure_response()
        try:
            return result.result()
        except BaseException:
            return _tool_failure_response()

    def _start_tool_call(
        self,
        params: JsonObject | None,
        result: Future[JsonObject],
    ) -> None:
        with self._lock:
            if not self._is_active:
                result.set_result(_tool_failure_response())
                return
            task = self._loop.create_task(self._call_tool(params))
            self._pending_tasks.add(task)
        task.add_done_callback(lambda completed: self._finish_tool_call(completed, result))

    def _finish_tool_call(
        self,
        task: asyncio.Task[JsonObject],
        result: Future[JsonObject],
    ) -> None:
        with self._lock:
            self._pending_tasks.discard(task)
        try:
            response = task.result()
        except BaseException:
            response = _tool_failure_response()
        result.set_result(response)

    async def _call_tool(self, params: JsonObject | None) -> JsonObject:
        if params is None or params.get("namespace") is not None:
            return _tool_failure_response()
        tool_name = params.get("tool")
        if not isinstance(tool_name, str):
            return _tool_failure_response()
        tool = self._tools.get(tool_name)
        if tool is None:
            return _tool_failure_response()
        try:
            result = await tool.call(params.get("arguments"))
            rendered = json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except Exception:
            return _tool_failure_response()
        return {
            "contentItems": [{"type": "inputText", "text": rendered}],
            "success": True,
        }

    async def deactivate(self) -> None:
        with self._lock:
            self._is_active = False
            pending = tuple(self._pending_tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def _deny_server_request(method: str) -> JsonObject:
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
    raise OperatorProviderUnavailableError("Codex requested an unsupported Operator capability")


def _tool_failure_response() -> JsonObject:
    return {
        "contentItems": [{"type": "inputText", "text": _TOOL_FAILURE_RESULT}],
        "success": False,
    }


__all__ = ["CodexDynamicToolBridge"]
