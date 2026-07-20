from __future__ import annotations

import ast
from pathlib import Path

from .models import AuditSettings, ModuleRecord


def load_modules(settings: AuditSettings) -> list[ModuleRecord]:
    modules: list[ModuleRecord] = []
    for path in iter_python_files(settings):
        source = path.read_text(encoding="utf-8")
        modules.append(
            ModuleRecord(
                path=path,
                module_name=module_name_for_path(path, settings),
                tree=ast.parse(source, filename=str(path)),
                lines=tuple(source.splitlines()),
            )
        )
    return modules


def iter_python_files(settings: AuditSettings) -> list[Path]:
    paths: set[Path] = set()
    for root in settings.scan_roots:
        if not root.exists():
            continue
        if root.is_file():
            if (
                root.suffix == ".py"
                and "__pycache__" not in root.parts
                and root not in settings.excluded_paths
            ):
                paths.add(root)
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or path in settings.excluded_paths:
                continue
            paths.add(path)
    return sorted(paths)


def module_name_for_path(path: Path, settings: AuditSettings) -> str | None:
    apps_api_root = settings.apps_api_root
    apps_api_src_root = apps_api_root / "src"
    scripts_docs_root = settings.root / "scripts" / "docs"

    if path.is_relative_to(apps_api_src_root):
        return dotted_module_name(path.relative_to(apps_api_src_root))
    if path.is_relative_to(apps_api_root):
        return dotted_module_name(path.relative_to(apps_api_root))
    if path.is_relative_to(scripts_docs_root):
        return dotted_module_name(path.relative_to(scripts_docs_root))
    return None


def dotted_module_name(relative_path: Path) -> str | None:
    parts = list(relative_path.with_suffix("").parts)
    if not parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def resolve_module_name(
    current_module: str | None,
    module: str | None,
    level: int,
    *,
    current_path: Path | None = None,
) -> str | None:
    if level == 0:
        return module
    if current_module is None:
        return None

    current_parts = current_module.split(".")
    if current_path is None:
        trim_count = level
    else:
        if current_path.name != "__init__.py":
            current_parts = current_parts[:-1]
        trim_count = level - 1
        if trim_count >= len(current_parts):
            return None
    if trim_count > len(current_parts):
        return None

    anchor_parts = current_parts[: len(current_parts) - trim_count]
    if module:
        return ".".join(anchor_parts + module.split("."))
    return ".".join(anchor_parts)


def count_non_comment_lines(lines: tuple[str, ...], start_line: int, end_line: int) -> int:
    return sum(
        1
        for line in lines[start_line - 1 : end_line]
        if line.strip() and not line.strip().startswith("#")
    )
