from __future__ import annotations

import ast
from pathlib import Path

from .models import (
    AuditSettings,
    DuplicateModuleNameFinding,
    GenericModuleNameFinding,
    ModuleRecord,
    SiblingPrefixFinding,
    StarImportCollectorFinding,
    StarImportLocation,
    StructuralFindings,
)


def collect_structural_findings(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> StructuralFindings:
    return StructuralFindings(
        sibling_prefix_findings=tuple(
            _collect_sibling_prefix_findings(
                modules,
                settings.apps_api_root / "tests",
                settings.sibling_prefix_threshold,
            )
        ),
        import_wrapper_modules=tuple(_collect_import_wrapper_modules(modules, settings)),
        star_import_collectors=tuple(_collect_star_import_collectors(modules, settings)),
        gitkeep_placeholders=tuple(_collect_gitkeep_placeholders(settings)),
        generic_module_name_findings=tuple(
            _collect_generic_module_name_findings(modules, settings)
        ),
        duplicate_module_name_findings=tuple(
            _collect_duplicate_module_name_findings(modules, settings)
        ),
    )


def _collect_sibling_prefix_findings(
    modules: list[ModuleRecord],
    tests_root: Path,
    sibling_prefix_threshold: int,
) -> list[SiblingPrefixFinding]:
    grouped_members: dict[tuple[Path, str], list[Path]] = {}
    for module in modules:
        if module.path.name == "__init__.py":
            continue
        stem = _family_stem(module.path, tests_root)
        if "_" not in stem:
            continue
        prefix = stem.split("_", maxsplit=1)[0]
        grouped_members.setdefault((module.path.parent, prefix), []).append(module.path)

    findings: list[SiblingPrefixFinding] = []
    for (directory, prefix), members in grouped_members.items():
        if len(members) < sibling_prefix_threshold:
            continue
        findings.append(
            SiblingPrefixFinding(
                directory=directory,
                prefix=prefix,
                members=tuple(sorted(members)),
            )
        )
    return sorted(findings, key=lambda finding: (finding.directory.as_posix(), finding.prefix))


def _family_stem(path: Path, tests_root: Path) -> str:
    stem = path.stem
    try:
        relative = path.relative_to(tests_root)
    except ValueError:
        return stem
    if relative.parts and stem.startswith("test_"):
        return stem[len("test_") :]
    return stem


def _collect_import_wrapper_modules(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> list[Path]:
    tests_root = settings.apps_api_root / "tests"
    return sorted(
        (
            module.path
            for module in modules
            if not module.path.is_relative_to(tests_root)
            and not _is_allowed_wrapper_module(module.path, settings)
            and _is_import_wrapper_module(module.tree)
        ),
        key=lambda path: path.as_posix(),
    )


def _is_allowed_wrapper_module(path: Path, settings: AuditSettings) -> bool:
    if path.name == "__init__.py":
        return True
    if path in settings.approved_wrapper_modules:
        return True
    return any(
        path.is_relative_to(directory) for directory in settings.approved_wrapper_directories
    )


def _is_import_wrapper_module(tree: ast.Module) -> bool:
    saw_import = False
    imported_names: set[str] = set()
    for node in tree.body:
        if _is_docstring_node(node):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            saw_import = True
            imported_names.update(_bound_import_names(node))
            continue
        if _is_export_assignment(node):
            continue
        if _is_import_alias_assignment(node, imported_names):
            continue
        return False
    return saw_import


def _is_docstring_node(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_export_assignment(node: ast.stmt) -> bool:
    if isinstance(node, ast.Assign):
        return (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__all__"
        )
    return (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "__all__"
    )


def _bound_import_names(node: ast.Import | ast.ImportFrom) -> set[str]:
    bound_names: set[str] = set()
    for alias in node.names:
        if alias.name == "*":
            continue
        if alias.asname is not None:
            bound_names.add(alias.asname)
            continue
        if isinstance(node, ast.Import):
            bound_names.add(alias.name.split(".", maxsplit=1)[0])
            continue
        bound_names.add(alias.name)
    return bound_names


def _is_import_alias_assignment(node: ast.stmt, imported_names: set[str]) -> bool:
    if isinstance(node, ast.Assign):
        if not all(isinstance(target, ast.Name) for target in node.targets):
            return False
        return _is_import_alias_value(node.value, imported_names)
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and _is_import_alias_value(
            node.value,
            imported_names,
        )
    return False


def _is_import_alias_value(node: ast.expr | None, imported_names: set[str]) -> bool:
    if node is None:
        return False
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return isinstance(current, ast.Name) and current.id in imported_names


def _collect_star_import_collectors(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> list[StarImportCollectorFinding]:
    tests_root = settings.apps_api_root / "tests"
    findings: list[StarImportCollectorFinding] = []
    for module in modules:
        if not module.path.is_relative_to(tests_root) or not module.path.name.startswith("test_"):
            continue
        star_imports = tuple(
            sorted(
                (
                    StarImportLocation(line=node.lineno, source=_format_import_from_source(node))
                    for node in ast.walk(module.tree)
                    if isinstance(node, ast.ImportFrom)
                    and any(alias.name == "*" for alias in node.names)
                ),
                key=lambda imported: (imported.line, imported.source),
            )
        )
        if not star_imports:
            continue
        findings.append(StarImportCollectorFinding(path=module.path, imports=star_imports))
    return sorted(findings, key=lambda finding: finding.path.as_posix())


def _format_import_from_source(node: ast.ImportFrom) -> str:
    module_name = node.module or ""
    return f"{'.' * node.level}{module_name}" or "<unknown>"


def _collect_gitkeep_placeholders(settings: AuditSettings) -> list[Path]:
    placeholders: set[Path] = set()
    for root in settings.scan_roots:
        if not root.exists():
            continue
        placeholders.update(root.rglob(".gitkeep"))
    return sorted(placeholders)


def _collect_generic_module_name_findings(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> list[GenericModuleNameFinding]:
    findings: list[GenericModuleNameFinding] = []
    for module in modules:
        if module.path.name == "__init__.py":
            continue
        if module.path.stem not in settings.disallowed_generic_module_names:
            continue
        package_name = module.path.parent.name
        if package_name not in settings.inexact_package_names:
            continue
        findings.append(
            GenericModuleNameFinding(
                path=module.path,
                package_name=package_name,
                module_name=module.path.stem,
            )
        )
    return sorted(findings, key=lambda finding: finding.path.as_posix())


def _collect_duplicate_module_name_findings(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> list[DuplicateModuleNameFinding]:
    module_name_to_paths: dict[str, list[Path]] = {}
    for module in modules:
        if module.module_name is None:
            continue
        module_name_to_paths.setdefault(module.module_name, []).append(module.path)

    findings: list[DuplicateModuleNameFinding] = []
    for module_name, paths in module_name_to_paths.items():
        unique_paths = tuple(sorted(set(paths)))
        if len(unique_paths) < 2:
            continue
        if all(path in settings.approved_duplicate_module_name_paths for path in unique_paths):
            continue
        findings.append(
            DuplicateModuleNameFinding(
                module_name=module_name,
                paths=unique_paths,
            )
        )
    return sorted(findings, key=lambda finding: finding.module_name)
