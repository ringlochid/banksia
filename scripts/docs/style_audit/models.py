from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuditSettings:
    root: Path
    apps_api_root: Path
    scan_roots: tuple[Path, ...]
    excluded_paths: frozenset[Path]
    file_split_review_threshold: int
    file_no_growth_threshold: int
    function_size_threshold: int
    sibling_prefix_threshold: int
    approved_wrapper_modules: frozenset[Path]
    approved_wrapper_directories: frozenset[Path]
    approved_duplicate_module_name_paths: frozenset[Path]
    app_shell_direct_owner_modules: frozenset[Path]
    approved_import_direction_exception_modules: frozenset[Path]
    approved_public_naming_exceptions: frozenset[tuple[Path, str]]
    disallowed_generic_module_names: frozenset[str]
    inexact_package_names: frozenset[str]
    public_naming_scan_roots: tuple[Path, ...]
    public_naming_extra_modules: frozenset[Path]
    module_shape_scan_roots: tuple[Path, ...]
    module_shape_excluded_modules: frozenset[Path]


@dataclass(frozen=True)
class HelperDefinition:
    path: Path
    name: str
    line: int
    end_line: int
    non_comment_lines: int


@dataclass(frozen=True)
class FunctionSizeViolation:
    path: Path
    name: str
    line: int
    non_comment_lines: int


@dataclass(frozen=True)
class ReferenceLocation:
    path: Path
    line: int
    kind: str


@dataclass(frozen=True)
class SiblingPrefixFinding:
    directory: Path
    prefix: str
    members: tuple[Path, ...]


@dataclass(frozen=True)
class StarImportLocation:
    line: int
    source: str


@dataclass(frozen=True)
class StarImportCollectorFinding:
    path: Path
    imports: tuple[StarImportLocation, ...]


@dataclass(frozen=True)
class ImportPlacementFinding:
    path: Path
    line: int
    statement: str


@dataclass(frozen=True)
class WildcardImportFinding:
    path: Path
    line: int
    source: str


@dataclass(frozen=True)
class TodoCommentFinding:
    path: Path
    line: int
    text: str


@dataclass(frozen=True)
class CrossModulePrivateAccessFinding:
    helper: str
    helper_path: Path
    helper_line: int
    consumer_path: Path
    consumer_line: int
    kind: str


@dataclass(frozen=True)
class GenericModuleNameFinding:
    path: Path
    package_name: str
    module_name: str


@dataclass(frozen=True)
class DuplicateModuleNameFinding:
    module_name: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class PhaseNamedTestDirectoryFinding:
    directory: Path
    lane: str
    phase_directory_name: str


@dataclass(frozen=True)
class PhaseNamedTestFileFinding:
    path: Path
    lane: str
    phase_owner_name: str


@dataclass(frozen=True)
class PhaseNamedTestSupportApiFinding:
    path: Path
    lane: str
    line: int
    name: str
    kind: str
    phase_owner_name: str


@dataclass(frozen=True)
class CrossLaneTestImportFinding:
    path: Path
    line: int
    statement: str
    consumer_lane: str
    imported_lane: str


@dataclass(frozen=True)
class ImportDirectionFinding:
    path: Path
    line: int
    statement: str
    owner_family: str
    violated_rule: str


@dataclass(frozen=True)
class PublicNamingFinding:
    path: Path
    line: int
    name: str
    kind: str
    reason: str


@dataclass(frozen=True)
class ModuleShapeFinding:
    path: Path
    line: int
    name: str
    reason: str


@dataclass(frozen=True)
class StructuralFindings:
    sibling_prefix_findings: tuple[SiblingPrefixFinding, ...]
    import_wrapper_modules: tuple[Path, ...]
    star_import_collectors: tuple[StarImportCollectorFinding, ...]
    gitkeep_placeholders: tuple[Path, ...]
    generic_module_name_findings: tuple[GenericModuleNameFinding, ...]
    duplicate_module_name_findings: tuple[DuplicateModuleNameFinding, ...]


@dataclass(frozen=True)
class ModuleRecord:
    path: Path
    module_name: str | None
    tree: ast.Module
    lines: tuple[str, ...]


@dataclass(frozen=True)
class AuditResults:
    modules: tuple[ModuleRecord, ...]
    sibling_prefix_findings: tuple[SiblingPrefixFinding, ...]
    import_wrapper_modules: tuple[Path, ...]
    star_import_collectors: tuple[StarImportCollectorFinding, ...]
    phase_named_test_directory_findings: tuple[PhaseNamedTestDirectoryFinding, ...]
    phase_named_test_file_findings: tuple[PhaseNamedTestFileFinding, ...]
    phase_named_test_support_api_findings: tuple[PhaseNamedTestSupportApiFinding, ...]
    cross_lane_test_import_findings: tuple[CrossLaneTestImportFinding, ...]
    import_direction_findings: tuple[ImportDirectionFinding, ...]
    import_placement_findings: tuple[ImportPlacementFinding, ...]
    wildcard_import_findings: tuple[WildcardImportFinding, ...]
    todo_comment_findings: tuple[TodoCommentFinding, ...]
    relative_import_depth_findings: tuple[ImportPlacementFinding, ...]
    cross_module_private_access_findings: tuple[CrossModulePrivateAccessFinding, ...]
    gitkeep_placeholders: tuple[Path, ...]
    generic_module_name_findings: tuple[GenericModuleNameFinding, ...]
    duplicate_module_name_findings: tuple[DuplicateModuleNameFinding, ...]
    public_naming_findings: tuple[PublicNamingFinding, ...]
    module_shape_findings: tuple[ModuleShapeFinding, ...]
    cross_module_findings: tuple[tuple[HelperDefinition, ReferenceLocation], ...]
    zero_reference_helpers: tuple[HelperDefinition, ...]
    file_line_violations: tuple[tuple[Path, int], ...]
    function_size_violations: tuple[FunctionSizeViolation, ...]

    @property
    def has_findings(self) -> bool:
        return any(
            (
                self.sibling_prefix_findings,
                self.import_wrapper_modules,
                self.star_import_collectors,
                self.phase_named_test_directory_findings,
                self.phase_named_test_file_findings,
                self.phase_named_test_support_api_findings,
                self.cross_lane_test_import_findings,
                self.import_direction_findings,
                self.import_placement_findings,
                self.wildcard_import_findings,
                self.todo_comment_findings,
                self.relative_import_depth_findings,
                self.cross_module_private_access_findings,
                self.gitkeep_placeholders,
                self.generic_module_name_findings,
                self.duplicate_module_name_findings,
                self.public_naming_findings,
                self.module_shape_findings,
                self.cross_module_findings,
                self.zero_reference_helpers,
                self.file_line_violations,
                self.function_size_violations,
            )
        )
