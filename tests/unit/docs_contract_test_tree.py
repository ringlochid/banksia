from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import Any

WORKFLOW_EXAMPLE_FILES = (
    "full.yaml",
    "minimal.yaml",
    "omx-autopilot.yaml",
    "omx-best-practice-research.yaml",
)
WORKFLOW_SEED_FILES = (
    "autonomous-delivery.yaml",
    "evidence-research.yaml",
    "reviewed-delivery.yaml",
)


def ensure_repo_root_on_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


def write_page(root: Path, relative_path: str, text: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def copy_workflow_fixtures(root: Path) -> None:
    repo_root = ensure_repo_root_on_path()
    source_root = repo_root / "docs-internal/design/appendices"
    target_root = root / "docs-internal/design/appendices"
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        source_root / "workflow-definition.schema.yaml",
        target_root / "workflow-definition.schema.yaml",
    )
    for family, names in (
        ("workflow-examples", WORKFLOW_EXAMPLE_FILES),
        ("workflow-seeds", WORKFLOW_SEED_FILES),
    ):
        family_root = target_root / family
        family_root.mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copy2(source_root / family / name, family_root / name)


def build_valid_contract_tree(root: Path) -> None:
    _write_root_and_public_docs(root)
    _write_versionless_design(root)
    _write_frozen_evidence(root)
    _write_decisions_and_standards(root)


def contract_modules() -> tuple[Any, Any]:
    ensure_repo_root_on_path()
    validator = importlib.import_module("scripts.docs.docs_contract.validator")
    markdown_files = importlib.import_module("scripts.docs.markdown_format.files")
    return validator, markdown_files


def finding_categories(report: Any) -> set[str]:
    return {finding.category for finding in report.findings}


def workflow_finding_messages(report: Any) -> set[str]:
    return {
        finding.message for finding in report.findings if finding.category == "workflow-fixture"
    }


def _write_root_and_public_docs(root: Path) -> None:
    write_page(root, "README.md", "# Banksia\n\n[Public docs](docs/README.md)\n")
    write_page(root, "AGENTS.md", "# Agents\n\nStatus: Reference\n")
    write_page(root, "STYLE.md", "# Style\n\nStatus: Reference\n")
    write_page(
        root,
        "docs/README.md",
        "# Docs\n\n"
        "[Getting started](start/getting-started.md)\n"
        "[Concepts](concepts/overview.md)\n"
        "[Guides](guides/example.md)\n"
        "[Help](help/troubleshooting.md)\n"
        "[Maintainers](maintainers/maintain-docs.md)\n"
        "[Reference](reference/overview.md)\n",
    )
    write_page(root, "docs/start/getting-started.md", "# Getting started\n")
    write_page(root, "docs/concepts/overview.md", "# Concepts\n")
    write_page(root, "docs/guides/example.md", "# Guide\n")
    write_page(root, "docs/help/troubleshooting.md", "# Troubleshooting\n")
    write_page(root, "docs/maintainers/maintain-docs.md", "# Maintain docs\n")
    write_page(root, "docs/reference/overview.md", "# Reference\n")


def _write_versionless_design(root: Path) -> None:
    write_page(
        root,
        "docs-internal/README.md",
        "# Internal canon\n\nStatus: Reference\n\n"
        "[Banksia design](design/README.md)\n"
        "[Frozen V1 design](design/v1/README.md)\n"
        "[Frozen V2 design](design/v2/README.md)\n"
        "[Frozen current evidence](current/v1/README.md)\n"
        "[Decisions](adr/README.md)\n",
    )
    write_page(
        root,
        "docs-internal/design/README.md",
        "# Banksia design\n\nStatus: Target\n\n"
        "[Runtime](runtime.md)\n"
        "[Appendices](appendices/README.md)\n"
        "[Frozen V1 design](v1/README.md)\n"
        "[Frozen V2 design](v2/README.md)\n",
    )
    write_page(root, "docs-internal/design/runtime.md", "# Runtime\n\nStatus: Target\n")
    write_page(
        root,
        "docs-internal/design/appendices/README.md",
        "# Appendices\n\nStatus: Reference\n\n"
        "[Workflow examples](workflow-examples/README.md)\n"
        "[Workflow seeds](workflow-seeds/README.md)\n",
    )
    write_page(
        root,
        "docs-internal/design/appendices/workflow-examples/README.md",
        "# Workflow examples\n\nStatus: Reference\n\n"
        "[Full](full.yaml)\n"
        "[Minimal](minimal.yaml)\n"
        "[Autopilot](omx-autopilot.yaml)\n"
        "[Research](omx-best-practice-research.yaml)\n",
    )
    write_page(
        root,
        "docs-internal/design/appendices/workflow-seeds/README.md",
        "# Workflow seeds\n\nStatus: Reference\n\n"
        "[Autonomous delivery](autonomous-delivery.yaml)\n"
        "[Evidence research](evidence-research.yaml)\n"
        "[Reviewed delivery](reviewed-delivery.yaml)\n",
    )
    copy_workflow_fixtures(root)


def _write_frozen_evidence(root: Path) -> None:
    write_page(
        root,
        "docs-internal/design/v1/README.md",
        "# V1 design\n\nStatus: Reference\n\n"
        "> **Frozen migration evidence:** This tree records an earlier Banksia "
        "baseline. It is not Banksia target authority. Use the versionless "
        "[Banksia design](../README.md).\n\n"
        "[Baseline](baseline.md)\n",
    )
    write_page(root, "docs-internal/design/v1/baseline.md", "# Baseline\n\nStatus: Target\n")
    write_page(
        root,
        "docs-internal/design/v2/README.md",
        "# V2 design\n\nStatus: Reference\n\n"
        "> **Frozen migration evidence:** This tree records the final Banksia "
        "baseline. It is not Banksia target authority. Use the versionless "
        "[Banksia design](../README.md).\n\n"
        "[Runtime contract](runtime.md)\n",
    )
    write_page(root, "docs-internal/design/v2/runtime.md", "# Runtime\n\nStatus: Target\n")
    write_page(
        root,
        "docs-internal/current/v1/README.md",
        "# Current v1\n\nStatus: Reference\n\n"
        "> **Frozen shipped-baseline evidence:** This tree is not a live Banksia current\n"
        "> lane or target owner. Use the versionless "
        "[Banksia design](../../design/README.md).\n\n"
        "[Runtime evidence](runtime.md)\n",
    )
    write_page(
        root,
        "docs-internal/current/v1/runtime.md",
        "# Runtime\n\nStatus: Current\n\n## Evidence\n\nObserved.\n",
    )


def _write_decisions_and_standards(root: Path) -> None:
    write_page(
        root,
        "docs-internal/adr/README.md",
        "# Decisions\n\nStatus: Reference\n\n[Controller truth](ADR-0001-controller.md)\n",
    )
    write_page(
        root,
        "docs-internal/adr/ADR-0001-controller.md",
        "# Controller truth\n\nStatus: Accepted\n",
    )
    write_page(
        root,
        ".agents/standards/README.md",
        "# Standards\n\nStatus: Reference\n\n[Docs structure](docs.md)\n",
    )
    write_page(root, ".agents/standards/docs.md", "# Docs structure\n\nStatus: Reference\n")
