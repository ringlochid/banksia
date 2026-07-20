from __future__ import annotations

import ast
from pathlib import Path

from .models import (
    CrossModulePrivateAccessFinding,
    HelperDefinition,
    ModuleRecord,
    ReferenceLocation,
)
from .module_loader import count_non_comment_lines, resolve_module_name


def collect_private_helpers(
    modules: list[ModuleRecord],
) -> tuple[dict[tuple[Path, str], HelperDefinition], dict[Path, dict[str, HelperDefinition]]]:
    helpers: dict[tuple[Path, str], HelperDefinition] = {}
    helpers_by_path: dict[Path, dict[str, HelperDefinition]] = {}
    for module in modules:
        module_helpers: dict[str, HelperDefinition] = {}
        for node in module.tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("_") or node.name.startswith("__"):
                continue
            end_line = node.end_lineno or node.lineno
            definition = HelperDefinition(
                path=module.path,
                name=node.name,
                line=node.lineno,
                end_line=end_line,
                non_comment_lines=count_non_comment_lines(module.lines, node.lineno, end_line),
            )
            helpers[(module.path, node.name)] = definition
            module_helpers[node.name] = definition
        helpers_by_path[module.path] = module_helpers
    return helpers, helpers_by_path


def collect_same_module_references(
    helpers: dict[tuple[Path, str], HelperDefinition],
    helpers_by_path: dict[Path, dict[str, HelperDefinition]],
    modules: list[ModuleRecord],
) -> dict[tuple[Path, str], list[ReferenceLocation]]:
    references: dict[tuple[Path, str], list[ReferenceLocation]] = {key: [] for key in helpers}
    for module in modules:
        module_helpers = helpers_by_path[module.path]
        if not module_helpers:
            continue
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
                continue
            helper = module_helpers.get(node.id)
            if helper is None:
                continue
            references[(module.path, helper.name)].append(
                ReferenceLocation(path=module.path, line=node.lineno, kind="same-module")
            )
    return references


def collect_cross_module_references(
    helpers_by_path: dict[Path, dict[str, HelperDefinition]],
    module_name_to_path: dict[str, Path],
    modules: list[ModuleRecord],
    references: dict[tuple[Path, str], list[ReferenceLocation]],
) -> list[tuple[HelperDefinition, ReferenceLocation]]:
    return sorted(
        _collect_cross_module_reference_items(
            helpers_by_path,
            module_name_to_path,
            modules,
            references,
        ),
        key=lambda finding: (
            finding[0].path.as_posix(),
            finding[0].name,
            finding[1].path.as_posix(),
            finding[1].line,
        ),
    )


def collect_cross_module_private_access_findings(
    helpers_by_path: dict[Path, dict[str, HelperDefinition]],
    module_name_to_path: dict[str, Path],
    modules: list[ModuleRecord],
) -> tuple[CrossModulePrivateAccessFinding, ...]:
    helper_reference_map: dict[tuple[Path, str], list[ReferenceLocation]] = {}
    for module_path, helper_map in helpers_by_path.items():
        for helper_name in helper_map:
            helper_reference_map[(module_path, helper_name)] = []

    raw_findings = _collect_cross_module_reference_items(
        helpers_by_path,
        module_name_to_path,
        modules,
        helper_reference_map,
    )
    return tuple(
        CrossModulePrivateAccessFinding(
            helper=helper.name,
            helper_path=helper.path,
            helper_line=helper.line,
            consumer_path=location.path,
            consumer_line=location.line,
            kind=location.kind,
        )
        for helper, location in raw_findings
    )


def _collect_cross_module_reference_items(
    helpers_by_path: dict[Path, dict[str, HelperDefinition]],
    module_name_to_path: dict[str, Path],
    modules: list[ModuleRecord],
    references: dict[tuple[Path, str], list[ReferenceLocation]],
) -> list[tuple[HelperDefinition, ReferenceLocation]]:
    findings: list[tuple[HelperDefinition, ReferenceLocation]] = []
    for module in modules:
        module_aliases: dict[str, Path] = {}
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Import):
                _record_import_aliases(node, module.path, module_name_to_path, module_aliases)
                continue
            if isinstance(node, ast.ImportFrom):
                _record_import_from_aliases(
                    node,
                    module,
                    helpers_by_path,
                    module_name_to_path,
                    module_aliases,
                    references,
                    findings,
                )
                continue
            if isinstance(node, ast.Attribute):
                _record_module_attribute_reference(
                    node,
                    module.path,
                    helpers_by_path,
                    module_aliases,
                    references,
                    findings,
                )
    return findings


def zero_reference_helpers(
    helpers: dict[tuple[Path, str], HelperDefinition],
    references: dict[tuple[Path, str], list[ReferenceLocation]],
) -> tuple[HelperDefinition, ...]:
    return tuple(
        sorted(
            (helper for helper_key, helper in helpers.items() if not references[helper_key]),
            key=lambda helper: (helper.path.as_posix(), helper.line, helper.name),
        )
    )


def _record_import_aliases(
    node: ast.Import,
    module_path: Path,
    module_name_to_path: dict[str, Path],
    module_aliases: dict[str, Path],
) -> None:
    for alias in node.names:
        target_path = module_name_to_path.get(alias.name)
        if target_path is None or target_path == module_path:
            continue
        alias_name = alias.asname or alias.name.rsplit(".", maxsplit=1)[-1]
        module_aliases[alias_name] = target_path


def _record_import_from_aliases(
    node: ast.ImportFrom,
    module: ModuleRecord,
    helpers_by_path: dict[Path, dict[str, HelperDefinition]],
    module_name_to_path: dict[str, Path],
    module_aliases: dict[str, Path],
    references: dict[tuple[Path, str], list[ReferenceLocation]],
    findings: list[tuple[HelperDefinition, ReferenceLocation]],
) -> None:
    resolved_module = resolve_module_name(
        module.module_name,
        node.module,
        node.level,
        current_path=module.path,
    )
    target_module_path = module_name_to_path.get(resolved_module) if resolved_module else None
    for alias in node.names:
        if alias.name == "*":
            continue
        if alias.name.startswith("_") and not alias.name.startswith("__"):
            _record_direct_private_import(
                alias.name,
                module.path,
                node.lineno,
                target_module_path,
                helpers_by_path,
                references,
                findings,
            )
        if resolved_module is None:
            continue
        submodule_path = module_name_to_path.get(f"{resolved_module}.{alias.name}")
        if submodule_path is None or submodule_path == module.path:
            continue
        module_aliases[alias.asname or alias.name] = submodule_path


def _record_direct_private_import(
    helper_name: str,
    module_path: Path,
    line: int,
    target_module_path: Path | None,
    helpers_by_path: dict[Path, dict[str, HelperDefinition]],
    references: dict[tuple[Path, str], list[ReferenceLocation]],
    findings: list[tuple[HelperDefinition, ReferenceLocation]],
) -> None:
    if target_module_path is None or target_module_path == module_path:
        return
    helper = helpers_by_path.get(target_module_path, {}).get(helper_name)
    if helper is None:
        return
    location = ReferenceLocation(path=module_path, line=line, kind="direct-import")
    references[(helper.path, helper.name)].append(location)
    findings.append((helper, location))


def _record_module_attribute_reference(
    node: ast.Attribute,
    module_path: Path,
    helpers_by_path: dict[Path, dict[str, HelperDefinition]],
    module_aliases: dict[str, Path],
    references: dict[tuple[Path, str], list[ReferenceLocation]],
    findings: list[tuple[HelperDefinition, ReferenceLocation]],
) -> None:
    if not node.attr.startswith("_") or node.attr.startswith("__"):
        return
    if not isinstance(node.value, ast.Name):
        return
    target_module_path = module_aliases.get(node.value.id)
    if target_module_path is None or target_module_path == module_path:
        return
    helper = helpers_by_path.get(target_module_path, {}).get(node.attr)
    if helper is None:
        return
    location = ReferenceLocation(path=module_path, line=node.lineno, kind="module-attribute")
    references[(helper.path, helper.name)].append(location)
    findings.append((helper, location))
