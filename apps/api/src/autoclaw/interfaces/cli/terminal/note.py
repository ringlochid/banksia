from __future__ import annotations

import shutil

from autoclaw.interfaces.cli.terminal.prompt_style import style_prompt_title
from autoclaw.interfaces.cli.terminal.theme import muted


def note(message: str, title: str | None = None, *, is_rich: bool) -> None:
    print(_render_note(message, title, is_rich=is_rich))


def _render_note(message: str, title: str | None = None, *, is_rich: bool) -> str:
    lines = _wrap_note_message(message)
    content_width = max([len(line) for line in lines] + [len(title or "")])
    border = "┌" + "─" * (content_width + 2) + "┐"
    footer = "└" + "─" * (content_width + 2) + "┘"
    rendered: list[str] = [border]
    styled_title = style_prompt_title(title, is_rich=is_rich)
    if styled_title:
        pad = max(content_width - len(title or ""), 0)
        rendered.append(f"│ {styled_title}{' ' * pad} │")
        rendered.append("├" + "─" * (content_width + 2) + "┤")
    for line in lines:
        styled_line = muted(line, is_rich=is_rich)
        rendered.append(f"│ {styled_line}{' ' * (content_width - len(line))} │")
    rendered.append(footer)
    return "\n".join(rendered)


def _wrap_note_message(message: str, *, width: int | None = None) -> list[str]:
    columns = shutil.get_terminal_size((100, 20)).columns
    max_width = max(40, min(width or columns - 6, 88))
    wrapped: list[str] = []
    for raw_line in message.splitlines() or [""]:
        wrapped.extend(_wrap_line(raw_line, max_width))
    return wrapped


def _wrap_line(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


__all__ = ["note"]
