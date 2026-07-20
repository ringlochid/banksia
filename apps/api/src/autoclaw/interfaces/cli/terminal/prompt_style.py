from __future__ import annotations

from autoclaw.interfaces.cli.terminal.theme import accent, heading, muted


def style_prompt_message(message: str, *, is_rich: bool) -> str:
    return accent(message, is_rich=is_rich)


def style_prompt_title(title: str | None, *, is_rich: bool) -> str | None:
    if title is None:
        return None
    return heading(title, is_rich=is_rich)


def style_prompt_hint(hint: str | None, *, is_rich: bool) -> str | None:
    if hint is None:
        return None
    return muted(hint, is_rich=is_rich)


__all__ = ["style_prompt_hint", "style_prompt_message", "style_prompt_title"]
