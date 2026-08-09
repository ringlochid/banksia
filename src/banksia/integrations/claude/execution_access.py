from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from claude_agent_sdk.types import (
    HookContext,
    HookEvent,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    SandboxSettings,
)

from banksia.providers import ManagedSandboxMode, NetworkAccess

_CLAUDE_WRITE_TOOL_PATH_FIELDS = {
    "Edit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}


def build_claude_workspace_hooks(
    sandbox_mode: ManagedSandboxMode,
    workspace_root: Path,
) -> dict[HookEvent, list[HookMatcher]]:
    if sandbox_mode is not ManagedSandboxMode.WORKSPACE_WRITE:
        return {}

    async def require_workspace_write_path(
        hook_input: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> HookJSONOutput:
        if hook_input["hook_event_name"] != "PreToolUse":
            return _deny_workspace_write("workspace write guard received a wrong hook event")
        pre_tool_input = hook_input
        tool_name = pre_tool_input["tool_name"]
        path_field = _CLAUDE_WRITE_TOOL_PATH_FIELDS.get(tool_name)
        raw_path = pre_tool_input["tool_input"].get(path_field) if path_field else None
        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            return _deny_workspace_write("write tool did not provide one valid target path")
        if not _is_workspace_write_path(raw_path, workspace_root=workspace_root):
            return _deny_workspace_write("write target is outside the assigned workspace")
        return {}

    return {
        "PreToolUse": [
            HookMatcher(
                matcher="Edit|Write|NotebookEdit",
                hooks=[require_workspace_write_path],
            )
        ]
    }


def build_claude_sandbox(network_access: NetworkAccess) -> SandboxSettings | None:
    if network_access is NetworkAccess.ALLOW:
        return None
    sandbox: dict[str, object] = {
        "enabled": True,
        "failIfUnavailable": True,
        "autoAllowBashIfSandboxed": True,
        "excludedCommands": [],
        "allowUnsandboxedCommands": False,
        "network": {
            "allowedDomains": ["127.0.0.1", "localhost", "::1"],
            "allowUnixSockets": [],
            "allowAllUnixSockets": False,
            "allowLocalBinding": False,
        },
    }
    return cast(SandboxSettings, sandbox)


def _is_workspace_write_path(raw_path: str, *, workspace_root: Path) -> bool:
    try:
        supplied = Path(raw_path)
        lexical_path = Path(
            os.path.abspath(supplied if supplied.is_absolute() else workspace_root / supplied)
        )
        lexical_relative = lexical_path.relative_to(workspace_root)
        cursor = workspace_root
        for index, part in enumerate(lexical_relative.parts):
            cursor /= part
            try:
                if cursor.is_symlink():
                    return False
                if (
                    index == len(lexical_relative.parts) - 1
                    and cursor.is_file()
                    and cursor.stat().st_nlink > 1
                ):
                    return False
            except OSError:
                return False
        resolved_path = lexical_path.resolve(strict=False)
        return resolved_path.is_relative_to(workspace_root)
    except (OSError, RuntimeError, ValueError):
        return False


def _deny_workspace_write(reason: str) -> HookJSONOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


__all__ = ["build_claude_sandbox", "build_claude_workspace_hooks"]
