from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence

from .discovery import ROOT
from .models import ContractReport
from .validator import build_contract_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "inventory"), nargs="?", default="validate")
    args = parser.parse_args(argv)
    report = build_contract_report(ROOT)
    if args.command == "inventory":
        print_inventory(report)
        return 0
    return print_validation(report)


def print_validation(report: ContractReport) -> int:
    if not report.findings:
        print(f"Docs contract validation passed for {len(report.files)} Markdown files.")
        return 0
    for issue in report.findings:
        print(f"ERROR [{issue.category}] {issue.path.as_posix()}:{issue.line}: {issue.message}")
    print(f"Docs contract validation found {len(report.findings)} issue(s).")
    return 1


def print_inventory(report: ContractReport) -> None:
    print(f"Maintained Markdown files: {len(report.files)}")
    print("Front doors:")
    for front_door in report.front_doors:
        print(f"- {front_door.label}: {front_door.entrypoint.relative_to(report.root)}")
    print("Findings by category:")
    counts = Counter(finding.category for finding in report.findings)
    if not counts:
        print("- none")
        return
    for category, count in sorted(counts.items()):
        print(f"- {category}: {count}")


if __name__ == "__main__":
    raise SystemExit(main())
