from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .style_audit_test_support import (
    build_style_audit_settings,
    load_style_audit_namespace,
    write_python_module,
)


def test_style_audit_flags_autoclaw_modules_that_import_app_outside_approved_shims(
    tmp_path: Path,
) -> None:
    autoclaw_root = tmp_path / "apps" / "api" / "autoclaw"
    app_root = tmp_path / "apps" / "api" / "app"
    settings = build_style_audit_settings(tmp_path, scan_roots=(autoclaw_root, app_root))
    audit = load_style_audit_namespace()

    write_python_module(app_root / "runtime" / "owner.py", "VALUE = 1\n")
    write_python_module(
        autoclaw_root / "consumer.py",
        "from app.runtime.owner import VALUE\n",
    )

    findings = audit.scan.run_style_audit(settings).import_direction_findings

    assert len(findings) == 1
    assert findings[0].path == autoclaw_root / "consumer.py"
    assert findings[0].owner_family == "autoclaw"
    assert findings[0].violated_rule == "autoclaw-consumer-imports-app-owner"


def test_style_audit_allows_phase6_approved_shim_import_direction_exceptions(
    tmp_path: Path,
) -> None:
    autoclaw_root = tmp_path / "apps" / "api" / "autoclaw"
    app_root = tmp_path / "apps" / "api" / "app"
    consumer_path = autoclaw_root / "cli.py"
    settings = replace(
        build_style_audit_settings(tmp_path, scan_roots=(autoclaw_root, app_root)),
        approved_import_direction_exception_modules=frozenset({consumer_path}),
    )
    audit = load_style_audit_namespace()

    write_python_module(app_root / "runtime" / "owner.py", "VALUE = 1\n")
    write_python_module(consumer_path, "from app.runtime.owner import VALUE\n")

    findings = audit.scan.run_style_audit(settings).import_direction_findings

    assert findings == ()


def test_style_audit_flags_legacy_app_shells_that_route_through_legacy_app_owners(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "apps" / "api" / "app"
    shell_path = app_root / "service_managers" / "base.py"
    settings = replace(
        build_style_audit_settings(tmp_path, scan_roots=(app_root,)),
        app_shell_direct_owner_modules=frozenset({shell_path}),
        approved_import_direction_exception_modules=frozenset({shell_path}),
    )
    audit = load_style_audit_namespace()

    write_python_module(
        shell_path,
        "from app.platform.managed_services.contracts import ManagedServiceManager\n",
    )

    findings = audit.scan.run_style_audit(settings).import_direction_findings

    assert len(findings) == 1
    assert findings[0].path == shell_path
    assert findings[0].violated_rule == "legacy-app-shell-imports-legacy-app-owner"


def test_style_audit_allows_legacy_app_shells_that_import_canonical_autoclaw_owners(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "apps" / "api" / "app"
    shell_path = app_root / "service_managers" / "base.py"
    settings = replace(
        build_style_audit_settings(tmp_path, scan_roots=(app_root,)),
        app_shell_direct_owner_modules=frozenset({shell_path}),
        approved_import_direction_exception_modules=frozenset({shell_path}),
    )
    audit = load_style_audit_namespace()

    write_python_module(
        shell_path,
        "from autoclaw.platform.managed_services.contracts import ManagedServiceManager\n",
    )

    findings = audit.scan.run_style_audit(settings).import_direction_findings

    assert findings == ()


def test_style_audit_flags_src_autoclaw_modules_that_import_legacy_autoclaw_owner(
    tmp_path: Path,
) -> None:
    src_root = tmp_path / "apps" / "api" / "src" / "autoclaw"
    legacy_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(src_root, legacy_root))
    audit = load_style_audit_namespace()

    write_python_module(legacy_root / "legacy_only.py", "VALUE = 1\n")
    write_python_module(
        src_root / "consumer.py",
        "from autoclaw.legacy_only import VALUE\n",
    )

    findings = audit.scan.run_style_audit(settings).import_direction_findings

    assert len(findings) == 1
    assert findings[0].path == src_root / "consumer.py"
    assert findings[0].violated_rule == "src-autoclaw-consumer-imports-legacy-owner"


def test_style_audit_flags_src_autoclaw_modules_that_import_legacy_owner_outside_scan_root(
    tmp_path: Path,
) -> None:
    src_root = tmp_path / "apps" / "api" / "src" / "autoclaw"
    legacy_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(src_root,))
    audit = load_style_audit_namespace()

    write_python_module(legacy_root / "legacy_only.py", "VALUE = 1\n")
    write_python_module(
        src_root / "consumer.py",
        "from autoclaw.legacy_only import VALUE\n",
    )

    findings = audit.scan.run_style_audit(settings).import_direction_findings

    assert len(findings) == 1
    assert findings[0].path == src_root / "consumer.py"
    assert findings[0].violated_rule == "src-autoclaw-consumer-imports-legacy-owner"


def test_style_audit_allows_src_autoclaw_modules_that_import_same_tree_owner_with_duplicate_name(
    tmp_path: Path,
) -> None:
    src_root = tmp_path / "apps" / "api" / "src" / "autoclaw"
    legacy_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(src_root,))
    audit = load_style_audit_namespace()

    write_python_module(src_root / "common.py", "VALUE = 1\n")
    write_python_module(legacy_root / "common.py", "VALUE = 2\n")
    write_python_module(src_root / "consumer.py", "from autoclaw.common import VALUE\n")

    findings = audit.scan.run_style_audit(settings).import_direction_findings

    assert findings == ()
