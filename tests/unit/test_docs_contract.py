from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from .docs_contract_test_tree import (
    build_valid_contract_tree,
    contract_modules,
    ensure_repo_root_on_path,
    finding_categories,
    write_page,
)


def test_valid_contract_tree_has_no_findings(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)

    report = validator.build_contract_report(tmp_path)

    assert report.findings == ()


def test_discovery_covers_final_doc_lanes_and_excludes_generated_output(
    tmp_path: Path,
) -> None:
    validator, markdown_files = contract_modules()
    build_valid_contract_tree(tmp_path)
    generated = write_page(
        tmp_path,
        "docs-internal/verification/generated/readback.md",
        "# Generated readback\n\nStatus: Reference\n",
    )

    contract_paths = {
        path.relative_to(tmp_path).as_posix()
        for path in validator.iter_contract_markdown_files(tmp_path)
    }
    formatter_paths = {
        path.relative_to(tmp_path).as_posix()
        for path in markdown_files.iter_maintained_markdown_files(tmp_path)
    }

    assert {
        "CONTRIBUTING.md",
        "docs-internal/architecture/runtime.md",
        "docs-internal/interfaces/runtime-tools.md",
        "docs-internal/operations/configuration-and-providers.md",
        "docs-internal/verification/gates.md",
        "docs-internal/adr/ADR-0001-controller.md",
    } <= contract_paths
    assert "CONTRIBUTING.md" in formatter_paths
    assert generated.relative_to(tmp_path).as_posix() in contract_paths
    assert generated.relative_to(tmp_path).as_posix() not in formatter_paths


def test_internal_docs_have_one_front_door(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)

    front_doors = validator.discover_front_doors(tmp_path)
    scope_roots = {
        front_door.scope_root.relative_to(tmp_path).as_posix() for front_door in front_doors
    }

    assert "docs-internal" in scope_roots
    assert "docs-internal/architecture" not in scope_roots
    assert "docs-internal/adr" not in scope_roots


@pytest.mark.parametrize(
    ("relative_path", "valid_statuses", "invalid_status"),
    (
        ("docs-internal/architecture/runtime.md", ("Reference",), "Target"),
        ("docs-internal/interfaces/runtime-tools.md", ("Reference",), "Current"),
        (
            "docs-internal/operations/configuration-and-providers.md",
            ("Reference",),
            "Target",
        ),
        ("docs-internal/verification/gates.md", ("Reference",), "Target"),
        ("docs-internal/adr/README.md", ("Reference",), "Accepted"),
        (
            "docs-internal/adr/ADR-0001-controller.md",
            ("Accepted", "Superseded", "Reference"),
            "Target",
        ),
    ),
)
def test_status_rules_follow_final_internal_roles(
    tmp_path: Path,
    relative_path: str,
    valid_statuses: tuple[str, ...],
    invalid_status: str,
) -> None:
    validator, _ = contract_modules()
    path = tmp_path / relative_path

    for status in valid_statuses:
        assert (
            validator.status_findings(
                root=tmp_path,
                path=path,
                text=f"# Page\n\nStatus: {status}\n",
            )
            == []
        )

    findings = validator.status_findings(
        root=tmp_path,
        path=path,
        text=f"# Page\n\nStatus: {invalid_status}\n",
    )

    assert len(findings) == 1
    assert findings[0].category == "status"


@pytest.mark.parametrize(
    "relative_path",
    ("CONTRIBUTING.md", "docs/start/getting-started.md"),
)
def test_public_docs_reject_internal_metadata_and_review_headings(
    tmp_path: Path,
    relative_path: str,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        relative_path,
        "# Getting started\n\nStatus: Reference\n\nLast verified: today\n\n## Evidence\n",
    )

    report = validator.build_contract_report(tmp_path)

    assert (
        len([finding for finding in report.findings if finding.category == "public-metadata"]) == 3
    )


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


def test_internal_owners_reject_ignored_dependencies_except_n8n_protocol(
    tmp_path: Path,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(tmp_path, "tmp/codex/research.md", "# Ignored research\n")
    write_page(
        tmp_path,
        "docs-internal/architecture/runtime.md",
        "# Runtime\n\nStatus: Reference\n\n"
        "[Ignored research](../../tmp/codex/research.md)\n\n"
        "Do not make `tmp/private-plan.md` an implementation dependency.\n",
    )
    protocol = write_page(
        tmp_path,
        "docs-internal/verification/n8n-reference-protocol.md",
        "# n8n protocol\n\nStatus: Reference\n\n"
        "Recreate `tmp/codex/references/n8n-source/upstream/` from the pinned source.\n",
    )
    root_readme = tmp_path / "docs-internal/README.md"
    root_readme.write_text(
        root_readme.read_text(encoding="utf-8")
        + "\n[n8n protocol](verification/n8n-reference-protocol.md)\n",
        encoding="utf-8",
    )

    report = validator.build_contract_report(tmp_path)
    ignored_findings = [
        finding for finding in report.findings if finding.category == "ignored-dependency"
    ]

    assert len(ignored_findings) == 2
    assert {finding.path for finding in ignored_findings} == {
        Path("docs-internal/architecture/runtime.md")
    }
    assert protocol.relative_to(tmp_path) not in {finding.path for finding in ignored_findings}


def test_front_door_reports_unreachable_internal_page(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs-internal/interfaces/orphan.md",
        "# Orphan\n\nStatus: Reference\n",
    )

    report = validator.build_contract_report(tmp_path)

    assert any(
        finding.category == "front-door"
        and finding.path == Path("docs-internal/interfaces/orphan.md")
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
    findings = [finding for finding in report.findings if finding.category == "deleted-route"]

    assert len(findings) == 1
    assert "docs-internal/archive" in findings[0].message


def test_markdown_formatter_normalizes_yaml_instruction_scalars() -> None:
    ensure_repo_root_on_path()
    formatting = importlib.import_module("scripts.docs.markdown_format.formatting")

    assert (
        formatting.format_yaml_text("instruction: |\n    First line\n    second line\n")
        == "instruction: >-\n  First line second line\n"
    )
