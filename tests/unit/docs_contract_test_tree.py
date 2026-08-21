from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import Any

WORKFLOW_EXAMPLE_FILES = (
    "advanced-cross-layer-delivery.yaml",
    "advanced-reviewed-code-change.yaml",
    "advanced-technical-decision.yaml",
)
WORKFLOW_SEED_FILES = (
    "decision-through-competing-prototypes.yaml",
    "deep-research-and-decision-brief.yaml",
    "experiment-and-replication-program.yaml",
    "idea-to-validated-demo.yaml",
    "incident-investigation-and-recovery.yaml",
    "migration-and-modernisation.yaml",
    "production-feature-delivery.yaml",
    "security-audit-and-hardening.yaml",
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
    schema_source = repo_root / "docs/reference/workflows/workflow-definition.schema.yaml"
    schema_target = root / "docs/reference/workflows/workflow-definition.schema.yaml"
    schema_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        schema_source,
        schema_target,
    )
    for source_root, target_root, names in (
        (
            repo_root / "examples/workflows",
            root / "examples/workflows",
            WORKFLOW_EXAMPLE_FILES,
        ),
        (
            repo_root / "src/banksia/workflows/resources/starter_workflows",
            root / "src/banksia/workflows/resources/starter_workflows",
            WORKFLOW_SEED_FILES,
        ),
    ):
        target_root.mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copy2(source_root / name, target_root / name)


def build_valid_contract_tree(root: Path) -> None:
    _write_root_and_public_docs(root)
    _write_internal_docs(root)
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
    write_page(root, "README.md", "# Oh My Subagents\n\n[Public docs](docs/README.md)\n")
    write_page(root, "CONTRIBUTING.md", "# Contributing\n")
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
        "[Reference](reference/overview.md)\n"
        "[Workflow schema](reference/workflows/README.md)\n",
    )
    write_page(root, "docs/start/getting-started.md", "# Getting started\n")
    write_page(root, "docs/concepts/overview.md", "# Concepts\n")
    write_page(root, "docs/guides/example.md", "# Guide\n")
    write_page(root, "docs/help/troubleshooting.md", "# Troubleshooting\n")
    write_page(root, "docs/maintainers/maintain-docs.md", "# Maintain docs\n")
    write_page(root, "docs/reference/overview.md", "# Reference\n")
    write_page(
        root,
        "docs/reference/workflows/README.md",
        "# Workflow reference\n\n[Workflow schema](workflow-definition.schema.yaml)\n",
    )
    write_page(
        root,
        "examples/workflows/README.md",
        "# Workflow examples\n\n"
        "[Cross-layer](advanced-cross-layer-delivery.yaml)\n"
        "[Reviewed change](advanced-reviewed-code-change.yaml)\n"
        "[Technical decision](advanced-technical-decision.yaml)\n",
    )
    copy_workflow_fixtures(root)


def _write_internal_docs(root: Path) -> None:
    write_page(
        root,
        "docs-internal/README.md",
        "# Internal docs\n\nStatus: Reference\n\n"
        "[Runtime](architecture/runtime.md)\n"
        "[Runtime tools](interfaces/runtime-tools.md)\n"
        "[Configuration](operations/configuration-and-providers.md)\n"
        "[Decisions](adr/README.md)\n",
    )
    write_page(
        root,
        "docs-internal/architecture/runtime.md",
        "# Runtime\n\nStatus: Reference\n",
    )
    write_page(
        root,
        "docs-internal/interfaces/runtime-tools.md",
        "# Runtime tools\n\nStatus: Reference\n",
    )
    write_page(
        root,
        "docs-internal/operations/configuration-and-providers.md",
        "# Configuration and providers\n\nStatus: Reference\n",
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
