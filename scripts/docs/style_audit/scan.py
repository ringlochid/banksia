from __future__ import annotations

from pathlib import Path

from .convention_scan import (
    collect_import_placement_findings,
    collect_relative_import_depth_findings,
    collect_todo_comment_findings,
    collect_wildcard_import_findings,
)
from .import_direction_scan import collect_import_direction_findings
from .layout_scan import collect_structural_findings
from .models import AuditResults, AuditSettings, DuplicateModuleNameFinding, ModuleRecord
from .module_loader import load_modules
from .module_shape_scan import collect_module_shape_findings
from .private_helpers import (
    collect_cross_module_private_access_findings,
    collect_cross_module_references,
    collect_private_helpers,
    collect_same_module_references,
    zero_reference_helpers,
)
from .public_naming_scan import collect_public_naming_findings
from .test_structure_scan import (
    collect_cross_lane_test_import_findings,
    collect_phase_named_test_directory_findings,
    collect_phase_named_test_file_findings,
    collect_phase_named_test_support_api_findings,
)
from .threshold_scan import collect_file_line_violations, collect_function_size_violations


def run_style_audit(settings: AuditSettings) -> AuditResults:
    modules = load_modules(settings)
    structural_findings = collect_structural_findings(modules, settings)
    module_name_to_path = _unique_module_name_to_path(
        modules,
        structural_findings.duplicate_module_name_findings,
    )
    helpers, helpers_by_path = collect_private_helpers(modules)
    references = collect_same_module_references(helpers, helpers_by_path, modules)
    cross_module_findings = collect_cross_module_references(
        helpers_by_path,
        module_name_to_path,
        modules,
        references,
    )
    return AuditResults(
        modules=tuple(modules),
        sibling_prefix_findings=structural_findings.sibling_prefix_findings,
        import_wrapper_modules=structural_findings.import_wrapper_modules,
        star_import_collectors=structural_findings.star_import_collectors,
        phase_named_test_directory_findings=collect_phase_named_test_directory_findings(
            modules,
            settings.apps_api_root / "tests",
        ),
        phase_named_test_file_findings=collect_phase_named_test_file_findings(
            modules,
            settings.apps_api_root / "tests",
        ),
        phase_named_test_support_api_findings=collect_phase_named_test_support_api_findings(
            modules,
            settings.apps_api_root / "tests",
        ),
        cross_lane_test_import_findings=collect_cross_lane_test_import_findings(
            modules,
            settings.apps_api_root / "tests",
        ),
        import_direction_findings=collect_import_direction_findings(modules, settings),
        import_placement_findings=tuple(collect_import_placement_findings(modules)),
        wildcard_import_findings=tuple(collect_wildcard_import_findings(modules)),
        todo_comment_findings=tuple(collect_todo_comment_findings(modules)),
        relative_import_depth_findings=collect_relative_import_depth_findings(modules),
        cross_module_private_access_findings=collect_cross_module_private_access_findings(
            helpers_by_path,
            module_name_to_path,
            modules,
        ),
        gitkeep_placeholders=structural_findings.gitkeep_placeholders,
        generic_module_name_findings=structural_findings.generic_module_name_findings,
        duplicate_module_name_findings=structural_findings.duplicate_module_name_findings,
        public_naming_findings=collect_public_naming_findings(modules, settings),
        module_shape_findings=collect_module_shape_findings(modules, settings),
        cross_module_findings=tuple(cross_module_findings),
        zero_reference_helpers=zero_reference_helpers(helpers, references),
        file_line_violations=collect_file_line_violations(modules, settings),
        function_size_violations=collect_function_size_violations(
            modules,
            settings.function_size_threshold,
        ),
    )


def _unique_module_name_to_path(
    modules: list[ModuleRecord],
    duplicate_findings: tuple[DuplicateModuleNameFinding, ...],
) -> dict[str, Path]:
    duplicated_names = {finding.module_name for finding in duplicate_findings}
    return {
        module.module_name: module.path
        for module in modules
        if module.module_name is not None and module.module_name not in duplicated_names
    }
