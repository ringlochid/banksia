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
    write_page(
        tmp_path,
        "docs-internal/design/appendices/generated/task-member-prompt-contract-readback.md",
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

    assert "docs/start/getting-started.md" in contract_paths
    assert "docs/concepts/overview.md" in contract_paths
    assert "docs/guides/example.md" in contract_paths
    assert "docs/help/troubleshooting.md" in contract_paths
    assert "docs/maintainers/maintain-docs.md" in contract_paths
    assert "docs/reference/overview.md" in contract_paths
    assert "docs-internal/design/runtime.md" in contract_paths
    assert "docs-internal/design/v1/baseline.md" in contract_paths
    assert "docs-internal/design/v2/runtime.md" in contract_paths
    assert "docs-internal/current/v1/runtime.md" in contract_paths
    assert "docs-internal/archive/old.md" not in contract_paths
    assert "docs-internal/execution/plan.md" not in contract_paths
    prompt_catalog_owned_paths = {
        "docs-internal/design/appendices/generated/task-member-prompt-contract-readback.md",
        "docs-internal/design/v1/prompt-layer/generated/inventory.md",
        "docs-internal/design/v1/prompt-layer/prompt-pack/mirror.md",
    }
    assert prompt_catalog_owned_paths <= contract_paths
    assert prompt_catalog_owned_paths.isdisjoint(formatter_paths)
    assert contract_paths - prompt_catalog_owned_paths == formatter_paths


def test_front_door_discovery_keeps_appendices_inside_versionless_design(
    tmp_path: Path,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs-internal/design/appendices/generated/README.md",
        "# Generated\n\nStatus: Reference\n",
    )

    front_doors = validator.discover_front_doors(tmp_path)
    labels = {front_door.label for front_door in front_doors}
    scope_roots = {
        front_door.scope_root.relative_to(tmp_path).as_posix() for front_door in front_doors
    }

    assert "Banksia design" in labels
    assert {"design v1", "design v2", "current v1"} <= labels
    assert "docs-internal/design" in scope_roots
    assert "docs-internal/design/appendices" not in scope_roots
    assert "docs-internal/design/appendices/generated" not in scope_roots


@pytest.mark.parametrize(
    ("relative_path", "valid_statuses", "invalid_status"),
    (
        ("docs-internal/design/README.md", ("Target",), "Reference"),
        ("docs-internal/design/runtime.md", ("Target",), "Reference"),
        ("docs-internal/design/appendices/README.md", ("Reference",), "Target"),
        (
            "docs-internal/design/appendices/operator-conversation-contract.md",
            ("Target",),
            "Reference",
        ),
        (
            "docs-internal/design/appendices/n8n-reference-protocol.md",
            ("Reference",),
            "Target",
        ),
        (
            "docs-internal/design/appendices/generated/readback.md",
            ("Reference",),
            "Target",
        ),
        ("docs-internal/design/v1/README.md", ("Reference",), "Target"),
        ("docs-internal/design/v2/README.md", ("Reference",), "Target"),
        ("docs-internal/current/v1/README.md", ("Reference",), "Current"),
        ("docs-internal/design/v1/baseline.md", ("Target", "Reference"), "Current"),
        ("docs-internal/design/v2/runtime.md", ("Target", "Reference"), "Current"),
        ("docs-internal/current/v1/runtime.md", ("Current", "Reference"), "Target"),
    ),
)
def test_status_rules_are_scoped_to_versionless_and_frozen_doc_roles(
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


def test_frozen_legacy_front_doors_require_explicit_notices(tmp_path: Path) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        "docs-internal/design/v2/README.md",
        "# V2 design\n\nStatus: Target\n\n[Runtime contract](runtime.md)\n",
    )

    report = validator.build_contract_report(tmp_path)

    assert "legacy-authority" in finding_categories(report)


@pytest.mark.parametrize(
    ("relative_path", "statement"),
    (
        (
            "docs-internal/design/runtime.md",
            "V2 contracts define legal routes for Banksia.",
        ),
        (
            "docs-internal/design/runtime.md",
            "V2 is the target source of truth for Banksia.",
        ),
        (
            "docs-internal/design/runtime.md",
            "The V2 tree defines legal routes for Banksia.",
        ),
        (
            "docs-internal/design/appendices/README.md",
            "Current/v1 owns target authority for this appendix.",
        ),
        (
            "docs-internal/design/appendices/README.md",
            "Current-v1 is the target owner for this appendix.",
        ),
        (
            ".agents/standards/docs.md",
            "V2 contracts are the target source of truth, not merely evidence.",
        ),
        (
            ".agents/standards/docs.md",
            "V2 is not merely evidence and defines legal routes.",
        ),
        (
            ".agents/standards/docs.md",
            "V2 is not merely the target source of truth.",
        ),
    ),
)
def test_live_routing_rejects_unnegated_legacy_target_authority(
    tmp_path: Path,
    relative_path: str,
    statement: str,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    path = tmp_path / relative_path
    original = path.read_text(encoding="utf-8")
    path.write_text(f"{original}\n{statement}\n", encoding="utf-8")

    report = validator.build_contract_report(tmp_path)

    assert any(
        finding.category == "legacy-authority" and finding.path == Path(relative_path)
        for finding in report.findings
    )


@pytest.mark.parametrize(
    "statement",
    (
        "V2 contracts are not the target source of truth.",
        "V2 contracts no longer define legal routes.",
        "Never treat design/v2 as target authority.",
    ),
)
def test_live_routing_allows_explicitly_negative_legacy_authority_statements(
    tmp_path: Path,
    statement: str,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    path = tmp_path / ".agents/standards/docs.md"
    path.write_text(
        f"# Docs structure\n\nStatus: Reference\n\n{statement}\n",
        encoding="utf-8",
    )

    report = validator.build_contract_report(tmp_path)

    assert not any(
        finding.category == "legacy-authority" and finding.path == Path(".agents/standards/docs.md")
        for finding in report.findings
    )


def test_frozen_version_descendants_are_exempt_from_live_authority_scan(
    tmp_path: Path,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    frozen_path = tmp_path / "docs-internal/design/v2/runtime.md"
    frozen_path.write_text(
        "# Runtime\n\nStatus: Target\n\n"
        "V2 contracts define legal routes and are the target source of truth.\n",
        encoding="utf-8",
    )

    report = validator.build_contract_report(tmp_path)

    assert not any(
        finding.category == "legacy-authority"
        and finding.path == Path("docs-internal/design/v2/runtime.md")
        for finding in report.findings
    )


@pytest.mark.parametrize(
    "relative_root",
    (
        "docs-internal/design/v3",
        "docs-internal/design/v99",
        "docs-internal/current/v2",
    ),
)
def test_unexpected_version_trees_are_rejected_and_never_become_front_doors(
    tmp_path: Path,
    relative_root: str,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(
        tmp_path,
        f"{relative_root}/README.md",
        "# Unexpected era\n\nStatus: Reference\n\n"
        "This V3 tree defines legal routes and is the target source of truth.\n",
    )

    report = validator.build_contract_report(tmp_path)
    front_door_roots = {
        front_door.scope_root.relative_to(tmp_path).as_posix() for front_door in report.front_doors
    }

    assert relative_root not in front_door_roots
    assert any(
        finding.category == "legacy-authority"
        and finding.path == Path(relative_root)
        and "unexpected" in finding.message
        for finding in report.findings
    )
    assert any(
        finding.category == "legacy-authority"
        and finding.path == Path(f"{relative_root}/README.md")
        and "versionless Banksia owner" in finding.message
        for finding in report.findings
    )


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


def test_versionless_canon_rejects_ignored_dependencies_except_n8n_protocol(
    tmp_path: Path,
) -> None:
    validator, _ = contract_modules()
    build_valid_contract_tree(tmp_path)
    write_page(tmp_path, "tmp/codex/research.md", "# Ignored research\n")
    write_page(
        tmp_path,
        "docs-internal/design/runtime.md",
        "# Runtime\n\nStatus: Target\n\n"
        "[Ignored research](../../tmp/codex/research.md)\n\n"
        "Do not make `tmp/private-plan.md` an implementation dependency.\n",
    )
    appendices_readme = tmp_path / "docs-internal/design/appendices/README.md"
    appendices_readme.write_text(
        appendices_readme.read_text(encoding="utf-8")
        + "[n8n protocol](n8n-reference-protocol.md)\n",
        encoding="utf-8",
    )
    write_page(
        tmp_path,
        "docs-internal/design/appendices/n8n-reference-protocol.md",
        "# n8n protocol\n\nStatus: Reference\n\n"
        "Recreate `tmp/codex/references/n8n-source/upstream/` from the pinned source.\n",
    )

    report = validator.build_contract_report(tmp_path)
    ignored_findings = [
        finding for finding in report.findings if finding.category == "ignored-dependency"
    ]

    assert len(ignored_findings) == 2
    assert {finding.path for finding in ignored_findings} == {
        Path("docs-internal/design/runtime.md")
    }


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
    write_page(
        tmp_path,
        "docs-internal/design/appendices/generated/task-member-prompt-contract-readback.md",
        "# Generated\n",
    )

    maintained_paths = {
        path.relative_to(tmp_path).as_posix()
        for path in markdown_files.iter_maintained_markdown_files(tmp_path)
    }

    assert "docs-internal/design/v1/prompt-layer/contract.md" in maintained_paths
    assert "docs-internal/design/v1/prompt-layer/generated/inventory.md" not in maintained_paths
    assert (
        "docs-internal/design/appendices/generated/task-member-prompt-contract-readback.md"
        not in maintained_paths
    )


def test_markdown_formatter_normalizes_yaml_instruction_scalars() -> None:
    ensure_repo_root_on_path()
    formatting = importlib.import_module("scripts.docs.markdown_format.formatting")

    assert (
        formatting.format_yaml_text("instruction: |\n    First line\n    second line\n")
        == "instruction: >-\n  First line second line\n"
    )
