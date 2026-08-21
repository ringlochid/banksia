from __future__ import annotations

import re
from collections import deque
from pathlib import Path

from .discovery import ROOT, discover_front_doors, iter_contract_markdown_files
from .links import (
    is_filename_style_label,
    iter_markdown_links,
    iter_non_fenced_lines,
    resolve_local_link,
)
from .models import ContractFinding, ContractReport, FrontDoor
from .workflow_fixtures import workflow_fixture_findings

STATUS_PATTERN = re.compile(r"^Status:\s*(?P<status>.+?)\s*$")
PUBLIC_METADATA_PATTERN = re.compile(r"^(?:Status|Last verified):\s*", re.IGNORECASE)
PUBLIC_REVIEW_HEADINGS = frozenset({"## Evidence", "## Verification"})
DELETED_ROUTE_PATTERNS = (
    "docs-internal/execution",
    "docs-internal/archive",
    "docs/product",
)
IGNORED_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9_.-])tmp/[A-Za-z0-9_./@-]+")
INTERNAL_OWNER_FAMILIES = frozenset({"architecture", "interfaces", "operations"})
BANKSIA_BRAND_PATTERN = re.compile(r"\bBanksia\b")
BANKSIA_COMPATIBILITY_DOCUMENTS = frozenset(
    {
        Path("docs/guides/migrate-from-banksia.md"),
        Path("docs-internal/adr/ADR-0013-banksia-target-and-clean-break.md"),
        Path("docs-internal/adr/ADR-0018-oh-my-subagents-identity-cutover.md"),
    }
)
BANKSIA_COMPATIBILITY_LINES = {
    Path("README.md"): ("Migrate from Banksia",),
    Path("docs/README.md"): ("Migrate from Banksia",),
    Path("docs/reference/cli.md"): (r"\Banksia\Controller",),
    Path("docs-internal/adr/README.md"): ("ADR-0013 Banksia target",),
    Path("docs-internal/operations/package-and-reset.md"): (r"\Banksia\Controller",),
}
BANKSIA_ENV_COMPATIBILITY_DOCUMENTS = frozenset(
    {
        Path("docs/guides/migrate-from-banksia.md"),
        Path("docs/reference/configuration.md"),
        Path("docs-internal/adr/ADR-0013-banksia-target-and-clean-break.md"),
        Path("docs-internal/adr/ADR-0018-oh-my-subagents-identity-cutover.md"),
    }
)
STALE_IDENTITY_MARKERS = (
    "github.com/ringlochid/banksia",
    "pypi.org/project/banksia",
    "banksia-intro",
    "banksia-mark",
    "Try: banksia",
    "cd banksia",
    "A Oh My Subagents",
    "Build adaptable, accountable AI teams in minutes",
)


def build_contract_report(root: Path = ROOT) -> ContractReport:
    files = tuple(iter_contract_markdown_files(root))
    front_doors = tuple(discover_front_doors(root))
    findings: list[ContractFinding] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        findings.extend(status_findings(root=root, path=path, text=text))
        findings.extend(public_surface_findings(root=root, path=path, text=text))
        findings.extend(identity_findings(root=root, path=path, text=text))
        findings.extend(deleted_route_findings(root=root, path=path, text=text))
        findings.extend(link_findings(root=root, path=path, text=text))
        findings.extend(ignored_dependency_findings(root=root, path=path, text=text))
    findings.extend(workflow_fixture_findings(root))
    findings.extend(front_door_findings(root=root, files=files, front_doors=front_doors))
    return ContractReport(
        root=root,
        files=files,
        front_doors=front_doors,
        findings=tuple(sorted(findings)),
    )


def status_findings(*, root: Path, path: Path, text: str) -> list[ContractFinding]:
    allowed_statuses = allowed_statuses_for_path(root=root, path=path)
    if allowed_statuses is None:
        return []
    matches = [
        (line_number, match.group("status"))
        for line_number, line in iter_non_fenced_lines(text)
        if (match := STATUS_PATTERN.match(line)) is not None
    ]
    if not matches:
        return [
            finding(
                root=root,
                category="status",
                path=path,
                line=1,
                message=f"missing Status metadata; expected {' or '.join(allowed_statuses)}",
            )
        ]
    if len(matches) > 1:
        return [
            finding(
                root=root,
                category="status",
                path=path,
                line=matches[1][0],
                message="multiple Status metadata lines",
            )
        ]
    line_number, status = matches[0]
    if status in allowed_statuses:
        return []
    return [
        finding(
            root=root,
            category="status",
            path=path,
            line=line_number,
            message=f"Status {status!r} is invalid; expected {' or '.join(allowed_statuses)}",
        )
    ]


def allowed_statuses_for_path(*, root: Path, path: Path) -> tuple[str, ...] | None:
    relative_path = path.relative_to(root)
    parts = relative_path.parts
    if relative_path in {
        Path("AGENTS.md"),
        Path("STYLE.md"),
        Path("docs-internal/README.md"),
    }:
        return ("Reference",)
    if parts[:2] == (".agents", "standards"):
        return ("Reference",)
    if len(parts) >= 3 and parts[0] == "docs-internal" and parts[1] in INTERNAL_OWNER_FAMILIES:
        return ("Reference",)
    if parts[:2] == ("docs-internal", "adr"):
        if path.name == "README.md":
            return ("Reference",)
        return ("Accepted", "Superseded", "Reference")
    return None


def public_surface_findings(*, root: Path, path: Path, text: str) -> list[ContractFinding]:
    relative_path = path.relative_to(root)
    if relative_path not in {Path("README.md"), Path("CONTRIBUTING.md")} and (
        relative_path.parts[:1] != ("docs",)
    ):
        return []
    findings: list[ContractFinding] = []
    for line_number, line in iter_non_fenced_lines(text):
        if PUBLIC_METADATA_PATTERN.match(line):
            findings.append(
                finding(
                    root=root,
                    category="public-metadata",
                    path=path,
                    line=line_number,
                    message="public docs must not expose authority or verification metadata",
                )
            )
        if line.strip() in PUBLIC_REVIEW_HEADINGS:
            findings.append(
                finding(
                    root=root,
                    category="public-metadata",
                    path=path,
                    line=line_number,
                    message="public docs must not expose internal evidence headings",
                )
            )
    return findings


def identity_findings(*, root: Path, path: Path, text: str) -> list[ContractFinding]:
    relative_path = path.relative_to(root)
    findings: list[ContractFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stale_markers = tuple(marker for marker in STALE_IDENTITY_MARKERS if marker in line)
        if stale_markers:
            findings.append(
                finding(
                    root=root,
                    category="identity",
                    path=path,
                    line=line_number,
                    message="stale released-identity marker: " + ", ".join(stale_markers),
                )
            )
        if "BANKSIA_" in line and relative_path not in BANKSIA_ENV_COMPATIBILITY_DOCUMENTS:
            findings.append(
                finding(
                    root=root,
                    category="identity",
                    path=path,
                    line=line_number,
                    message="BANKSIA_* is allowed only in named compatibility documentation",
                )
            )
        if not BANKSIA_BRAND_PATTERN.search(line):
            continue
        if relative_path in BANKSIA_COMPATIBILITY_DOCUMENTS:
            continue
        allowed_fragments = BANKSIA_COMPATIBILITY_LINES.get(relative_path, ())
        if any(fragment in line for fragment in allowed_fragments):
            continue
        findings.append(
            finding(
                root=root,
                category="identity",
                path=path,
                line=line_number,
                message="Banksia branding is not in the maintained compatibility allowlist",
            )
        )
    return findings


def deleted_route_findings(*, root: Path, path: Path, text: str) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for line_number, line in iter_non_fenced_lines(text):
        for deleted_route in DELETED_ROUTE_PATTERNS:
            if deleted_route not in line:
                continue
            findings.append(
                finding(
                    root=root,
                    category="deleted-route",
                    path=path,
                    line=line_number,
                    message=f"reference to deleted route {deleted_route!r}",
                )
            )
    return findings


def ignored_dependency_findings(
    *,
    root: Path,
    path: Path,
    text: str,
) -> list[ContractFinding]:
    relative_path = path.relative_to(root)
    if not is_internal_owner_path(relative_path):
        return []

    findings: list[ContractFinding] = []
    reported_lines: set[int] = set()
    for link in iter_markdown_links(text):
        resolved_target = resolve_local_link(root=root, source=path, target=link.target)
        if resolved_target is None or not resolved_target.is_relative_to(root / "tmp"):
            continue
        findings.append(
            finding(
                root=root,
                category="ignored-dependency",
                path=path,
                line=link.line,
                message=f"versionless canon cannot link to ignored tmp content: {link.target!r}",
            )
        )
        reported_lines.add(link.line)

    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_number in reported_lines:
            continue
        ignored_paths = IGNORED_PATH_PATTERN.findall(line)
        if not ignored_paths:
            continue
        findings.append(
            finding(
                root=root,
                category="ignored-dependency",
                path=path,
                line=line_number,
                message=(
                    "versionless canon cannot depend on ignored tmp paths: "
                    + ", ".join(ignored_paths)
                ),
            )
        )
    return findings


def is_internal_owner_path(relative_path: Path) -> bool:
    return (
        len(relative_path.parts) >= 3
        and relative_path.parts[0] == "docs-internal"
        and relative_path.parts[1] in INTERNAL_OWNER_FAMILIES
    )


def link_findings(*, root: Path, path: Path, text: str) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for link in iter_markdown_links(text):
        resolved_target = resolve_local_link(root=root, source=path, target=link.target)
        if resolved_target is None:
            continue
        if not resolved_target.is_relative_to(root):
            findings.append(
                finding(
                    root=root,
                    category="link",
                    path=path,
                    line=link.line,
                    message=f"local link escapes the repository: {link.target!r}",
                )
            )
            continue
        if not resolved_target.exists():
            findings.append(
                finding(
                    root=root,
                    category="link",
                    path=path,
                    line=link.line,
                    message=f"local link target does not exist: {link.target!r}",
                )
            )
        if is_filename_style_label(link.label, link.target):
            findings.append(
                finding(
                    root=root,
                    category="link-label",
                    path=path,
                    line=link.line,
                    message=f"use a human-readable label instead of {link.label!r}",
                )
            )
    return findings


def front_door_findings(
    *,
    root: Path,
    files: tuple[Path, ...],
    front_doors: tuple[FrontDoor, ...],
) -> list[ContractFinding]:
    graph = markdown_link_graph(root=root, files=files)
    findings: list[ContractFinding] = []
    for front_door in front_doors:
        if not front_door.entrypoint.exists():
            findings.append(
                finding(
                    root=root,
                    category="front-door",
                    path=front_door.scope_root,
                    line=1,
                    message=f"{front_door.label} is missing README.md",
                )
            )
            continue
        reachable = reachable_paths(graph=graph, entrypoint=front_door.entrypoint.resolve())
        scope_files = {
            path.resolve() for path in files if path.is_relative_to(front_door.scope_root)
        }
        for orphan in sorted(scope_files - reachable):
            findings.append(
                finding(
                    root=root,
                    category="front-door",
                    path=orphan,
                    line=1,
                    message=f"not reachable from the {front_door.label} front door",
                )
            )
    return findings


def markdown_link_graph(*, root: Path, files: tuple[Path, ...]) -> dict[Path, set[Path]]:
    file_set = {path.resolve() for path in files}
    graph: dict[Path, set[Path]] = {path.resolve(): set() for path in files}
    for path in files:
        for link in iter_markdown_links(path.read_text(encoding="utf-8")):
            resolved_target = resolve_local_link(root=root, source=path, target=link.target)
            if resolved_target in file_set:
                graph[path.resolve()].add(resolved_target)
    return graph


def reachable_paths(*, graph: dict[Path, set[Path]], entrypoint: Path) -> set[Path]:
    reachable: set[Path] = set()
    pending = deque([entrypoint])
    while pending:
        path = pending.popleft()
        if path in reachable:
            continue
        reachable.add(path)
        pending.extend(graph.get(path, set()) - reachable)
    return reachable


def finding(
    *,
    root: Path,
    category: str,
    path: Path,
    line: int,
    message: str,
) -> ContractFinding:
    return ContractFinding(
        category=category,
        path=path.relative_to(root),
        line=line,
        message=message,
    )
