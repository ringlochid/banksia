from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path

from .formatting import format_markdown_text, format_yaml_text, normalize_text

ROOT = Path(__file__).resolve().parents[3]
FORMAT_SUFFIXES = frozenset({".md", ".yaml", ".yml"})
EXCLUDED_PROMPT_GENERATED_DIRECTORIES = (
    Path("docs-internal/design/v1/prompt-layer/generated"),
    Path("docs-internal/design/v1/prompt-layer/prompt-pack"),
)
MAINTAINED_MARKDOWN_DIRECTORIES = (
    Path("docs"),
    Path("docs-internal/design"),
    Path("docs-internal/current"),
    Path("docs-internal/adr"),
    Path(".agents/standards"),
)
MAINTAINED_MARKDOWN_FILES = (
    Path("README.md"),
    Path("AGENTS.md"),
    Path("STYLE.md"),
    Path("docs-internal/README.md"),
)


@dataclass(frozen=True)
class FormatterViolation:
    path: Path
    line: int
    reason: str = "hard-wrapped prose or list item"


def iter_maintained_markdown_files(root: Path = ROOT) -> list[Path]:
    paths: list[Path] = []
    for relative_directory in MAINTAINED_MARKDOWN_DIRECTORIES:
        directory = root / relative_directory
        if not directory.exists():
            continue
        paths.extend(
            path
            for path in sorted(directory.rglob("*.md"))
            if not is_excluded_prompt_generated_path(path, root=root)
        )
    paths.extend(
        path
        for relative_file in MAINTAINED_MARKDOWN_FILES
        if (path := root / relative_file).exists()
    )
    return deduplicate_paths(paths)


def is_excluded_prompt_generated_path(path: Path, *, root: Path = ROOT) -> bool:
    return any(
        path.is_relative_to(root / relative_directory)
        for relative_directory in EXCLUDED_PROMPT_GENERATED_DIRECTORIES
    )


def deduplicate_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(path)
    return result


def first_difference_line(original: str, formatted: str) -> int:
    original_lines = normalize_text(original).splitlines()
    formatted_lines = normalize_text(formatted).splitlines()
    for index, (left, right) in enumerate(
        zip_longest(original_lines, formatted_lines, fillvalue=None),
        start=1,
    ):
        if left != right:
            return index
    return 1


def collect_violations(paths: Iterable[Path]) -> list[FormatterViolation]:
    violations: list[FormatterViolation] = []
    for path in paths:
        original = path.read_text(encoding="utf-8")
        formatted = format_path_text(path, original)
        if original != formatted:
            violations.append(
                FormatterViolation(
                    path=path,
                    line=first_difference_line(original, formatted),
                )
            )
    return violations


def write_formatted_files(paths: Iterable[Path]) -> list[Path]:
    changed: list[Path] = []
    for path in paths:
        original = path.read_text(encoding="utf-8")
        formatted = format_path_text(path, original)
        if original == formatted:
            continue
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(formatted)
        changed.append(path)
    return changed


def resolve_paths(cli_paths: Sequence[str] | None) -> list[Path]:
    if not cli_paths:
        return iter_maintained_markdown_files()

    resolved: list[Path] = []
    for raw in cli_paths:
        path = (ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw)
        if path in {ROOT / "docs", ROOT / "docs-internal"}:
            resolved.extend(iter_maintained_markdown_files())
            continue
        if path.is_dir():
            resolved.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.suffix in FORMAT_SUFFIXES and not is_excluded_prompt_generated_path(child)
            )
            continue
        if path.suffix in FORMAT_SUFFIXES:
            resolved.append(path)
    return deduplicate_paths(resolved)


def format_path_text(path: Path, text: str) -> str:
    if path.suffix in {".yaml", ".yml"}:
        return format_yaml_text(text)
    return format_markdown_text(text)
