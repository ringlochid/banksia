from __future__ import annotations

from importlib.resources import files


def read_operator_system_prompt() -> str:
    return (
        files("oh_my_subagents.operator.prompt")
        .joinpath("assets/system.txt")
        .read_text(encoding="utf-8")
    )


__all__ = ["read_operator_system_prompt"]
