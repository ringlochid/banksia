from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from .style_audit_test_support import (
    build_empty_audit_results,
    build_results_with_findings,
    build_style_audit_settings,
    load_style_audit_namespace,
    write_python_module,
)


def test_render_audit_report_includes_phase6_sections(tmp_path: Path) -> None:
    audit = load_style_audit_namespace()
    settings = build_style_audit_settings(tmp_path)
    report = audit.report.render_audit_report(
        build_results_with_findings(audit.models, tmp_path),
        settings,
    )

    assert "Execution STYLE audit" in report
    assert "Import-direction findings" in report
    assert "Module-shape findings" in report
    assert "Public naming findings" in report
    assert "Duplicate module-name ownership findings" in report
    assert "Sibling-prefix layout families" in report
    assert "Phase-numbered test directories" in report
    assert "Phase-numbered test filenames" in report
    assert "Phase-coded test support APIs" in report
    assert "Cross-lane test imports" in report
    assert "Top-level import placement violations" in report
    assert "Wildcard imports outside deliberate export surfaces" in report
    assert "TODO comments missing owner or removal detail" in report
    assert "Cross-module private-helper imports" in report
    assert "Function-size threshold violations" in report


def test_render_audit_report_renders_no_findings_footer(tmp_path: Path) -> None:
    audit = load_style_audit_namespace()
    report = audit.report.render_audit_report(
        build_empty_audit_results(audit.models, tmp_path),
        build_style_audit_settings(tmp_path),
    )

    assert "No findings." in report
    assert "Rerun with `--fail-on-findings`" in report


def test_cli_main_respects_fail_on_findings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    audit = load_style_audit_namespace()
    settings = build_style_audit_settings(tmp_path)
    results = audit.models.AuditResults(
        **{
            **build_empty_audit_results(audit.models, tmp_path).__dict__,
            "file_line_violations": ((tmp_path / "big.py", 700),),
        }
    )
    monkeypatch.setattr(audit.cli, "build_audit_settings", lambda: settings)
    monkeypatch.setattr(audit.cli, "run_style_audit", lambda _settings: results)
    monkeypatch.setattr(audit.cli, "render_audit_report", lambda *_args: "REPORT\n")

    assert audit.cli.main([]) == 0
    assert capsys.readouterr().out == "REPORT\n"
    assert audit.cli.main(["--fail-on-findings"]) == 1
    assert capsys.readouterr().out == "REPORT\n"


def test_cli_main_passes_explicit_scan_roots(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    audit = load_style_audit_namespace()
    scan_root = tmp_path / "apps" / "api" / "app"
    settings = build_style_audit_settings(tmp_path, scan_roots=(scan_root,))
    captured_scan_roots: dict[str, tuple[Path, ...]] = {}

    def build_settings_for_scan_roots(
        *,
        scan_roots: tuple[Path, ...] | None = None,
    ) -> Any:
        captured_scan_roots["value"] = scan_roots or ()
        return settings

    monkeypatch.setattr(audit.cli, "_validated_scan_roots", lambda *_args: (scan_root,))
    monkeypatch.setattr(audit.cli, "build_audit_settings", build_settings_for_scan_roots)
    monkeypatch.setattr(
        audit.cli,
        "run_style_audit",
        lambda _settings: build_empty_audit_results(audit.models, tmp_path),
    )
    monkeypatch.setattr(audit.cli, "render_audit_report", lambda *_args: "REPORT\n")
    write_python_module(scan_root / "sample.py", "value = 1\n")

    assert audit.cli.main(["--scan-root", "apps/api/app"]) == 0
    assert captured_scan_roots["value"] == (scan_root,)
    assert capsys.readouterr().out == "REPORT\n"


def test_cli_main_accepts_python_file_scan_roots(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    audit = load_style_audit_namespace()
    scan_root_argument = "apps/api/tests/unit/style_audit/test_report_and_cli.py"
    scan_root = tmp_path / scan_root_argument
    write_python_module(scan_root, "value = 1\n")
    settings = build_style_audit_settings(tmp_path, scan_roots=(scan_root,))
    captured_scan_roots: dict[str, tuple[Path, ...]] = {}

    def build_settings_for_scan_roots(
        *,
        scan_roots: tuple[Path, ...] | None = None,
    ) -> Any:
        captured_scan_roots["value"] = scan_roots or ()
        return settings

    monkeypatch.setattr(audit.cli, "_validated_scan_roots", lambda *_args: (scan_root,))
    monkeypatch.setattr(audit.cli, "build_audit_settings", build_settings_for_scan_roots)
    monkeypatch.setattr(
        audit.cli,
        "run_style_audit",
        lambda _settings: build_empty_audit_results(audit.models, tmp_path),
    )
    monkeypatch.setattr(audit.cli, "render_audit_report", lambda *_args: "REPORT\n")

    assert audit.cli.main(["--scan-root", scan_root_argument]) == 0
    assert captured_scan_roots["value"] == (scan_root,)
    assert capsys.readouterr().out == "REPORT\n"


def test_cli_main_import_interface_gate_ignores_threshold_only_findings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    audit = load_style_audit_namespace()
    settings = build_style_audit_settings(tmp_path)
    results = audit.models.AuditResults(
        **{
            **build_empty_audit_results(audit.models, tmp_path).__dict__,
            "file_line_violations": ((tmp_path / "big.py", 700),),
        }
    )

    monkeypatch.setattr(audit.cli, "build_audit_settings", lambda: settings)
    monkeypatch.setattr(audit.cli, "run_style_audit", lambda _settings: results)
    monkeypatch.setattr(audit.cli, "render_audit_report", lambda *_args: "REPORT\n")

    assert audit.cli.main(["--gate", "import-interface", "--fail-on-findings"]) == 0
    assert capsys.readouterr().out == "REPORT\n"


def test_cli_main_import_interface_gate_fails_on_duplicate_module_ownership(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    audit = load_style_audit_namespace()
    settings = build_style_audit_settings(tmp_path)
    results = audit.models.AuditResults(
        **{
            **build_empty_audit_results(audit.models, tmp_path).__dict__,
            "duplicate_module_name_findings": (
                audit.models.DuplicateModuleNameFinding(
                    module_name="autoclaw.common",
                    paths=(
                        tmp_path / "apps" / "api" / "autoclaw" / "common.py",
                        tmp_path / "apps" / "api" / "src" / "autoclaw" / "common.py",
                    ),
                ),
            ),
        }
    )

    monkeypatch.setattr(audit.cli, "build_audit_settings", lambda: settings)
    monkeypatch.setattr(audit.cli, "run_style_audit", lambda _settings: results)
    monkeypatch.setattr(audit.cli, "render_audit_report", lambda *_args: "REPORT\n")

    assert audit.cli.main(["--gate", "import-interface", "--fail-on-findings"]) == 1
    assert capsys.readouterr().out == "REPORT\n"
