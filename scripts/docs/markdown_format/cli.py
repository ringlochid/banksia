from __future__ import annotations

import argparse
from collections.abc import Sequence

from .files import ROOT, collect_violations, resolve_paths, write_formatted_files


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)

    paths = resolve_paths(args.paths)
    if args.check:
        violations = collect_violations(paths)
        if violations:
            for violation in violations:
                print(
                    "FORMAT: "
                    f"{violation.path.relative_to(ROOT)}:{violation.line}: "
                    f"{violation.reason}"
                )
            print(f"{len(violations)} maintained markdown file(s) need unwrap formatting.")
            return 1
        print("Markdown unwrap check passed for the selected markdown files.")
        return 0

    changed = write_formatted_files(paths)
    for path in changed:
        print(f"REWROTE: {path.relative_to(ROOT)}")
    print(f"Markdown unwrap write complete. Changed {len(changed)} file(s).")
    return 0
