from __future__ import annotations

import re
import subprocess
from pathlib import Path

LEGACY_IDENTITY_PATTERN = re.compile(r"banksia", re.IGNORECASE)
LEGACY_IDENTITY_ALLOWED_PATHS = frozenset(
    {
        "README.md",
        "docs-internal/adr/ADR-0013-banksia-target-and-clean-break.md",
        "docs-internal/adr/ADR-0018-oh-my-subagents-identity-cutover.md",
        "docs-internal/adr/ADR-0019-oms-backend-identity-migration.md",
        "docs-internal/adr/README.md",
        "docs-internal/operations/package-and-reset.md",
        "docs/README.md",
        "docs/guides/migrate-from-banksia.md",
        "docs/reference/cli.md",
        "docs/reference/configuration.md",
        "pyproject.toml",
        "scripts/docs/docs_contract/validator.py",
        "scripts/testing/installed_distribution/artifacts.py",
        "scripts/testing/installed_distribution/processes.py",
        "scripts/testing/installed_distribution/runtime.py",
        "scripts/testing/legacy_identity_audit.py",
        "src/oh_my_subagents/config.py",
        "src/oh_my_subagents/interfaces/cli/context.py",
        "src/oh_my_subagents/interfaces/cli/main.py",
        "src/oh_my_subagents/interfaces/cli/migration.py",
        "src/oh_my_subagents/interfaces/cli/root.py",
        "src/oh_my_subagents/paths.py",
        "src/oh_my_subagents/product_identity.py",
        "src/oh_my_subagents/runtime/prompt/rendering.py",
        "src/oh_my_subagents/runtime/workspace/admission.py",
        "src/oh_my_subagents/runtime/workspace/storage.py",
        "tests/unit/cli/test_command_surface.py",
        "tests/unit/cli/test_migration.py",
        "tests/unit/platform/test_managed_services.py",
        "tests/unit/runtime/test_task_root_compatibility.py",
        "tests/unit/runtime_prompt_rendering/test_rendering.py",
        "tests/unit/test_config.py",
        "tests/unit/test_docs_contract.py",
        "tests/unit/test_package_entrypoints.py",
        "tests/unit/test_product_identity.py",
    }
)
EXPECTED_LEGACY_PACKAGE_MEMBERS = frozenset(
    {
        "src/banksia/__init__.py",
        "src/banksia/__main__.py",
    }
)


def find_legacy_identity_violations(repo_root: Path) -> tuple[str, ...]:
    tracked_and_untracked = (
        subprocess.run(
            ("git", "ls-files", "-co", "--exclude-standard", "-z"),
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    violations: list[str] = []
    for relative in tracked_and_untracked:
        if not relative:
            continue
        path = repo_root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if LEGACY_IDENTITY_PATTERN.search(text) and relative not in LEGACY_IDENTITY_ALLOWED_PATHS:
            violations.append(relative)

    legacy_package_members = frozenset(
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "src" / "banksia").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    if legacy_package_members != EXPECTED_LEGACY_PACKAGE_MEMBERS:
        violations.append(
            "src/banksia package members differ from the two-file compatibility bridge: "
            f"{sorted(legacy_package_members)}"
        )
    return tuple(sorted(violations))


__all__ = [
    "EXPECTED_LEGACY_PACKAGE_MEMBERS",
    "LEGACY_IDENTITY_ALLOWED_PATHS",
    "find_legacy_identity_violations",
]
