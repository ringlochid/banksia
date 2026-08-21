"""Shared presentation rules for controller-owned Task prompts."""

from __future__ import annotations

from oh_my_subagents.runtime.errors import illegal_state_error

TASK_TITLE_MAX_CHARACTERS = 80
TASK_SUMMARY_MAX_CHARACTERS = 240


def task_prompt_excerpt(prompt: str, *, max_characters: int) -> str:
    """Return one normalized, nonblank, contract-bounded Task prompt excerpt."""

    compact = " ".join(prompt.split())
    if not compact:
        raise illegal_state_error("root Assignment prompt is blank")
    return compact[:max_characters]


__all__ = [
    "TASK_SUMMARY_MAX_CHARACTERS",
    "TASK_TITLE_MAX_CHARACTERS",
    "task_prompt_excerpt",
]
