from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .models import AuditResults, AuditSettings
from .report_sections import (
    render_cross_lane_test_import_findings,
    render_cross_module_findings,
    render_cross_module_private_access_findings,
    render_duplicate_module_name_findings,
    render_file_line_violations,
    render_function_size_violations,
    render_generic_module_name_findings,
    render_gitkeep_placeholders,
    render_import_direction_findings,
    render_import_placement_findings,
    render_import_wrapper_modules,
    render_module_shape_findings,
    render_phase_named_test_directory_findings,
    render_phase_named_test_file_findings,
    render_phase_named_test_support_api_findings,
    render_public_naming_findings,
    render_relative_import_depth_findings,
    render_sibling_prefix_findings,
    render_star_import_collectors,
    render_todo_comment_findings,
    render_wildcard_import_findings,
    render_zero_reference_helpers,
)


def render_audit_report(results: AuditResults, settings: AuditSettings) -> str:
    lines = _render_summary_lines(results, settings)
    lines.extend(_render_finding_sections(results, settings))

    if not results.has_findings:
        lines.extend(["No findings.", ""])

    lines.extend(_report_footer_lines())
    return "\n".join(lines).rstrip() + "\n"


def _render_finding_sections(results: AuditResults, settings: AuditSettings) -> list[str]:
    lines: list[str] = []
    for findings, render_section in _section_specs(results, settings):
        if not findings:
            continue
        lines.extend(render_section(findings))
    return lines


def _section_specs(
    results: AuditResults,
    settings: AuditSettings,
) -> list[tuple[Any, Callable[[Any], list[str]]]]:
    return [
        *_import_interface_section_specs(results, settings),
        *_structure_section_specs(results, settings),
        *_naming_section_specs(results, settings),
        *_threshold_section_specs(results, settings),
    ]


def _import_interface_section_specs(
    results: AuditResults,
    settings: AuditSettings,
) -> list[tuple[Any, Callable[[Any], list[str]]]]:
    return [
        (
            results.import_direction_findings,
            lambda findings: render_import_direction_findings(findings, settings.root),
        ),
        (
            results.import_placement_findings,
            lambda findings: render_import_placement_findings(findings, settings.root),
        ),
        (
            results.wildcard_import_findings,
            lambda findings: render_wildcard_import_findings(findings, settings.root),
        ),
        (
            results.relative_import_depth_findings,
            lambda findings: render_relative_import_depth_findings(findings, settings.root),
        ),
    ]


def _structure_section_specs(
    results: AuditResults,
    settings: AuditSettings,
) -> list[tuple[Any, Callable[[Any], list[str]]]]:
    return [
        (
            results.import_wrapper_modules,
            lambda findings: render_import_wrapper_modules(findings, settings.root),
        ),
        (
            results.sibling_prefix_findings,
            lambda findings: render_sibling_prefix_findings(findings, settings.root),
        ),
        (
            results.generic_module_name_findings,
            lambda findings: render_generic_module_name_findings(findings, settings.root),
        ),
        (
            results.duplicate_module_name_findings,
            lambda findings: render_duplicate_module_name_findings(findings, settings.root),
        ),
        (
            results.phase_named_test_directory_findings,
            lambda findings: render_phase_named_test_directory_findings(findings, settings.root),
        ),
        (
            results.phase_named_test_file_findings,
            lambda findings: render_phase_named_test_file_findings(findings, settings.root),
        ),
        (
            results.phase_named_test_support_api_findings,
            lambda findings: render_phase_named_test_support_api_findings(findings, settings.root),
        ),
        (
            results.cross_lane_test_import_findings,
            lambda findings: render_cross_lane_test_import_findings(findings, settings.root),
        ),
        (
            results.star_import_collectors,
            lambda findings: render_star_import_collectors(findings, settings.root),
        ),
        (
            results.module_shape_findings,
            lambda findings: render_module_shape_findings(findings, settings.root),
        ),
        (
            results.todo_comment_findings,
            lambda findings: render_todo_comment_findings(findings, settings.root),
        ),
        (
            results.cross_module_findings,
            lambda findings: render_cross_module_findings(findings, settings.root),
        ),
        (
            results.cross_module_private_access_findings,
            lambda findings: render_cross_module_private_access_findings(
                findings,
                settings.root,
            ),
        ),
        (
            results.zero_reference_helpers,
            lambda findings: render_zero_reference_helpers(findings, settings.root),
        ),
        (
            results.gitkeep_placeholders,
            lambda findings: render_gitkeep_placeholders(findings, settings.root),
        ),
    ]


def _naming_section_specs(
    results: AuditResults,
    settings: AuditSettings,
) -> list[tuple[Any, Callable[[Any], list[str]]]]:
    return [
        (
            results.public_naming_findings,
            lambda findings: render_public_naming_findings(findings, settings.root),
        ),
    ]


def _threshold_section_specs(
    results: AuditResults,
    settings: AuditSettings,
) -> list[tuple[Any, Callable[[Any], list[str]]]]:
    return [
        (
            results.file_line_violations,
            lambda findings: render_file_line_violations(findings, settings),
        ),
        (
            results.function_size_violations,
            lambda findings: render_function_size_violations(findings, settings.root),
        ),
    ]


def _report_footer_lines() -> list[str]:
    return [
        "This command is report-only by default.",
        "Rerun with `--fail-on-findings` to make findings exit non-zero.",
    ]


def _render_summary_lines(results: AuditResults, settings: AuditSettings) -> list[str]:
    return [
        "Execution STYLE audit",
        "",
        f"- scanned python files: {len(results.modules)}",
        "- scan roots:",
        *[f"  - {path.relative_to(settings.root)}" for path in settings.scan_roots],
        f"- explicit path exclusions: {len(settings.excluded_paths)}",
        f"- import-direction findings: {len(results.import_direction_findings)}",
        f"- top-level import placement violations: {len(results.import_placement_findings)}",
        f"- wildcard imports outside export surfaces: {len(results.wildcard_import_findings)}",
        f"- deep relative imports outside tests: {len(results.relative_import_depth_findings)}",
        f"- import-only wrapper modules: {len(results.import_wrapper_modules)}",
        f"- sibling-prefix layout families: {len(results.sibling_prefix_findings)}",
        f"- generic module filenames: {len(results.generic_module_name_findings)}",
        "- duplicate module-name ownership findings: "
        f"{len(results.duplicate_module_name_findings)}",
        f"- phase-numbered test directories: {len(results.phase_named_test_directory_findings)}",
        f"- phase-numbered test filenames: {len(results.phase_named_test_file_findings)}",
        f"- phase-coded test support APIs: {len(results.phase_named_test_support_api_findings)}",
        f"- cross-lane test imports: {len(results.cross_lane_test_import_findings)}",
        f"- star-import test collectors: {len(results.star_import_collectors)}",
        f"- module-shape findings: {len(results.module_shape_findings)}",
        f"- TODO comments missing owner/removal detail: {len(results.todo_comment_findings)}",
        f"- cross-module private-helper imports: {len(results.cross_module_findings)}",
        "- cross-module private access findings: "
        f"{len(results.cross_module_private_access_findings)}",
        f"- zero-reference private module helpers: {len(results.zero_reference_helpers)}",
        f"- tracked .gitkeep placeholders: {len(results.gitkeep_placeholders)}",
        f"- public naming findings: {len(results.public_naming_findings)}",
        f"- file-size threshold violations: {len(results.file_line_violations)}",
        f"- function-size threshold violations: {len(results.function_size_violations)}",
        "",
    ]
