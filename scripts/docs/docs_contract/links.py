from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

MARKDOWN_LINK_PATTERN = re.compile(r"!?\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)")
FENCE_PATTERN = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass(frozen=True)
class MarkdownLink:
    label: str
    target: str
    line: int


def iter_markdown_links(text: str) -> Iterator[MarkdownLink]:
    for line_number, line in iter_non_fenced_lines(text):
        for match in MARKDOWN_LINK_PATTERN.finditer(line):
            yield MarkdownLink(
                label=match.group("label").strip(),
                target=normalize_link_target(match.group("target")),
                line=line_number,
            )


def iter_non_fenced_lines(text: str) -> Iterator[tuple[int, str]]:
    active_fence_character: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        fence_match = FENCE_PATTERN.match(line)
        if fence_match:
            fence_character = fence_match.group(1)[0]
            if active_fence_character is None:
                active_fence_character = fence_character
            elif active_fence_character == fence_character:
                active_fence_character = None
            continue
        if active_fence_character is not None:
            continue
        yield line_number, line


def normalize_link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def resolve_local_link(*, root: Path, source: Path, target: str) -> Path | None:
    if not target or target.startswith("#"):
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    target_path = unquote(parsed.path)
    if not target_path:
        return None
    if target_path.startswith("/"):
        return (root / target_path.lstrip("/")).resolve()
    return (source.parent / target_path).resolve()


def is_filename_style_label(label: str, target: str) -> bool:
    normalized_label = label.replace("`", "").strip().lower()
    target_name = Path(urlparse(target).path).name.lower()
    if not target_name.endswith(".md"):
        return False
    return (
        ".md" in normalized_label
        or normalized_label in {"readme", "index"}
        or normalized_label == target_name
    )
