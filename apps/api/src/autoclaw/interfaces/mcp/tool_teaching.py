from __future__ import annotations

from dataclasses import dataclass

from mcp.types import ToolAnnotations

READ_ONLY_PREFIX = "Read-only:"
MUTATING_PREFIX = "Mutating:"
LOCAL_FILE_PATH_NOTE = "Local file path on the AutoClaw host."
STATUS_CHECK_WARNING = "Do not use for status checks."
RUNTIME_STATE_WARNING = "This changes runtime state."
FRESH_REVISION_NOTE = (
    "Use only with fresh expected_active_flow_revision_id and expected_control_revision "
    "values from get_runtime_task or get_operator_snapshot."
)
INSPECT_FIRST_NOTE = "Use only after inspecting current runtime state."
DISCOVER_CANDIDATES_NOTE = "Use this to discover candidates before choosing or mutating."
INSPECT_CURRENT_REVISION_NOTE = "Use this to inspect one current revision."
AUDIT_ONLY_NOTE = "Use this for audit or provenance, not normal planning."
INSPECT_IF_UNSURE_NOTE = (
    "Inspect current definitions first if you are unsure which definition to change."
)
REAL_RUNTIME_EFFECTS_NOTE = "Creates task root and starts real runtime effects."


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
    "FRESH_REVISION_NOTE",
    "INSPECT_CURRENT_REVISION_NOTE",
    "INSPECT_FIRST_NOTE",
    "INSPECT_IF_UNSURE_NOTE",
    "LOCAL_FILE_PATH_NOTE",
    "MUTATING_PREFIX",
    "READ_ONLY_PREFIX",
    "REAL_RUNTIME_EFFECTS_NOTE",
    "RUNTIME_STATE_WARNING",
    "STATUS_CHECK_WARNING",
    "ToolTeaching",
    "mutating_tool_teaching",
    "read_only_tool_teaching",
    "tool_title",
]
