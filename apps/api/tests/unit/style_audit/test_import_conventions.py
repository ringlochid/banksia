from __future__ import annotations

from pathlib import Path

from .style_audit_test_support import (
    build_style_audit_settings,
    load_style_audit_namespace,
    write_python_module,
)


def test_style_audit_flags_top_level_import_placement(tmp_path: Path) -> None:
    settings = build_style_audit_settings(tmp_path)
    module_path = settings.scan_roots[0] / "late_import.py"
    module_path.write_text(
        '"""module docstring"""\n'
        "from __future__ import annotations\n"
        '__all__ = ["value"]\n'
        "value = 1\n"
        "import math\n",
        encoding="utf-8",
    )

    audit = load_style_audit_namespace()
    results = audit.scan.run_style_audit(settings)

    assert len(results.import_placement_findings) == 1
    finding = results.import_placement_findings[0]
    assert finding.path == module_path
    assert finding.line == 5
    assert finding.statement == "import math"


def test_style_audit_ignores_wildcard_imports_in_package_exports(tmp_path: Path) -> None:
    settings = build_style_audit_settings(tmp_path)
    package_dir = settings.scan_roots[0] / "pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        "from .helpers import *\n",
        encoding="utf-8",
    )
    (package_dir / "helpers.py").write_text("VALUE = 1\n", encoding="utf-8")

    audit = load_style_audit_namespace()
    results = audit.scan.run_style_audit(settings)

    assert results.wildcard_import_findings == ()


def test_style_audit_flags_wildcard_imports_outside_export_surfaces(tmp_path: Path) -> None:
    settings = build_style_audit_settings(tmp_path)
    module_path = settings.scan_roots[0] / "consumer.py"
    module_path.write_text("from helpers import *\n", encoding="utf-8")
    (settings.scan_roots[0] / "helpers.py").write_text("VALUE = 1\n", encoding="utf-8")

    audit = load_style_audit_namespace()
    results = audit.scan.run_style_audit(settings)

    assert len(results.wildcard_import_findings) == 1
    finding = results.wildcard_import_findings[0]
    assert finding.path == module_path
    assert finding.line == 1
    assert finding.source == "helpers"


def test_style_audit_flags_todo_without_owner_or_removal_detail(tmp_path: Path) -> None:
    settings = build_style_audit_settings(tmp_path)
    module_path = settings.scan_roots[0] / "todo_example.py"
    module_path.write_text("# TODO tighten this later\nvalue = 1\n", encoding="utf-8")

    audit = load_style_audit_namespace()
    results = audit.scan.run_style_audit(settings)

    assert len(results.todo_comment_findings) == 1
    finding = results.todo_comment_findings[0]
    assert finding.path == module_path
    assert finding.line == 1
    assert finding.text == "# TODO tighten this later"


def test_style_audit_accepts_todo_with_phase_detail(tmp_path: Path) -> None:
    settings = build_style_audit_settings(tmp_path)
    (settings.scan_roots[0] / "todo_ok.py").write_text(
        "# TODO phase 5b: remove after packaging cutover\nvalue = 1\n",
        encoding="utf-8",
    )

    audit = load_style_audit_namespace()
    results = audit.scan.run_style_audit(settings)

    assert results.todo_comment_findings == ()


def test_convention_scan_flags_deep_relative_imports_outside_tests(tmp_path: Path) -> None:
    app_root = tmp_path / "apps" / "api" / "app" / "runtime"
    test_root = tmp_path / "apps" / "api" / "tests" / "unit"
    settings = build_style_audit_settings(tmp_path, scan_roots=(app_root, test_root))
    audit = load_style_audit_namespace()

    write_python_module(app_root / "deep_relative.py", "from ...helpers import thing\n")
    write_python_module(test_root / "test_relative.py", "from ...helpers import thing\n")

    findings = audit.scan.run_style_audit(settings).relative_import_depth_findings

    assert len(findings) == 1
    assert findings[0].path == app_root / "deep_relative.py"
    assert findings[0].statement == "from ...helpers import thing"
