from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .style_audit_test_support import (
    build_style_audit_settings,
    load_style_audit_namespace,
    write_python_module,
)


def test_module_loader_skips_pycache_and_resolves_module_names(tmp_path: Path) -> None:
    scan_root = tmp_path / "scan"
    included_path = scan_root / "included.py"
    excluded_path = scan_root / "excluded.py"
    pycache_path = scan_root / "__pycache__" / "ignored.py"
    write_python_module(included_path, "value = 1\n")
    write_python_module(excluded_path, "value = 2\n")
    write_python_module(pycache_path, "value = 3\n")

    settings = build_style_audit_settings(
        tmp_path,
        scan_roots=(scan_root,),
        excluded_paths=frozenset({excluded_path}),
    )
    audit = load_style_audit_namespace()

    assert audit.module_loader.iter_python_files(settings) == [included_path]

    app_module_path = tmp_path / "apps" / "api" / "app" / "runtime" / "sample.py"
    docs_module_path = tmp_path / "scripts" / "docs" / "tooling" / "example.py"
    write_python_module(app_module_path, "value = 1\n")
    write_python_module(docs_module_path, "value = 1\n")

    assert (
        audit.module_loader.module_name_for_path(app_module_path, settings) == "app.runtime.sample"
    )
    assert audit.module_loader.module_name_for_path(docs_module_path, settings) == "tooling.example"
    assert audit.module_loader.dotted_module_name(Path("pkg/__init__.py")) == "pkg"
    assert (
        audit.module_loader.resolve_module_name("pkg.sub.consumer", "source", 1) == "pkg.sub.source"
    )
    assert (
        audit.module_loader.resolve_module_name(
            "pkg.sub.consumer",
            "source",
            1,
            current_path=Path("pkg/sub/consumer.py"),
        )
        == "pkg.sub.source"
    )
    assert (
        audit.module_loader.resolve_module_name(
            "pkg.sub",
            "source",
            1,
            current_path=Path("pkg/sub/__init__.py"),
        )
        == "pkg.sub.source"
    )
    assert audit.module_loader.resolve_module_name("pkg.consumer", None, 1) == "pkg"
    assert audit.module_loader.resolve_module_name("pkg", "source", 2) is None
    assert audit.module_loader.count_non_comment_lines(("", "# x", "value = 1"), 1, 3) == 1


def test_module_loader_dedupes_overlapping_scan_roots(tmp_path: Path) -> None:
    runtime_root = tmp_path / "apps" / "api" / "app" / "runtime"
    child_root = runtime_root / "nested"
    module_path = child_root / "sample.py"
    write_python_module(module_path, "value = 1\n")
    settings = build_style_audit_settings(tmp_path, scan_roots=(runtime_root, child_root))
    audit = load_style_audit_namespace()

    assert audit.module_loader.iter_python_files(settings) == [module_path]


def test_module_loader_accepts_python_file_scan_roots(tmp_path: Path) -> None:
    module_path = tmp_path / "scan.py"
    write_python_module(module_path, "value = 1\n")
    settings = build_style_audit_settings(tmp_path, scan_roots=(module_path,))
    audit = load_style_audit_namespace()

    assert audit.module_loader.iter_python_files(settings) == [module_path]


def test_build_audit_settings_exposes_phase6_wrapper_and_direction_scopes() -> None:
    audit = load_style_audit_namespace()
    settings = audit.config.build_audit_settings()

    expected_roots = {
        Path("scripts/docs"),
        Path("apps/api/src/autoclaw"),
        Path("apps/api/tests/e2e"),
        Path("apps/api/tests/helpers"),
        Path("apps/api/tests/integration"),
        Path("apps/api/tests/unit"),
    }
    assert {path.relative_to(settings.root) for path in settings.scan_roots} == expected_roots
    assert settings.excluded_paths == frozenset()
    approved_wrappers = {
        path.relative_to(settings.root) for path in settings.approved_wrapper_modules
    }
    assert approved_wrappers == {Path("apps/api/src/autoclaw/interfaces/http/router.py")}
    assert all(
        not str(path).startswith("apps/api/app/") and not str(path).startswith("apps/api/autoclaw/")
        for path in approved_wrappers
    )
    assert all((settings.root / path).exists() for path in approved_wrappers)
    assert settings.approved_wrapper_directories == frozenset()
    duplicate_name_exceptions = {
        path.relative_to(settings.root) for path in settings.approved_duplicate_module_name_paths
    }
    assert duplicate_name_exceptions == set()
    direction_exceptions = {
        path.relative_to(settings.root)
        for path in settings.approved_import_direction_exception_modules
    }
    assert direction_exceptions == set()
    app_shell_direct_owner_modules = {
        path.relative_to(settings.root) for path in settings.app_shell_direct_owner_modules
    }
    assert app_shell_direct_owner_modules == set()
    public_naming_roots = {
        path.relative_to(settings.root) for path in settings.public_naming_scan_roots
    }
    assert public_naming_roots == {Path("apps/api/src/autoclaw")}
    assert settings.public_naming_extra_modules == frozenset()
    module_shape_roots = {
        path.relative_to(settings.root) for path in settings.module_shape_scan_roots
    }
    assert module_shape_roots == {Path("apps/api/src/autoclaw")}
    public_naming_exceptions = {
        (path.relative_to(settings.root), name)
        for path, name in settings.approved_public_naming_exceptions
    }
    assert (
        Path("apps/api/src/autoclaw/integrations/openclaw/gateway/adapter.py"),
        "check_compatibility",
    ) in public_naming_exceptions
    assert (Path("apps/api/src/autoclaw/config.py"), "value_is_complex") in (
        public_naming_exceptions
    )
    assert (
        Path("apps/api/src/autoclaw/runtime/replan/defaults.py"),
        "apply_child_defaults",
    ) in public_naming_exceptions
    assert (
        Path("apps/api/src/autoclaw/runtime/watchdog/manager.py"),
        "stop_requested",
    ) in public_naming_exceptions
    assert all(
        (settings.root / path).exists()
        and not str(path).startswith("apps/api/app/")
        and not str(path).startswith("apps/api/autoclaw/")
        for path, _name in public_naming_exceptions
    )


def test_layout_scan_collects_structural_findings(tmp_path: Path) -> None:
    tests_root = tmp_path / "apps" / "api" / "tests" / "unit"
    runtime_root = tmp_path / "apps" / "api" / "app" / "runtime"
    routes_root = tmp_path / "apps" / "api" / "app" / "api" / "routes"
    settings = build_style_audit_settings(
        tmp_path,
        scan_roots=(tests_root, runtime_root, routes_root),
    )
    audit = load_style_audit_namespace()

    write_python_module(tests_root / "test_alpha_one.py", "value = 1\n")
    write_python_module(tests_root / "test_alpha_two.py", "value = 2\n")
    write_python_module(tests_root / "test_alpha_three.py", "value = 3\n")
    write_python_module(tests_root / "test_star.py", "from app.runtime.source import *\n")
    write_python_module(runtime_root / "wrapper.py", '"""wrapper"""\nimport math\n')
    write_python_module(runtime_root / "helpers.py", "value = 1\n")
    write_python_module(routes_root / "allowed.py", "import math\n")
    (runtime_root / ".gitkeep").write_text("", encoding="utf-8")

    modules = audit.module_loader.load_modules(settings)
    findings = audit.layout_scan.collect_structural_findings(modules, settings)

    assert len(findings.sibling_prefix_findings) == 1
    assert findings.sibling_prefix_findings[0].prefix == "alpha"
    assert findings.import_wrapper_modules == (runtime_root / "wrapper.py",)
    assert len(findings.star_import_collectors) == 1
    assert findings.star_import_collectors[0].path == tests_root / "test_star.py"
    assert findings.gitkeep_placeholders == (runtime_root / ".gitkeep",)
    assert len(findings.generic_module_name_findings) == 1
    assert findings.generic_module_name_findings[0].path == runtime_root / "helpers.py"


def test_layout_scan_respects_configured_wrapper_directories_without_allowlisting_new_wrappers(
    tmp_path: Path,
) -> None:
    routes_root = tmp_path / "apps" / "api" / "app" / "api" / "routes"
    runtime_root = tmp_path / "apps" / "api" / "app" / "runtime"
    settings = replace(
        build_style_audit_settings(
            tmp_path,
            scan_roots=(routes_root, runtime_root),
        ),
        approved_wrapper_directories=frozenset({routes_root}),
    )
    audit = load_style_audit_namespace()

    write_python_module(routes_root / "allowed.py", "import math\n")
    write_python_module(runtime_root / "blocked.py", "import math\n")

    modules = audit.module_loader.load_modules(settings)
    findings = audit.layout_scan.collect_structural_findings(modules, settings)

    assert findings.import_wrapper_modules == (runtime_root / "blocked.py",)


def test_layout_scan_flags_alias_reexport_wrapper_modules(tmp_path: Path) -> None:
    runtime_root = tmp_path / "apps" / "api" / "app" / "runtime"
    settings = build_style_audit_settings(tmp_path, scan_roots=(runtime_root,))
    audit = load_style_audit_namespace()

    alias_wrapper = runtime_root / "alias_wrapper.py"
    write_python_module(
        alias_wrapper,
        "from app.runtime.control import failures as legacy_failures\n"
        "RuntimeOperationError = legacy_failures.RuntimeOperationError\n"
        '__all__ = ["RuntimeOperationError"]\n',
    )

    modules = audit.module_loader.load_modules(settings)
    findings = audit.layout_scan.collect_structural_findings(modules, settings)

    assert findings.import_wrapper_modules == (alias_wrapper,)


def test_layout_scan_requires_exact_allowlist_for_alias_wrapper_shells(tmp_path: Path) -> None:
    runtime_root = tmp_path / "apps" / "api" / "app" / "runtime"
    allowed_alias = runtime_root / "allowed_alias.py"
    blocked_alias = runtime_root / "blocked_alias.py"
    settings = replace(
        build_style_audit_settings(tmp_path, scan_roots=(runtime_root,)),
        approved_wrapper_modules=frozenset({allowed_alias}),
    )
    audit = load_style_audit_namespace()

    module_content = (
        "from app.runtime.control import failures as legacy_failures\n"
        "RuntimeOperationError = legacy_failures.RuntimeOperationError\n"
        '__all__ = ["RuntimeOperationError"]\n'
    )
    write_python_module(allowed_alias, module_content)
    write_python_module(blocked_alias, module_content)

    modules = audit.module_loader.load_modules(settings)
    findings = audit.layout_scan.collect_structural_findings(modules, settings)

    assert findings.import_wrapper_modules == (blocked_alias,)


def test_layout_scan_flags_duplicate_module_name_ownership_across_legacy_and_src_autoclaw(
    tmp_path: Path,
) -> None:
    legacy_root = tmp_path / "apps" / "api" / "autoclaw"
    src_root = tmp_path / "apps" / "api" / "src" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(legacy_root, src_root))
    audit = load_style_audit_namespace()

    write_python_module(legacy_root / "common.py", "VALUE = 1\n")
    write_python_module(src_root / "common.py", "VALUE = 2\n")

    modules = audit.module_loader.load_modules(settings)
    findings = audit.layout_scan.collect_structural_findings(modules, settings)

    assert len(findings.duplicate_module_name_findings) == 1
    finding = findings.duplicate_module_name_findings[0]
    assert finding.module_name == "autoclaw.common"
    assert finding.paths == (legacy_root / "common.py", src_root / "common.py")


def test_layout_scan_ignores_approved_duplicate_module_name_shims(tmp_path: Path) -> None:
    legacy_root = tmp_path / "apps" / "api" / "autoclaw"
    src_root = tmp_path / "apps" / "api" / "src" / "autoclaw"
    legacy_main = legacy_root / "main.py"
    src_main = src_root / "main.py"
    settings = replace(
        build_style_audit_settings(tmp_path, scan_roots=(legacy_root, src_root)),
        approved_duplicate_module_name_paths=frozenset({legacy_main, src_main}),
    )
    audit = load_style_audit_namespace()

    write_python_module(legacy_main, "from app.main import app\n")
    write_python_module(src_main, "from app.main import app\n")

    modules = audit.module_loader.load_modules(settings)
    findings = audit.layout_scan.collect_structural_findings(modules, settings)

    assert findings.duplicate_module_name_findings == ()


def test_test_structure_scan_flags_phase_directories_files_support_apis_and_cross_lane_imports(
    tmp_path: Path,
) -> None:
    tests_root = tmp_path / "apps" / "api" / "tests"
    settings = build_style_audit_settings(
        tmp_path,
        scan_roots=(tests_root / "unit", tests_root / "integration", tests_root / "e2e"),
    )
    audit = load_style_audit_namespace()

    write_python_module(
        tests_root / "unit" / "test_cli.py",
        "from tests.integration.public_surfaces.support import build_payload\n",
    )
    write_python_module(tests_root / "integration" / "phase5a" / "support.py", "value = 1\n")
    write_python_module(
        tests_root / "integration" / "public_surfaces" / "support.py",
        "class Phase5aHttpContext:\n    pass\n\n"
        "async def phase5a_http_context() -> None:\n    return None\n",
    )
    write_python_module(
        tests_root / "e2e" / "workflows" / "test_root_cli_phase5a.py",
        "value = 1\n",
    )

    modules = audit.module_loader.load_modules(settings)
    phase_directory_findings = (
        audit.test_structure_scan.collect_phase_named_test_directory_findings(
            modules,
            tests_root,
        )
    )
    phase_file_findings = audit.test_structure_scan.collect_phase_named_test_file_findings(
        modules,
        tests_root,
    )
    phase_support_api_findings = (
        audit.test_structure_scan.collect_phase_named_test_support_api_findings(
            modules,
            tests_root,
        )
    )
    cross_lane_findings = audit.test_structure_scan.collect_cross_lane_test_import_findings(
        modules,
        tests_root,
    )

    assert [finding.phase_directory_name for finding in phase_directory_findings] == ["phase5a"]
    assert [finding.path.name for finding in phase_file_findings] == ["test_root_cli_phase5a.py"]
    assert [finding.name for finding in phase_support_api_findings] == [
        "Phase5aHttpContext",
        "phase5a_http_context",
    ]
    assert len(cross_lane_findings) == 1
    assert cross_lane_findings[0].consumer_lane == "unit"
    assert cross_lane_findings[0].imported_lane == "integration"


def test_private_helper_scan_detects_direct_and_attribute_imports(tmp_path: Path) -> None:
    runtime_root = tmp_path / "apps" / "api" / "app" / "runtime"
    settings = build_style_audit_settings(tmp_path, scan_roots=(runtime_root,))
    audit = load_style_audit_namespace()

    write_python_module(
        runtime_root / "source.py",
        "def _helper() -> int:\n    return 1\n\n\ndef _unused() -> int:\n    return 2\n",
    )
    write_python_module(
        runtime_root / "consumer_direct.py",
        "from app.runtime.source import _helper\n\nvalue = _helper()\n",
    )
    write_python_module(
        runtime_root / "consumer_attr.py",
        "import app.runtime.source as source\n\nvalue = source._helper()\n",
    )

    modules = audit.module_loader.load_modules(settings)
    module_name_to_path = {
        module.module_name: module.path for module in modules if module.module_name is not None
    }
    helpers, helpers_by_path = audit.private_helpers.collect_private_helpers(modules)
    references = audit.private_helpers.collect_same_module_references(
        helpers,
        helpers_by_path,
        modules,
    )
    findings = audit.private_helpers.collect_cross_module_references(
        helpers_by_path,
        module_name_to_path,
        modules,
        references,
    )
    access_findings = audit.private_helpers.collect_cross_module_private_access_findings(
        helpers_by_path,
        module_name_to_path,
        modules,
    )
    zero_reference = audit.private_helpers.zero_reference_helpers(helpers, references)

    assert [location.kind for _, location in findings] == ["module-attribute", "direct-import"]
    assert [finding.kind for finding in access_findings] == ["module-attribute", "direct-import"]
    assert [helper.name for helper in zero_reference] == ["_unused"]
