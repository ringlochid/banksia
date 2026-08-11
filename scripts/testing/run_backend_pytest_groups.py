from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src"

SUITES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "integration": (
        (
            "workflow-and-runtime-schema",
            (
                "tests/integration/runtime_schema_contract",
                "tests/integration/test_readyz_real_db.py",
                "tests/integration/test_startup_schema_guard.py",
                "tests/integration/test_db_upgrade_db.py",
                "tests/integration/test_db_reset_db.py",
            ),
        ),
        ("bootstrap", ("tests/integration/bootstrap",)),
        ("runtime", ("tests/integration/runtime",)),
        ("mcp", ("tests/integration/mcp",)),
        ("public-surfaces", ("tests/integration/public_surfaces",)),
        ("operator", ("tests/integration/operator",)),
        ("workflow-authoring", ("tests/integration/workflows",)),
    ),
    "e2e-bounded": (
        ("workflow-bounded", ("tests/e2e/workflows/test_published_workflow_start.py",)),
    ),
    "e2e-reviewed": (
        ("workflow-reviewed", ("tests/e2e/workflows/test_recursive_wave_result.py",)),
    ),
    "e2e-staged": (("workflow-staged", ("tests/e2e/workflows/test_wait_watchdog_recovery.py",)),),
}


def main(arguments: Sequence[str] | None = None) -> int:
    selected = tuple(sys.argv[1:] if arguments is None else arguments)
    if len(selected) != 1:
        raise SystemExit(_usage())
    command = selected[0]
    if command == "list":
        for suite in ("integration", "e2e-bounded", "e2e-reviewed", "e2e-staged"):
            print(f"\n[{suite}]")
            for label, paths in SUITES[suite]:
                print(f"{label}: {' '.join(paths)}")
        return 0
    suites = ("e2e-bounded", "e2e-reviewed", "e2e-staged") if command == "e2e-all" else (command,)
    if any(suite not in SUITES for suite in suites):
        raise SystemExit(_usage())
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(SOURCE_ROOT), environment.get("PYTHONPATH")) if value
    )
    for suite in suites:
        for label, paths in SUITES[suite]:
            print(f"\n== {label} ==", flush=True)
            completed = subprocess.run(
                (sys.executable, "-m", "pytest", *paths, "-q"),
                cwd=REPO_ROOT,
                env=environment,
                check=False,
            )
            if completed.returncode != 0:
                return completed.returncode
    return 0


def _usage() -> str:
    return (
        "usage: python -m scripts.testing.run_backend_pytest_groups "
        "list|integration|e2e-bounded|e2e-reviewed|e2e-staged|e2e-all"
    )


if __name__ == "__main__":
    raise SystemExit(main())
