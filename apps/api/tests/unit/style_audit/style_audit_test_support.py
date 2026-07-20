from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def load_style_audit_namespace() -> SimpleNamespace:
    _ensure_repo_root_on_path()
    return SimpleNamespace(
        cli=importlib.import_module("scripts.docs.style_audit.cli"),
        config=importlib.import_module("scripts.docs.style_audit.config"),
        import_direction_scan=importlib.import_module(
            "scripts.docs.style_audit.import_direction_scan"
        ),
        layout_scan=importlib.import_module("scripts.docs.style_audit.layout_scan"),
        models=importlib.import_module("scripts.docs.style_audit.models"),
        module_shape_scan=importlib.import_module("scripts.docs.style_audit.module_shape_scan"),
        module_loader=importlib.import_module("scripts.docs.style_audit.module_loader"),
        private_helpers=importlib.import_module("scripts.docs.style_audit.private_helpers"),
        public_naming_scan=importlib.import_module("scripts.docs.style_audit.public_naming_scan"),
        report=importlib.import_module("scripts.docs.style_audit.report"),
        scan=importlib.import_module("scripts.docs.style_audit.scan"),
        test_structure_scan=importlib.import_module("scripts.docs.style_audit.test_structure_scan"),
        threshold_scan=importlib.import_module("scripts.docs.style_audit.threshold_scan"),
    )


def build_style_audit_settings(
    tmp_path: Path,
    *,
    scan_roots: tuple[Path, ...] | None = None,
    excluded_paths: frozenset[Path] | None = None,
) -> Any:
    audit = load_style_audit_namespace()
    apps_api_root = tmp_path / "apps" / "api"
    apps_api_root.mkdir(parents=True, exist_ok=True)
    if scan_roots is None:
        scan_root = tmp_path / "scan"
        scan_root.mkdir(parents=True, exist_ok=True)
        scan_roots = (scan_root,)
    for root in scan_roots:
        if root.suffix == ".py":
            root.parent.mkdir(parents=True, exist_ok=True)
            continue
        root.mkdir(parents=True, exist_ok=True)
    return audit.models.AuditSettings(
        root=tmp_path,
        apps_api_root=apps_api_root,
        scan_roots=scan_roots,
        excluded_paths=excluded_paths or frozenset(),
        file_split_review_threshold=600,
        file_no_growth_threshold=600,
        function_size_threshold=80,
        sibling_prefix_threshold=3,
        approved_wrapper_modules=frozenset(),
        approved_wrapper_directories=frozenset({apps_api_root / "app" / "api" / "routes"}),
        approved_duplicate_module_name_paths=frozenset(),
        app_shell_direct_owner_modules=frozenset(),
        approved_import_direction_exception_modules=frozenset(),
        approved_public_naming_exceptions=frozenset(),
        disallowed_generic_module_names=frozenset({"helpers"}),
        inexact_package_names=frozenset({"runtime"}),
        public_naming_scan_roots=scan_roots,
        public_naming_extra_modules=frozenset(),
        module_shape_scan_roots=scan_roots,
        module_shape_excluded_modules=frozenset(),
    )


def write_python_module(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_empty_audit_results(models: Any, root: Path) -> Any:
    module = models.ModuleRecord(
        path=root / "dummy.py",
        module_name="dummy",
        tree=ast.parse("pass\n"),
        lines=("pass",),
    )
    return models.AuditResults(
        modules=(module,),
        sibling_prefix_findings=(),
        import_wrapper_modules=(),
        star_import_collectors=(),
        phase_named_test_directory_findings=(),
        phase_named_test_file_findings=(),
        phase_named_test_support_api_findings=(),
        cross_lane_test_import_findings=(),
        import_direction_findings=(),
        import_placement_findings=(),
        wildcard_import_findings=(),
        todo_comment_findings=(),
        relative_import_depth_findings=(),
        cross_module_private_access_findings=(),
        gitkeep_placeholders=(),
        generic_module_name_findings=(),
        duplicate_module_name_findings=(),
        public_naming_findings=(),
        module_shape_findings=(),
        cross_module_findings=(),
        zero_reference_helpers=(),
        file_line_violations=(),
        function_size_violations=(),
    )


def build_results_with_findings(models: Any, tmp_path: Path) -> Any:
    helper, reference = _build_cross_module_sample_records(models, tmp_path)
    base = build_empty_audit_results(models, tmp_path)
    return replace(
        base,
        **_build_results_with_findings_payload(models, tmp_path, helper, reference),
    )


def _build_cross_module_sample_records(models: Any, tmp_path: Path) -> tuple[Any, Any]:
    helper = models.HelperDefinition(
        path=tmp_path / "helper.py",
        name="_helper",
        line=3,
        end_line=5,
        non_comment_lines=3,
    )
    reference = models.ReferenceLocation(
        path=tmp_path / "consumer.py",
        line=9,
        kind="direct-import",
    )
    return helper, reference


def _build_results_with_findings_payload(
    models: Any,
    tmp_path: Path,
    helper: Any,
    reference: Any,
) -> dict[str, Any]:
    return {
        **_build_results_import_findings_payload(models, tmp_path),
        **_build_results_structure_findings_payload(models, tmp_path, helper, reference),
        **_build_results_threshold_payload(models, tmp_path, helper),
    }


def _build_results_import_findings_payload(models: Any, tmp_path: Path) -> dict[str, Any]:
    return {
        "import_direction_findings": (
            models.ImportDirectionFinding(
                path=tmp_path / "autoclaw" / "consumer.py",
                line=5,
                statement="from app.runtime.owner import VALUE",
                owner_family="autoclaw",
                violated_rule="autoclaw-consumer-imports-app-owner",
            ),
        ),
        "import_placement_findings": (
            models.ImportPlacementFinding(
                path=tmp_path / "late_import.py",
                line=6,
                statement="import math",
            ),
        ),
        "wildcard_import_findings": (
            models.WildcardImportFinding(
                path=tmp_path / "wildcard.py",
                line=2,
                source="helpers",
            ),
        ),
        "todo_comment_findings": (
            models.TodoCommentFinding(
                path=tmp_path / "todo.py",
                line=1,
                text="# TODO fix this",
            ),
        ),
        "relative_import_depth_findings": (
            models.ImportPlacementFinding(
                path=tmp_path / "deep_relative.py",
                line=3,
                statement="from ...helpers import thing",
            ),
        ),
    }


def _build_results_structure_findings_payload(
    models: Any,
    tmp_path: Path,
    helper: Any,
    reference: Any,
) -> dict[str, Any]:
    return {
        **_build_results_layout_findings_payload(models, tmp_path),
        **_build_results_phase_structure_findings_payload(models, tmp_path),
        **_build_results_naming_shape_findings_payload(models, tmp_path),
        **_build_results_shared_surface_findings_payload(models, tmp_path, helper, reference),
    }


def _build_results_layout_findings_payload(models: Any, tmp_path: Path) -> dict[str, Any]:
    return {
        "sibling_prefix_findings": (
            models.SiblingPrefixFinding(
                directory=tmp_path / "pkg",
                prefix="alpha",
                members=(tmp_path / "pkg" / "alpha_one.py", tmp_path / "pkg" / "alpha_two.py"),
            ),
        ),
        "import_wrapper_modules": (tmp_path / "wrapper.py",),
        "star_import_collectors": (
            models.StarImportCollectorFinding(
                path=tmp_path / "test_star.py",
                imports=(models.StarImportLocation(line=4, source="app.runtime.source"),),
            ),
        ),
        "gitkeep_placeholders": (tmp_path / ".gitkeep",),
        "generic_module_name_findings": (
            models.GenericModuleNameFinding(
                path=tmp_path / "helpers.py",
                package_name="runtime",
                module_name="helpers",
            ),
        ),
        "duplicate_module_name_findings": (
            models.DuplicateModuleNameFinding(
                module_name="autoclaw.common",
                paths=(
                    tmp_path / "apps" / "api" / "autoclaw" / "common.py",
                    tmp_path / "apps" / "api" / "src" / "autoclaw" / "common.py",
                ),
            ),
        ),
    }


def _build_results_phase_structure_findings_payload(models: Any, tmp_path: Path) -> dict[str, Any]:
    return {
        "phase_named_test_directory_findings": (
            models.PhaseNamedTestDirectoryFinding(
                directory=tmp_path / "tests" / "integration" / "phase5a",
                lane="integration",
                phase_directory_name="phase5a",
            ),
        ),
        "phase_named_test_file_findings": (
            models.PhaseNamedTestFileFinding(
                path=tmp_path
                / "tests"
                / "integration"
                / "public_surfaces"
                / "test_root_cli_phase5a.py",
                lane="integration",
                phase_owner_name="phase5a",
            ),
        ),
        "phase_named_test_support_api_findings": (
            models.PhaseNamedTestSupportApiFinding(
                path=tmp_path / "tests" / "integration" / "public_surfaces" / "support.py",
                lane="integration",
                line=4,
                name="Phase5aHttpContext",
                kind="class",
                phase_owner_name="phase5a",
            ),
        ),
        "cross_lane_test_import_findings": (
            models.CrossLaneTestImportFinding(
                path=tmp_path / "tests" / "unit" / "test_cli.py",
                line=12,
                statement="from tests.integration.public_surfaces.support import helper",
                consumer_lane="unit",
                imported_lane="integration",
            ),
        ),
    }


def _build_results_naming_shape_findings_payload(models: Any, tmp_path: Path) -> dict[str, Any]:
    return {
        "public_naming_findings": (
            models.PublicNamingFinding(
                path=tmp_path / "naming.py",
                line=3,
                name="handle_dispatch",
                kind="function",
                reason="weak_public_verb",
            ),
        ),
        "module_shape_findings": (
            models.ModuleShapeFinding(
                path=tmp_path / "ordering.py",
                line=7,
                name="public_entrypoint",
                reason="public_after_private_helper",
            ),
        ),
    }


def _build_results_shared_surface_findings_payload(
    models: Any,
    tmp_path: Path,
    helper: Any,
    reference: Any,
) -> dict[str, Any]:
    return {
        "cross_module_private_access_findings": (
            models.CrossModulePrivateAccessFinding(
                helper="_helper",
                helper_path=tmp_path / "helper.py",
                helper_line=3,
                consumer_path=tmp_path / "consumer.py",
                consumer_line=9,
                kind="direct-import",
            ),
        ),
        "cross_module_findings": ((helper, reference),),
    }


def _build_results_threshold_payload(models: Any, tmp_path: Path, helper: Any) -> dict[str, Any]:
    return {
        "zero_reference_helpers": (helper,),
        "file_line_violations": ((tmp_path / "big.py", 700),),
        "function_size_violations": (
            models.FunctionSizeViolation(
                path=tmp_path / "big.py",
                name="too_big",
                line=10,
                non_comment_lines=99,
            ),
        ),
    }
