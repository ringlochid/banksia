from __future__ import annotations

import argparse
from pathlib import Path

from .config import ROOT, build_audit_settings
from .models import AuditResults
from .module_loader import iter_python_files
from .report import render_audit_report
from .scan import run_style_audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="exit non-zero when the audit reports findings",
    )
    parser.add_argument(
        "--gate",
        choices=("full", "import-interface"),
        default="full",
        help="select which finding family should control fail-on-findings",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        default=[],
        help=(
            "limit scanning to one repo-relative directory or Python file; "
            "repeat for multiple roots"
        ),
    )
    args = parser.parse_args(argv)

    explicit_scan_roots = _validated_scan_roots(parser, tuple(args.scan_root))
    settings = (
        build_audit_settings(scan_roots=explicit_scan_roots)
        if explicit_scan_roots
        else build_audit_settings()
    )
    if args.scan_root and not iter_python_files(settings):
        parser.error("explicit --scan-root selection resolved zero Python modules")

    results = run_style_audit(settings)
    print(render_audit_report(results, settings), end="")
    return 1 if args.fail_on_findings and _selected_gate_has_findings(results, args.gate) else 0


def _validated_scan_roots(
    parser: argparse.ArgumentParser,
    raw_scan_roots: tuple[str, ...],
) -> tuple[Path, ...]:
    validated: list[Path] = []
    for raw_scan_root in raw_scan_roots:
        candidate = (ROOT / raw_scan_root).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            parser.error(f"--scan-root must stay inside the repo: {raw_scan_root}")
        if not candidate.exists():
            parser.error(f"--scan-root does not exist: {raw_scan_root}")
        if candidate.is_file() and candidate.suffix != ".py":
            parser.error(f"--scan-root file must be a Python module: {raw_scan_root}")
        if not candidate.is_dir() and not candidate.is_file():
            parser.error(f"--scan-root must point to a directory or Python file: {raw_scan_root}")
        validated.append(candidate)
    return tuple(validated)


def _selected_gate_has_findings(results: AuditResults, gate: str) -> bool:
    if gate == "full":
        return bool(results.has_findings)
    return any(
        (
            results.import_direction_findings,
            results.import_placement_findings,
            results.wildcard_import_findings,
            results.relative_import_depth_findings,
            results.import_wrapper_modules,
            results.duplicate_module_name_findings,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
