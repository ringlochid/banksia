from __future__ import annotations

from pathlib import Path

from .models import (
    AuditSettings,
    CrossLaneTestImportFinding,
    CrossModulePrivateAccessFinding,
    DuplicateModuleNameFinding,
    FunctionSizeViolation,
    GenericModuleNameFinding,
    HelperDefinition,
    ImportDirectionFinding,
    ImportPlacementFinding,
    ModuleShapeFinding,
    PhaseNamedTestDirectoryFinding,
    PhaseNamedTestFileFinding,
    PhaseNamedTestSupportApiFinding,
    PublicNamingFinding,
    ReferenceLocation,
    SiblingPrefixFinding,
    StarImportCollectorFinding,
    TodoCommentFinding,
    WildcardImportFinding,
)


def render_import_direction_findings(
    findings: tuple[ImportDirectionFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Import-direction findings", ""]
    for finding in findings:
        lines.append(
            f"- {finding.path.relative_to(root)}:{finding.line} `{finding.statement}` "
            f"({finding.owner_family}, {finding.violated_rule})"
        )
    lines.append("")
    return lines


def render_sibling_prefix_findings(
    findings: tuple[SiblingPrefixFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Sibling-prefix layout families", ""]
    for finding in findings:
        lines.append(
            f"- {finding.directory.relative_to(root)}: prefix `{finding.prefix}` "
            f"across {len(finding.members)} sibling files"
        )
        for member in finding.members:
            lines.append(f"  - {member.name}")
        lines.append("")
    return lines


def render_import_wrapper_modules(modules: tuple[Path, ...], root: Path) -> list[str]:
    lines = ["Import-only wrapper modules", ""]
    for module in modules:
        lines.append(f"- {module.relative_to(root)}")
    lines.append("")
    return lines


def render_star_import_collectors(
    findings: tuple[StarImportCollectorFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Star-import test collectors", ""]
    for finding in findings:
        lines.append(f"- {finding.path.relative_to(root)}")
        for imported in finding.imports:
            lines.append(f"  - line {imported.line}: from `{imported.source}` import `*`")
    lines.append("")
    return lines


def render_phase_named_test_directory_findings(
    findings: tuple[PhaseNamedTestDirectoryFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Phase-numbered test directories", ""]
    for finding in findings:
        lines.append(
            f"- {finding.directory.relative_to(root)}: `{finding.phase_directory_name}` under "
            f"`{finding.lane}`"
        )
    lines.append("")
    return lines


def render_phase_named_test_file_findings(
    findings: tuple[PhaseNamedTestFileFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Phase-numbered test filenames", ""]
    for finding in findings:
        lines.append(
            f"- {finding.path.relative_to(root)}: `{finding.phase_owner_name}` under "
            f"`{finding.lane}`"
        )
    lines.append("")
    return lines


def render_phase_named_test_support_api_findings(
    findings: tuple[PhaseNamedTestSupportApiFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Phase-coded test support APIs", ""]
    for finding in findings:
        lines.append(
            f"- {finding.path.relative_to(root)}:{finding.line} `{finding.name}` "
            f"({finding.kind}, {finding.phase_owner_name}, {finding.lane})"
        )
    lines.append("")
    return lines


def render_cross_lane_test_import_findings(
    findings: tuple[CrossLaneTestImportFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Cross-lane test imports", ""]
    for finding in findings:
        lines.append(
            f"- {finding.path.relative_to(root)}:{finding.line} `{finding.statement}` "
            f"({finding.consumer_lane} -> {finding.imported_lane})"
        )
    lines.append("")
    return lines


def render_import_placement_findings(
    findings: tuple[ImportPlacementFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Top-level import placement violations", ""]
    for finding in findings:
        lines.append(f"- {finding.path.relative_to(root)}:{finding.line} `{finding.statement}`")
    lines.append("")
    return lines


def render_wildcard_import_findings(
    findings: tuple[WildcardImportFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Wildcard imports outside deliberate export surfaces", ""]
    for finding in findings:
        lines.append(
            f"- {finding.path.relative_to(root)}:{finding.line} from `{finding.source}` import `*`"
        )
    lines.append("")
    return lines


def render_todo_comment_findings(
    findings: tuple[TodoCommentFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["TODO comments missing owner or removal detail", ""]
    for finding in findings:
        lines.append(f"- {finding.path.relative_to(root)}:{finding.line} `{finding.text}`")
    lines.append("")
    return lines


def render_relative_import_depth_findings(
    findings: tuple[ImportPlacementFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Deep relative imports outside tests", ""]
    for finding in findings:
        lines.append(f"- {finding.path.relative_to(root)}:{finding.line} `{finding.statement}`")
    lines.append("")
    return lines


def render_gitkeep_placeholders(placeholders: tuple[Path, ...], root: Path) -> list[str]:
    lines = ["Tracked .gitkeep placeholders", ""]
    for placeholder in placeholders:
        lines.append(f"- {placeholder.relative_to(root)}")
    lines.append("")
    return lines


def render_generic_module_name_findings(
    findings: tuple[GenericModuleNameFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Generic module filenames", ""]
    for finding in findings:
        lines.append(
            f"- {finding.path.relative_to(root)}: generic `{finding.module_name}.py` "
            f"under package `{finding.package_name}`"
        )
    lines.append("")
    return lines


def render_duplicate_module_name_findings(
    findings: tuple[DuplicateModuleNameFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Duplicate module-name ownership findings", ""]
    for finding in findings:
        lines.append(f"- `{finding.module_name}`")
        for path in finding.paths:
            lines.append(f"  - {path.relative_to(root)}")
        lines.append("")
    return lines


def render_public_naming_findings(
    findings: tuple[PublicNamingFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Public naming findings", ""]
    for finding in findings:
        lines.append(
            f"- {finding.path.relative_to(root)}:{finding.line} `{finding.name}` "
            f"({finding.kind}, {finding.reason})"
        )
    lines.append("")
    return lines


def render_module_shape_findings(
    findings: tuple[ModuleShapeFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Module-shape findings", ""]
    for finding in findings:
        lines.append(
            f"- {finding.path.relative_to(root)}:{finding.line} `{finding.name}` ({finding.reason})"
        )
    lines.append("")
    return lines


def render_cross_module_findings(
    findings: tuple[tuple[HelperDefinition, ReferenceLocation], ...],
    root: Path,
) -> list[str]:
    grouped: dict[tuple[Path, str], list[ReferenceLocation]] = {}
    for helper, location in findings:
        grouped.setdefault((helper.path, helper.name), []).append(location)

    lines = ["Cross-module private-helper imports", ""]
    for helper_path, helper_name in sorted(grouped):
        helper = next(
            finding_helper
            for finding_helper, _ in findings
            if finding_helper.path == helper_path and finding_helper.name == helper_name
        )
        lines.append(f"- {format_helper(helper, root)}")
        for location in sorted(grouped[(helper_path, helper_name)], key=reference_sort_key):
            lines.append(
                f"  - {location.path.relative_to(root)}:{location.line} via {location.kind}"
            )
        lines.append("")
    return lines


def render_cross_module_private_access_findings(
    findings: tuple[CrossModulePrivateAccessFinding, ...],
    root: Path,
) -> list[str]:
    lines = ["Cross-module private access findings", ""]
    for finding in findings:
        lines.append(
            f"- {finding.consumer_path.relative_to(root)}:{finding.consumer_line} "
            f"-> {finding.helper_path.relative_to(root)}:{finding.helper_line} "
            f"`{finding.helper}` via {finding.kind}"
        )
    lines.append("")
    return lines


def render_zero_reference_helpers(
    helpers: tuple[HelperDefinition, ...],
    root: Path,
) -> list[str]:
    lines = ["Zero-reference private module helpers", ""]
    for helper in helpers:
        lines.append(
            f"- {format_helper(helper, root)} ({helper.non_comment_lines} non-comment lines)"
        )
    lines.append("")
    return lines


def render_file_line_violations(
    violations: tuple[tuple[Path, int], ...],
    settings: AuditSettings,
) -> list[str]:
    lines = ["File-size threshold violations", ""]
    for path, line_count in violations:
        threshold = (
            f">{settings.file_no_growth_threshold} no-growth"
            if line_count > settings.file_no_growth_threshold
            else f">{settings.file_split_review_threshold} split-review"
        )
        lines.append(f"- {path.relative_to(settings.root)}: {line_count} lines ({threshold})")
    lines.append("")
    return lines


def render_function_size_violations(
    violations: tuple[FunctionSizeViolation, ...],
    root: Path,
) -> list[str]:
    lines = ["Function-size threshold violations", ""]
    for violation in violations:
        lines.append(
            f"- {violation.path.relative_to(root)}:{violation.line} `{violation.name}` "
            f"({violation.non_comment_lines} non-comment lines)"
        )
    lines.append("")
    return lines


def format_helper(helper: HelperDefinition, root: Path) -> str:
    return f"{helper.path.relative_to(root)}:{helper.line} `{helper.name}`"


def reference_sort_key(location: ReferenceLocation) -> tuple[str, int, str]:
    return (location.path.as_posix(), location.line, location.kind)
