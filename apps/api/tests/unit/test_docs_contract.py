from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any


def ensure_repo_root_on_path() -> Path:
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


def write_page(root: Path, relative_path: str, text: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def build_valid_contract_tree(root: Path) -> None:
    write_page(root, "README.md", "# AutoClaw\n\n[Public docs](docs/README.md)\n")
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
    write_page(
        root,
        "docs-internal/README.md",
        "# Internal canon\n\nStatus: Reference\n\n"
        "[Design](design/v2/README.md)\n"
        "[V1 design](design/v1/README.md)\n"
        "[Current](current/v1/README.md)\n"
        "[Decisions](adr/README.md)\n",
    )
    write_page(
        root,
        "docs-internal/design/v1/README.md",
        "# V1 design\n\nStatus: Target\n\n[Baseline](baseline.md)\n",
    )
    write_page(
        root,
        "docs-internal/design/v1/baseline.md",
        "# Baseline\n\nStatus: Target\n",
    )
    write_page(
        root,
        "docs-internal/design/v2/README.md",
        "# V2 design\n\nStatus: Target\n\n[Runtime contract](runtime.md)\n",
    )
    write_page(
        root,
        "docs-internal/design/v2/runtime.md",
        "# Runtime\n\nStatus: Target\n",
    )
    write_page(
        root,
        "docs-internal/current/v1/README.md",
        "# Current v1\n\nStatus: Current\n\n[Runtime evidence](runtime.md)\n",
    )
    write_page(
        root,
        "docs-internal/current/v1/runtime.md",
        "# Runtime\n\nStatus: Current\n\n## Evidence\n\nObserved.\n",
    )
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
    write_page(
        root,
        ".agents/standards/docs.md",
        "# Docs structure\n\nStatus: Reference\n",
    )


def contract_modules() -> tuple[Any, Any]:
    ensure_repo_root_on_path()
    validator = importlib.import_module("scripts.docs.docs_contract.validator")
    markdown_files = importlib.import_module("scripts.docs.markdown_format.files")
    return validator, markdown_files


def finding_categories(report: Any) -> set[str]:
    return {finding.category for finding in report.findings}


def test_valid_contract_tree_has_no_findings(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)

    report = validator.build_contract_report(tmp_path)

    assert report.findings == ()


def test_contract_discovery_and_formatter_cover_live_doc_lanes(tmp_path: Path) -> None:
    validator, markdown_files = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs-internal/archive/old.md",
        "# Deleted archive\n\nStatus: Reference\n",
    )
    write_page(
        tmp_path,
        "docs-internal/execution/plan.md",
        "# Deleted execution\n\nStatus: Reference\n",
    )
    write_page(
        tmp_path,
        "docs-internal/design/v1/prompt-layer/generated/inventory.md",
        "# Generated inventory\n\nStatus: Reference\n",
    )
    write_page(
        tmp_path,
        "docs-internal/design/v1/prompt-layer/prompt-pack/mirror.md",
        "# Prompt mirror\n\nStatus: Reference\n",
    )

    contract_paths = {
        path.relative_to(tmp_path).as_posix()
        for path in validator.iter_contract_markdown_files(tmp_path)
    }
    formatter_paths = {
        path.relative_to(tmp_path).as_posix()
        for path in markdown_files.iter_maintained_markdown_files(tmp_path)
    }

    assert "docs/start/getting-started.md" in contract_paths
    assert "docs/concepts/overview.md" in contract_paths
    assert "docs/guides/example.md" in contract_paths
    assert "docs/help/troubleshooting.md" in contract_paths
    assert "docs/maintainers/maintain-docs.md" in contract_paths
    assert "docs/reference/overview.md" in contract_paths
    assert "docs-internal/design/v1/baseline.md" in contract_paths
    assert "docs-internal/design/v2/runtime.md" in contract_paths
    assert "docs-internal/current/v1/runtime.md" in contract_paths
    assert "docs-internal/archive/old.md" not in contract_paths
    assert "docs-internal/execution/plan.md" not in contract_paths
    prompt_catalog_owned_paths = {
        "docs-internal/design/v1/prompt-layer/generated/inventory.md",
        "docs-internal/design/v1/prompt-layer/prompt-pack/mirror.md",
    }
    assert prompt_catalog_owned_paths <= contract_paths
    assert prompt_catalog_owned_paths.isdisjoint(formatter_paths)
    assert contract_paths - prompt_catalog_owned_paths == formatter_paths


def test_status_and_current_evidence_rules_are_path_scoped(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(tmp_path, "docs-internal/design/v2/runtime.md", "# Runtime\n")
    write_page(
        tmp_path,
        "docs-internal/current/v1/runtime.md",
        "# Runtime\n\nStatus: Target\n",
    )

    report = validator.build_contract_report(tmp_path)

    assert finding_categories(report) >= {"status", "current-evidence"}


def test_public_docs_reject_internal_metadata_and_review_headings(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs/start/getting-started.md",
        "# Getting started\n\nStatus: Current\n\nLast verified: today\n\n## Evidence\n",
    )

    report = validator.build_contract_report(tmp_path)
    public_findings = [
        finding for finding in report.findings if finding.category == "public-metadata"
    ]

    assert len(public_findings) == 3


def test_links_require_existing_targets_and_human_labels(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs/README.md",
        "# Docs\n\n[getting-started.md](start/getting-started.md)\n"
        "[Missing guide](guides/missing.md)\n",
    )

    report = validator.build_contract_report(tmp_path)

    assert finding_categories(report) >= {"link", "link-label"}


def test_definition_examples_must_match_shipped_seeds(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs/reference/overview.md",
        "# Reference\n\n[Example](definitions/workflows/example.md)\n",
    )
    seed = "kind: workflow\nid: example\ndescription: Current example\n"
    write_page(
        tmp_path,
        "apps/api/src/autoclaw/definitions/seeds/workflows/example.yaml",
        seed,
    )
    example_path = "docs/reference/definitions/workflows/example.md"
    write_page(tmp_path, example_path, f"# Example\n\n```yaml\n{seed}```\n")

    matching_report = validator.build_contract_report(tmp_path)
    assert "definition-example" not in finding_categories(matching_report)

    write_page(tmp_path, example_path, "# Example\n\n```yaml\nid: stale\n```\n")
    stale_report = validator.build_contract_report(tmp_path)
    assert "definition-example" in finding_categories(stale_report)


def test_front_door_reports_unreachable_pages(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs-internal/design/v2/orphan.md",
        "# Orphan\n\nStatus: Reference\n",
    )

    report = validator.build_contract_report(tmp_path)

    assert any(
        finding.category == "front-door"
        and finding.path == Path("docs-internal/design/v2/orphan.md")
        for finding in report.findings
    )


def test_deleted_routes_are_rejected_outside_examples(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs/start/getting-started.md",
        "# Getting started\n\nDo not route to `docs-internal/archive/README.md`.\n\n"
        "```text\n"
        "docs-internal/execution/example.md\n"
        "```\n",
    )

    report = validator.build_contract_report(tmp_path)
    deleted_route_findings = [
        finding for finding in report.findings if finding.category == "deleted-route"
    ]

    assert len(deleted_route_findings) == 1
    assert "docs-internal/archive" in deleted_route_findings[0].message


def test_formatter_keeps_prompt_catalog_outputs_separate(tmp_path: Path) -> None:
    _, markdown_files = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs-internal/design/v1/prompt-layer/generated/inventory.md",
        "# Generated\n",
    )
    write_page(
        tmp_path,
        "docs-internal/design/v1/prompt-layer/contract.md",
        "# Contract\n\nStatus: Target\n",
    )

    maintained_paths = {
        path.relative_to(tmp_path).as_posix()
        for path in markdown_files.iter_maintained_markdown_files(tmp_path)
    }

    assert "docs-internal/design/v1/prompt-layer/contract.md" in maintained_paths
    assert "docs-internal/design/v1/prompt-layer/generated/inventory.md" not in maintained_paths


def test_markdown_formatter_normalizes_yaml_instruction_scalars() -> None:
    ensure_repo_root_on_path()
    formatting = importlib.import_module("scripts.docs.markdown_format.formatting")

    assert (
        formatting.format_yaml_text("instruction: |\n    First line\n    second line\n")
        == "instruction: >-\n  First line second line\n"
    )
