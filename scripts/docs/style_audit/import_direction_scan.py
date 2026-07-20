from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from .models import AuditSettings, ImportDirectionFinding, ModuleRecord
from .module_loader import resolve_module_name


def collect_import_direction_findings(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> tuple[ImportDirectionFinding, ...]:
    module_name_to_paths = _module_name_to_paths(modules)
    findings: list[ImportDirectionFinding] = []
    for module in modules:
        owner_family = _owner_family(module, settings)
        if owner_family is None:
            continue
        for node, imported_modules in _iter_imported_modules(module):
            if _has_legacy_app_shell_violation(module, imported_modules, settings):
                findings.append(
                    ImportDirectionFinding(
                        path=module.path,
                        line=node.lineno,
                        statement=ast.unparse(node),
                        owner_family=owner_family,
                        violated_rule="legacy-app-shell-imports-legacy-app-owner",
                    )
                )
                continue
            if module.path in settings.approved_import_direction_exception_modules:
                continue
            if _has_direction_violation(
                module,
                owner_family,
                imported_modules,
                module_name_to_paths,
                settings,
            ):
                findings.append(
                    ImportDirectionFinding(
                        path=module.path,
                        line=node.lineno,
                        statement=ast.unparse(node),
                        owner_family=owner_family,
                        violated_rule=_violated_rule(
                            module,
                            owner_family,
                            imported_modules,
                            module_name_to_paths,
                            settings,
                        ),
                    )
                )
    return tuple(sorted(findings, key=lambda finding: (finding.path.as_posix(), finding.line)))


def _iter_imported_modules(
    module: ModuleRecord,
) -> Iterable[tuple[ast.Import | ast.ImportFrom, tuple[str, ...]]]:
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            imported_modules = tuple(alias.name for alias in node.names)
            yield node, imported_modules
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        imported_modules = _import_from_modules(module, node)
        if imported_modules:
            yield node, imported_modules


def _import_from_modules(module: ModuleRecord, node: ast.ImportFrom) -> tuple[str, ...]:
    resolved_module = resolve_module_name(
        module.module_name,
        node.module,
        node.level,
        current_path=module.path,
    )
    if resolved_module is None:
        return ()
    imported_modules = [resolved_module]
    imported_modules.extend(
        f"{resolved_module}.{alias.name}" for alias in node.names if alias.name != "*"
    )
    return tuple(imported_modules)


def _owner_family(module: ModuleRecord, settings: AuditSettings) -> str | None:
    apps_api_root = settings.apps_api_root
    if module.path.is_relative_to(apps_api_root / "app"):
        return "app"
    if module.path.is_relative_to(apps_api_root / "autoclaw"):
        return "autoclaw"
    if module.path.is_relative_to(apps_api_root / "src" / "autoclaw"):
        return "autoclaw"
    return None


def _has_direction_violation(
    module: ModuleRecord,
    owner_family: str,
    imported_modules: tuple[str, ...],
    module_name_to_paths: dict[str, tuple[Path, ...]],
    settings: AuditSettings,
) -> bool:
    if owner_family == "autoclaw":
        if any(name == "app" or name.startswith("app.") for name in imported_modules):
            return True
        consumer_tree_kind = _autoclaw_tree_kind(module.path, settings)
        if consumer_tree_kind is None:
            return False
        return any(
            _imported_autoclaw_cross_tree_violation(
                name,
                consumer_tree_kind,
                module_name_to_paths,
                settings,
            )
            for name in imported_modules
            if name == "autoclaw" or name.startswith("autoclaw.")
        )
    return any(name == "autoclaw" or name.startswith("autoclaw.") for name in imported_modules)


def _has_legacy_app_shell_violation(
    module: ModuleRecord,
    imported_modules: tuple[str, ...],
    settings: AuditSettings,
) -> bool:
    if module.path not in settings.app_shell_direct_owner_modules:
        return False
    return any(name == "app" or name.startswith("app.") for name in imported_modules)


def _violated_rule(
    module: ModuleRecord,
    owner_family: str,
    imported_modules: tuple[str, ...],
    module_name_to_paths: dict[str, tuple[Path, ...]],
    settings: AuditSettings,
) -> str:
    if owner_family == "autoclaw":
        if any(name == "app" or name.startswith("app.") for name in imported_modules):
            return "autoclaw-consumer-imports-app-owner"
        consumer_tree_kind = _autoclaw_tree_kind(module.path, settings)
        if consumer_tree_kind == "legacy":
            return "legacy-autoclaw-consumer-imports-src-owner"
        return "src-autoclaw-consumer-imports-legacy-owner"
    return "app-consumer-imports-autoclaw-owner"


def _module_name_to_paths(modules: list[ModuleRecord]) -> dict[str, tuple[Path, ...]]:
    module_name_to_paths: dict[str, list[Path]] = {}
    for module in modules:
        if module.module_name is None:
            continue
        module_name_to_paths.setdefault(module.module_name, []).append(module.path)
    return {
        module_name: tuple(sorted(paths)) for module_name, paths in module_name_to_paths.items()
    }


def _autoclaw_tree_kind(path: Path, settings: AuditSettings) -> str | None:
    if path.is_relative_to(settings.apps_api_root / "autoclaw"):
        return "legacy"
    if path.is_relative_to(settings.apps_api_root / "src" / "autoclaw"):
        return "src"
    return None


def _imported_autoclaw_cross_tree_violation(
    module_name: str,
    consumer_tree_kind: str,
    module_name_to_paths: dict[str, tuple[Path, ...]],
    settings: AuditSettings,
) -> bool:
    for name in _module_name_candidates(module_name):
        paths = _known_module_paths(name, module_name_to_paths, settings)
        if not paths:
            continue
        root_kinds = {
            _autoclaw_tree_kind(path, settings)
            for path in paths
            if _autoclaw_tree_kind(path, settings)
        }
        if not root_kinds:
            continue
        if consumer_tree_kind in root_kinds:
            return False
        return True
    return False


def _module_name_candidates(module_name: str) -> tuple[str, ...]:
    parts = module_name.split(".")
    return tuple(".".join(parts[:index]) for index in range(len(parts), 0, -1))


def _known_module_paths(
    module_name: str,
    module_name_to_paths: dict[str, tuple[Path, ...]],
    settings: AuditSettings,
) -> tuple[Path, ...]:
    return tuple(
        sorted(
            {
                *module_name_to_paths.get(module_name, ()),
                *_repo_owned_module_paths(module_name, settings),
            }
        )
    )


def _repo_owned_module_paths(module_name: str, settings: AuditSettings) -> tuple[Path, ...]:
    if module_name != "autoclaw" and not module_name.startswith("autoclaw."):
        return ()
    relative_parts = module_name.split(".")[1:]
    paths: set[Path] = set()
    for root in (
        settings.apps_api_root / "autoclaw",
        settings.apps_api_root / "src" / "autoclaw",
    ):
        paths.update(_existing_module_paths(root, relative_parts))
    return tuple(sorted(paths))


def _existing_module_paths(root: Path, relative_parts: list[str]) -> set[Path]:
    if not relative_parts:
        package_init = root / "__init__.py"
        return {package_init} if package_init.exists() else set()
    module_base = root.joinpath(*relative_parts)
    candidates = {
        module_base.with_suffix(".py"),
        module_base / "__init__.py",
    }
    return {candidate for candidate in candidates if candidate.exists()}
