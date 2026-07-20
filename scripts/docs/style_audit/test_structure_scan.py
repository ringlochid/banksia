from __future__ import annotations

import ast
import re
from pathlib import Path

from .models import (
    CrossLaneTestImportFinding,
    ModuleRecord,
    PhaseNamedTestDirectoryFinding,
    PhaseNamedTestFileFinding,
    PhaseNamedTestSupportApiFinding,
)

PHASE_DIRECTORY_PATTERN = re.compile(r"phase\d+(?:\.\d+)?[a-z]?$")
PHASE_OWNER_PATTERN = re.compile(r"phase\d+(?:\.\d+)?[a-z]?", re.IGNORECASE)
TEST_LANES = {"unit", "integration", "e2e"}


def collect_phase_named_test_directory_findings(
    modules: list[ModuleRecord],
    tests_root: Path,
) -> tuple[PhaseNamedTestDirectoryFinding, ...]:
    directories: set[tuple[Path, str, str]] = set()
    for module in modules:
        try:
            relative_parts = module.path.relative_to(tests_root).parts[:-1]
        except ValueError:
            continue
        if not relative_parts:
            continue
        lane = relative_parts[0]
        if lane not in TEST_LANES:
            continue
        for index, part in enumerate(relative_parts[1:], start=1):
            if not PHASE_DIRECTORY_PATTERN.fullmatch(part):
                continue
            directories.add((tests_root / Path(*relative_parts[: index + 1]), lane, part))
    return tuple(
        PhaseNamedTestDirectoryFinding(
            directory=directory,
            lane=lane,
            phase_directory_name=phase_directory_name,
        )
        for directory, lane, phase_directory_name in sorted(
            directories,
            key=lambda item: item[0].as_posix(),
        )
    )


def collect_phase_named_test_file_findings(
    modules: list[ModuleRecord],
    tests_root: Path,
) -> tuple[PhaseNamedTestFileFinding, ...]:
    findings: list[PhaseNamedTestFileFinding] = []
    for module in modules:
        lane = _test_lane_for_path(module.path, tests_root)
        if lane is None:
            continue
        phase_match = PHASE_OWNER_PATTERN.search(module.path.stem)
        if phase_match is None:
            continue
        findings.append(
            PhaseNamedTestFileFinding(
                path=module.path,
                lane=lane,
                phase_owner_name=phase_match.group(0).lower(),
            )
        )
    return tuple(sorted(findings, key=lambda finding: finding.path.as_posix()))


def collect_phase_named_test_support_api_findings(
    modules: list[ModuleRecord],
    tests_root: Path,
) -> tuple[PhaseNamedTestSupportApiFinding, ...]:
    findings: list[PhaseNamedTestSupportApiFinding] = []
    for module in modules:
        lane = _test_lane_for_path(module.path, tests_root)
        if lane is None or not _is_support_module(module.path):
            continue
        for node in module.tree.body:
            if not isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
                continue
            phase_match = PHASE_OWNER_PATTERN.search(node.name)
            if phase_match is None:
                continue
            findings.append(
                PhaseNamedTestSupportApiFinding(
                    path=module.path,
                    lane=lane,
                    line=node.lineno,
                    name=node.name,
                    kind=_node_kind(node),
                    phase_owner_name=phase_match.group(0).lower(),
                )
            )
    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.path.as_posix(),
                finding.line,
                finding.name,
            ),
        )
    )


def collect_cross_lane_test_import_findings(
    modules: list[ModuleRecord],
    tests_root: Path,
) -> tuple[CrossLaneTestImportFinding, ...]:
    findings: list[CrossLaneTestImportFinding] = []
    for module in modules:
        consumer_lane = _test_lane_for_path(module.path, tests_root)
        if consumer_lane is None:
            continue
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_lane = _imported_test_lane(node)
            if imported_lane is None or imported_lane == consumer_lane:
                continue
            findings.append(
                CrossLaneTestImportFinding(
                    path=module.path,
                    line=node.lineno,
                    statement=ast.unparse(node),
                    consumer_lane=consumer_lane,
                    imported_lane=imported_lane,
                )
            )
    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.path.as_posix(),
                finding.line,
                finding.statement,
            ),
        )
    )


def _test_lane_for_path(path: Path, tests_root: Path) -> str | None:
    try:
        relative_parts = path.relative_to(tests_root).parts
    except ValueError:
        return None
    if not relative_parts:
        return None
    lane = relative_parts[0]
    return lane if lane in TEST_LANES else None


def _imported_test_lane(node: ast.ImportFrom) -> str | None:
    module_name = _absolute_import_from_module(node)
    if module_name is None or not module_name.startswith("tests."):
        return None
    parts = module_name.split(".")
    if len(parts) < 2:
        return None
    imported_lane = parts[1]
    return imported_lane if imported_lane in TEST_LANES else None


def _is_support_module(path: Path) -> bool:
    stem = path.stem
    return stem == "support" or stem.endswith("_support")


def _node_kind(node: ast.AsyncFunctionDef | ast.ClassDef | ast.FunctionDef) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    return "function"


def _absolute_import_from_module(node: ast.ImportFrom) -> str | None:
    if node.level != 0:
        return None
    if node.module is None:
        return None
    return node.module
