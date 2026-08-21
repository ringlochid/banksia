from __future__ import annotations

from pathlib import Path

from scripts.testing.legacy_identity_audit import find_legacy_identity_violations

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_legacy_identity_occurrences_match_the_migration_allowlist() -> None:
    assert find_legacy_identity_violations(REPO_ROOT) == ()
