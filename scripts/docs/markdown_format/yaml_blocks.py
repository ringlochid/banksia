from __future__ import annotations

import re
from collections.abc import Sequence

import yaml

YAML_PROSE_SCALAR_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_-]*):\s*[|>]([+-]?)(\s*(?:#.*)?)$")
YAML_PROSE_SCALAR_KEYS = frozenset({"instruction"})
YAML_UNWRAPPED_SCALAR_KEYS = frozenset({"description"})
YAML_KEY_VALUE_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_-]*):\s+(.+)$")


def format_yaml_lines(lines: Sequence[str]) -> list[str]:
    formatted: list[str] = []
    index = 0
    while index < len(lines):
        scalar = _consume_yaml_prose_block_scalar(lines, index)
        if scalar is not None:
            block, index = scalar
            formatted.extend(block)
            continue
        scalar = _consume_yaml_instruction_scalar(lines, index)
        if scalar is not None:
            block, index = scalar
            formatted.extend(block)
            continue
        unwrapped_scalar = _consume_yaml_unwrapped_scalar(lines, index)
        if unwrapped_scalar is not None:
            line, index = unwrapped_scalar
            formatted.append(line)
            continue
        formatted.append(_format_yaml_line(lines[index]))
        index += 1
    return formatted


def format_yaml_text(text: str) -> str:
    normalized = _normalize_text(text)
    had_trailing_newline = normalized.endswith("\n")
    lines = normalized.split("\n")
    if had_trailing_newline and lines and lines[-1] == "":
        lines = lines[:-1]

    formatted = "\n".join(format_yaml_lines(lines))
    if had_trailing_newline:
        formatted += "\n"
    return formatted


def _consume_yaml_prose_block_scalar(
    lines: Sequence[str],
    index: int,
) -> tuple[list[str], int] | None:
    line = lines[index]
    match = YAML_PROSE_SCALAR_RE.match(line)
    if not match:
        return None

    indent, key, chomp, suffix = match.groups()
    if key not in YAML_PROSE_SCALAR_KEYS:
        return None

    indent_len = len(indent)
    cursor = index + 1
    body: list[str] = []
    while cursor < len(lines):
        next_line = lines[cursor]
        if next_line.strip() and _leading_spaces(next_line) <= indent_len:
            break
        body.append(next_line.strip())
        cursor += 1

    if not body:
        return [_format_yaml_line(line)], cursor

    folded_chomp = "+" if chomp == "+" else "-"
    header = f"{indent}{key}: >{folded_chomp}{suffix}"
    value = " ".join(" ".join(body).split())
    if not value:
        return [header], cursor
    return [header, *_yaml_scalar_body_lines(indent, value)], cursor


def _consume_yaml_unwrapped_scalar(
    lines: Sequence[str],
    index: int,
) -> tuple[str, int] | None:
    line = lines[index]
    match = YAML_KEY_VALUE_RE.match(line)
    if not match:
        return None

    indent, key, value = match.groups()
    if key not in YAML_UNWRAPPED_SCALAR_KEYS:
        return None

    stripped_value = value.lstrip()
    if stripped_value.startswith(("|", ">", '"', "'")):
        return None

    indent_len = len(indent)
    parts = [value.strip()]
    cursor = index + 1
    while cursor < len(lines):
        next_line = lines[cursor]
        next_stripped = next_line.strip()
        if not next_stripped:
            break
        next_indent = _leading_spaces(next_line)
        if next_indent <= indent_len:
            break
        if next_stripped.startswith(("- ", "#")):
            break
        if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:\s*", next_stripped):
            break
        parts.append(next_stripped)
        cursor += 1

    if cursor == index + 1:
        return None

    return f"{indent}{key}: {' '.join(parts)}", cursor


def _consume_yaml_instruction_scalar(
    lines: Sequence[str],
    index: int,
) -> tuple[list[str], int] | None:
    line = lines[index]
    match = re.match(r"^(\s*)instruction:\s+(.+)$", line)
    if not match:
        return None

    value_start = match.group(2).lstrip()
    if value_start.startswith(("|", ">")):
        return None

    indent = match.group(1)
    indent_len = len(indent)
    scalar_lines = [line]
    cursor = index + 1
    while cursor < len(lines):
        next_line = lines[cursor]
        if next_line.strip() and _leading_spaces(next_line) <= indent_len:
            break
        scalar_lines.append(next_line)
        cursor += 1

    value = _parse_instruction_scalar(indent_len, scalar_lines)
    if value is None:
        return None

    normalized = " ".join(value.split())
    if not normalized:
        return None

    return [
        f"{indent}instruction: >-",
        *_yaml_scalar_body_lines(indent, normalized),
    ], cursor


def _yaml_scalar_body_lines(indent: str, value: str) -> list[str]:
    body_indent = f"{indent}  "
    if not value:
        return [body_indent.rstrip()]
    return [f"{body_indent}{value}"]


def _parse_instruction_scalar(indent_len: int, scalar_lines: Sequence[str]) -> str | None:
    dedented = []
    for line in scalar_lines:
        if line.startswith(" " * indent_len):
            dedented.append(line[indent_len:])
        else:
            dedented.append(line)
    try:
        payload = yaml.safe_load("\n".join(dedented))
    except yaml.YAMLError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("instruction")
    if not isinstance(value, str):
        return None
    return value


def _format_yaml_line(line: str) -> str:
    match = YAML_PROSE_SCALAR_RE.match(line)
    if not match:
        return line

    indent, key, chomp, suffix = match.groups()
    if key not in YAML_PROSE_SCALAR_KEYS:
        return line
    folded_chomp = "+" if chomp == "+" else "-"
    return f"{indent}{key}: >{folded_chomp}{suffix}"


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
