from __future__ import annotations

from pathlib import Path

from .style_audit_test_support import (
    build_style_audit_settings,
    load_style_audit_namespace,
    write_python_module,
)


def test_style_audit_flags_weak_public_function_verbs(tmp_path: Path) -> None:
    autoclaw_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(autoclaw_root,))
    audit = load_style_audit_namespace()

    write_python_module(
        autoclaw_root / "naming.py",
        "def handle_dispatch() -> None:\n    return None\n",
    )

    findings = audit.scan.run_style_audit(settings).public_naming_findings

    assert len(findings) == 1
    assert findings[0].name == "handle_dispatch"
    assert findings[0].reason == "weak_public_verb"


def test_style_audit_does_not_flag_names_with_weak_verb_prefix_collisions(
    tmp_path: Path,
) -> None:
    autoclaw_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(autoclaw_root,))
    audit = load_style_audit_namespace()

    write_python_module(
        autoclaw_root / "naming.py",
        "def runtime_exception_failure() -> None:\n    return None\n"
        "def checkpoint_id() -> str:\n    return 'x'\n",
    )

    findings = audit.scan.run_style_audit(settings).public_naming_findings

    assert findings == ()


def test_style_audit_flags_non_fact_shaped_public_booleans(tmp_path: Path) -> None:
    autoclaw_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(autoclaw_root,))
    audit = load_style_audit_namespace()

    write_python_module(autoclaw_root / "naming.py", "ready_flag = True\n")

    findings = audit.scan.run_style_audit(settings).public_naming_findings

    assert len(findings) == 1
    assert findings[0].name == "ready_flag"
    assert findings[0].reason == "public_boolean_not_fact_shaped"


def test_style_audit_flags_non_fact_shaped_public_optional_booleans(tmp_path: Path) -> None:
    autoclaw_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(autoclaw_root,))
    audit = load_style_audit_namespace()

    write_python_module(autoclaw_root / "naming.py", "ready_flag: bool | None = None\n")

    findings = audit.scan.run_style_audit(settings).public_naming_findings

    assert len(findings) == 1
    assert findings[0].name == "ready_flag"
    assert findings[0].reason == "public_boolean_not_fact_shaped"


def test_style_audit_flags_non_fact_shaped_public_boolean_parameters(tmp_path: Path) -> None:
    autoclaw_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(autoclaw_root,))
    audit = load_style_audit_namespace()

    write_python_module(
        autoclaw_root / "naming.py",
        "def build_runtime(ready_flag: bool, is_safe: bool = True) -> None:\n    return None\n",
    )

    findings = audit.scan.run_style_audit(settings).public_naming_findings

    assert len(findings) == 1
    assert findings[0].name == "ready_flag"
    assert findings[0].kind == "function-parameter"


def test_style_audit_flags_non_fact_shaped_public_boolean_fields_and_methods(
    tmp_path: Path,
) -> None:
    autoclaw_root = tmp_path / "apps" / "api" / "autoclaw"
    settings = build_style_audit_settings(tmp_path, scan_roots=(autoclaw_root,))
    audit = load_style_audit_namespace()

    write_python_module(
        autoclaw_root / "naming.py",
        "class RuntimeState:\n"
        "    ready_flag: bool = False\n\n"
        "    def __init__(self, should_sync: bool, enabled_flag: bool = False) -> None:\n"
        "        self.enabled_flag = enabled_flag\n\n"
        "    def handle_runtime(self, allow_retry: bool) -> None:\n"
        "        return None\n",
    )

    findings = audit.scan.run_style_audit(settings).public_naming_findings

    assert [(finding.name, finding.kind, finding.reason) for finding in findings] == [
        ("ready_flag", "field", "public_boolean_not_fact_shaped"),
        ("enabled_flag", "constructor-parameter", "public_boolean_not_fact_shaped"),
        ("allow_retry", "method-parameter", "public_boolean_not_fact_shaped"),
        ("handle_runtime", "method", "weak_public_verb"),
    ]


def test_style_audit_flags_private_helper_before_public_entrypoint(tmp_path: Path) -> None:
    app_root = tmp_path / "apps" / "api" / "app"
    settings = build_style_audit_settings(tmp_path, scan_roots=(app_root,))
    audit = load_style_audit_namespace()

    write_python_module(
        app_root / "runtime" / "ordering.py",
        "def _helper() -> None:\n    return None\n\n"
        "def public_entrypoint() -> None:\n    return None\n",
    )

    findings = audit.scan.run_style_audit(settings).module_shape_findings

    assert len(findings) == 1
    assert findings[0].reason == "public_after_private_helper"
    assert findings[0].name == "public_entrypoint"


def test_style_audit_flags_constant_after_function_block(tmp_path: Path) -> None:
    app_root = tmp_path / "apps" / "api" / "app"
    settings = build_style_audit_settings(tmp_path, scan_roots=(app_root,))
    audit = load_style_audit_namespace()

    write_python_module(
        app_root / "runtime" / "ordering.py",
        "def public_entrypoint() -> None:\n    return None\n\nVALUE = 1\n",
    )

    findings = audit.scan.run_style_audit(settings).module_shape_findings

    assert len(findings) == 1
    assert findings[0].reason == "declaration_after_function_block"
    assert findings[0].name == "VALUE"


def test_style_audit_flags_public_entrypoint_after_shared_helper_value_reference(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "apps" / "api" / "app"
    settings = build_style_audit_settings(tmp_path, scan_roots=(app_root,))
    audit = load_style_audit_namespace()

    write_python_module(
        app_root / "main.py",
        "def lifespan() -> object:\n    return object()\n\n"
        'def build_app() -> object:\n    return {"lifespan": lifespan}\n',
    )

    findings = audit.scan.run_style_audit(settings).module_shape_findings

    assert len(findings) == 1
    assert findings[0].reason == "public_after_shared_helper"
    assert findings[0].name == "build_app"


def test_threshold_scan_reports_file_and_function_violations(tmp_path: Path) -> None:
    scan_root = tmp_path / "scan"
    settings = build_style_audit_settings(tmp_path, scan_roots=(scan_root,))
    audit = load_style_audit_namespace()

    write_python_module(scan_root / "huge.py", "".join("value = 1\n" for _ in range(601)))
    long_body = "\n".join(f"    value_{index} = {index}" for index in range(81))
    write_python_module(
        scan_root / "long_function.py",
        f"def long_function() -> None:\n{long_body}\n",
    )

    modules = audit.module_loader.load_modules(settings)
    file_violations = audit.threshold_scan.collect_file_line_violations(modules, settings)
    function_violations = audit.threshold_scan.collect_function_size_violations(
        modules,
        settings.function_size_threshold,
    )

    assert file_violations == ((scan_root / "huge.py", 601),)
    assert len(function_violations) == 1
    assert function_violations[0].name == "long_function"
    assert function_violations[0].non_comment_lines == 82
