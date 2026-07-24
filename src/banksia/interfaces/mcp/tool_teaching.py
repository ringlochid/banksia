from __future__ import annotations

from dataclasses import dataclass

from mcp.types import ToolAnnotations

READ_ONLY_PREFIX = "Read-only:"
MUTATING_PREFIX = "Mutating:"
LOCAL_FILE_PATH_NOTE = "Local file path on the Banksia host."
STATUS_CHECK_WARNING = "Do not use for status checks."
RUNTIME_STATE_WARNING = "This changes runtime state."
DISCOVER_CANDIDATES_NOTE = "Use this to discover candidates before choosing or mutating."
INSPECT_CURRENT_REVISION_NOTE = "Use this to inspect one current revision."
AUDIT_ONLY_NOTE = "Use this for audit or provenance, not normal planning."


@dataclass(frozen=True)
class ToolTeaching:
    title: str
    description: str
    annotations: ToolAnnotations


def read_only_tool_teaching(
    *,
    name: str,
    summary: str,
    details: tuple[str, ...] = (),
) -> ToolTeaching:
    return ToolTeaching(
        title=tool_title(name),
        description=_join_sentences(f"{READ_ONLY_PREFIX} {summary}", *details),
        annotations=ToolAnnotations(readOnlyHint=True),
    )


def mutating_tool_teaching(
    *,
    name: str,
    summary: str,
    details: tuple[str, ...] = (),
) -> ToolTeaching:
    return ToolTeaching(
        title=tool_title(name),
        description=_join_sentences(f"{MUTATING_PREFIX} {summary}", *details),
        annotations=ToolAnnotations(readOnlyHint=False),
    )


def tool_title(name: str) -> str:
    return name.replace("_", " ").title()


def _join_sentences(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if part.strip())


__all__ = [
    "AUDIT_ONLY_NOTE",
    "DISCOVER_CANDIDATES_NOTE",
    "INSPECT_CURRENT_REVISION_NOTE",
    "LOCAL_FILE_PATH_NOTE",
    "MUTATING_PREFIX",
    "READ_ONLY_PREFIX",
    "RUNTIME_STATE_WARNING",
    "STATUS_CHECK_WARNING",
    "ToolTeaching",
    "mutating_tool_teaching",
    "read_only_tool_teaching",
    "tool_title",
]
