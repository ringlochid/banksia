from __future__ import annotations

from pathlib import Path

from .models import AuditSettings

ROOT = Path(__file__).resolve().parents[3]
APPS_API_ROOT = ROOT / "apps" / "api"
APPS_API_TESTS_ROOT = APPS_API_ROOT / "tests"
AUTOCLAW_SRC_PACKAGE_ROOT = APPS_API_ROOT / "src" / "autoclaw"
SCRIPTS_DOCS_ROOT = ROOT / "scripts" / "docs"
FILE_SPLIT_REVIEW_THRESHOLD = 600
FILE_NO_GROWTH_THRESHOLD = 600
FUNCTION_SIZE_THRESHOLD = 80
SIBLING_PREFIX_THRESHOLD = 3
DISALLOWED_GENERIC_MODULE_NAMES = frozenset(
    {
        "helpers",
        "lookup",
        "misc",
        "models",
        "resources",
        "service",
        "shared",
        "support",
        "utils",
    }
)
INEXACT_PACKAGE_NAMES = frozenset(
    {
        "api",
        "compiler",
        "core",
        "db",
        "definitions",
        "models",
        "registry",
        "runtime",
        "schemas",
        "services",
        "tests",
    }
)


def _style_audit_scan_roots() -> tuple[Path, ...]:
    return _existing_roots(
        SCRIPTS_DOCS_ROOT,
        AUTOCLAW_SRC_PACKAGE_ROOT,
        APPS_API_TESTS_ROOT / "e2e",
        APPS_API_TESTS_ROOT / "helpers",
        APPS_API_TESTS_ROOT / "integration",
        APPS_API_TESTS_ROOT / "unit",
    )


def _existing_roots(*paths: Path) -> tuple[Path, ...]:
    return tuple(path for path in paths if path.exists())


def _existing_paths(*paths: Path) -> frozenset[Path]:
    return frozenset(path for path in paths if path.exists())


def _existing_public_naming_exceptions(
    *exceptions: tuple[Path, str],
) -> frozenset[tuple[Path, str]]:
    return frozenset((path, name) for path, name in exceptions if path.exists())


def _app_shell_direct_owner_modules() -> frozenset[Path]:
    return frozenset()


def _src_owner_wrapper_modules() -> frozenset[Path]:
    return _existing_paths(
        AUTOCLAW_SRC_PACKAGE_ROOT / "interfaces" / "http" / "router.py",
    )


def _approved_wrapper_modules() -> frozenset[Path]:
    return _src_owner_wrapper_modules()


def _approved_wrapper_directories() -> frozenset[Path]:
    return frozenset()


def _approved_duplicate_module_name_paths() -> frozenset[Path]:
    return frozenset()


def _src_runtime_import_exceptions() -> frozenset[Path]:
    return frozenset()


def _canonical_contract_naming_exceptions() -> frozenset[tuple[Path, str]]:
    return _existing_public_naming_exceptions(
        (ROOT / "apps/api/src/autoclaw/config.py", "enabled"),
        (ROOT / "apps/api/src/autoclaw/config.py", "value_is_complex"),
        (
            ROOT / "apps/api/src/autoclaw/integrations/openclaw/gateway/adapter.py",
            "check",
        ),
        (
            ROOT / "apps/api/src/autoclaw/runtime/contracts/operation_failure.py",
            "ok",
        ),
        (
            ROOT / "apps/api/src/autoclaw/runtime/contracts/operation_failure.py",
            "retryable",
        ),
        (
            ROOT / "apps/api/src/autoclaw/runtime/work_plan/contracts.py",
            "changed",
        ),
    )


def _approved_public_naming_exceptions() -> frozenset[tuple[Path, str]]:
    return _canonical_contract_naming_exceptions()


def _approved_import_direction_exception_modules() -> frozenset[Path]:
    return _src_runtime_import_exceptions()


def _public_naming_scan_roots() -> tuple[Path, ...]:
    return _existing_roots(AUTOCLAW_SRC_PACKAGE_ROOT)


def _public_naming_extra_modules() -> frozenset[Path]:
    return frozenset()


def _module_shape_scan_roots() -> tuple[Path, ...]:
    return _existing_roots(AUTOCLAW_SRC_PACKAGE_ROOT)


def build_audit_settings(
    *,
    scan_roots: tuple[Path, ...] | None = None,
    excluded_paths: frozenset[Path] | None = None,
) -> AuditSettings:
    return AuditSettings(
        root=ROOT,
        apps_api_root=APPS_API_ROOT,
        scan_roots=scan_roots or _style_audit_scan_roots(),
        excluded_paths=excluded_paths or frozenset(),
        file_split_review_threshold=FILE_SPLIT_REVIEW_THRESHOLD,
        file_no_growth_threshold=FILE_NO_GROWTH_THRESHOLD,
        function_size_threshold=FUNCTION_SIZE_THRESHOLD,
        sibling_prefix_threshold=SIBLING_PREFIX_THRESHOLD,
        approved_wrapper_modules=_approved_wrapper_modules(),
        approved_wrapper_directories=_approved_wrapper_directories(),
        approved_duplicate_module_name_paths=_approved_duplicate_module_name_paths(),
        app_shell_direct_owner_modules=_app_shell_direct_owner_modules(),
        approved_import_direction_exception_modules=(
            _approved_import_direction_exception_modules()
        ),
        approved_public_naming_exceptions=_approved_public_naming_exceptions(),
        disallowed_generic_module_names=DISALLOWED_GENERIC_MODULE_NAMES,
        inexact_package_names=INEXACT_PACKAGE_NAMES,
        public_naming_scan_roots=_public_naming_scan_roots(),
        public_naming_extra_modules=_public_naming_extra_modules(),
        module_shape_scan_roots=_module_shape_scan_roots(),
        module_shape_excluded_modules=frozenset({AUTOCLAW_SRC_PACKAGE_ROOT / "main.py"}),
    )
