from __future__ import annotations

import re
from collections import deque
from pathlib import Path

from .definition_examples import definition_example_findings
from .discovery import (
    FROZEN_LEGACY_VERSION_ROOTS_BY_FAMILY,
    ROOT,
    discover_front_doors,
    iter_contract_markdown_files,
)
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
CURRENT_EVIDENCE_HEADINGS = PUBLIC_REVIEW_HEADINGS
DELETED_ROUTE_PATTERNS = (
    "docs-internal/execution",
    "docs-internal/archive",
    "docs/product",
)
FROZEN_LEGACY_FRONT_DOOR_REQUIREMENTS = {
    Path("docs-internal/design/v1/README.md"): (
        "frozen migration evidence",
        "not banksia target authority",
        "../readme.md",
    ),
    Path("docs-internal/design/v2/README.md"): (
        "frozen migration evidence",
        "not banksia target authority",
        "../readme.md",
    ),
    Path("docs-internal/current/v1/README.md"): (
        "frozen shipped-baseline evidence",
        "not a live banksia current lane or target owner",
        "../../design/readme.md",
    ),
}
LEGACY_VERSION_REFERENCE_PATTERN = re.compile(
    r"(?:\b(?:design|current)[/-]v[0-9]+\b|"
    r"\bcurrent[-_/ ]?v[0-9]+\b|"
    r"\bv[0-9]+(?:\s+(?:tree|design|contracts?|docs?|pages?))?\b|"
    r"\bv[0-9]+/v[0-9]+\b)",
    re.IGNORECASE,
)
LIVE_AUTHORITY_CLAIM_PATTERN = re.compile(
    r"(?:source of truth|target authority|target owner|defines? legal|current target|owns? target)",
    re.IGNORECASE,
)
AUTHORITY_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"[.,;:!?]|\b(?:and|or|but|however|yet|although|though|while)\b",
    re.IGNORECASE,
)
LOCAL_AUTHORITY_NEGATION_PATTERN = re.compile(
    r"\b(?:never|cannot|can't|no\s+longer)\b|"
    r"\bnot\b(?!\s+(?:only|merely|just|solely)\b)",
    re.IGNORECASE,
)
N8N_REFERENCE_PROTOCOL_PATH = Path("docs-internal/design/appendices/n8n-reference-protocol.md")
N8N_PROTOCOL_ALLOWED_IGNORED_PREFIXES = (
    "tmp/codex/references/n8n-source/",
    "tmp/codex/references/n8n-ui/",
)
IGNORED_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9_.-])tmp/[A-Za-z0-9_./@-]+")
VERSION_DIRECTORY_PATTERN = re.compile(r"^v[0-9]+$")


def build_contract_report(root: Path = ROOT) -> ContractReport:
    files = tuple(iter_contract_markdown_files(root))
    front_doors = tuple(discover_front_doors(root))
    findings: list[ContractFinding] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        findings.extend(status_findings(root=root, path=path, text=text))
        findings.extend(public_surface_findings(root=root, path=path, text=text))
        findings.extend(current_evidence_findings(root=root, path=path, text=text))
        findings.extend(deleted_route_findings(root=root, path=path, text=text))
        findings.extend(link_findings(root=root, path=path, text=text))
        findings.extend(ignored_dependency_findings(root=root, path=path, text=text))
    findings.extend(definition_example_findings(root))
    findings.extend(unexpected_version_tree_findings(root=root))
    findings.extend(frozen_legacy_front_door_findings(root=root))
    findings.extend(live_legacy_authority_findings(root=root, files=files))
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
    if relative_path in FROZEN_LEGACY_FRONT_DOOR_REQUIREMENTS:
        return ("Reference",)
    if parts[:3] == ("docs-internal", "design", "appendices"):
        return ("Reference",)
    if len(parts) == 3 and parts[:2] == ("docs-internal", "design"):
        return ("Target",)
    if is_frozen_legacy_version_path(relative_path, family="design"):
        return ("Target", "Reference")
    if is_frozen_legacy_version_path(relative_path, family="current"):
        return ("Current", "Reference")
    if parts[:2] == ("docs-internal", "adr"):
        return ("Accepted", "Reference")
    return None


def public_surface_findings(*, root: Path, path: Path, text: str) -> list[ContractFinding]:
    relative_path = path.relative_to(root)
    if relative_path != Path("README.md") and relative_path.parts[:1] != ("docs",):
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


def current_evidence_findings(*, root: Path, path: Path, text: str) -> list[ContractFinding]:
    relative_path = path.relative_to(root)
    if relative_path.parts[:2] != ("docs-internal", "current") or path.name == "README.md":
        return []
    headings = {line.strip() for _, line in iter_non_fenced_lines(text)}
    if headings & CURRENT_EVIDENCE_HEADINGS:
        return []
    return [
        finding(
            root=root,
            category="current-evidence",
            path=path,
            line=1,
            message=(
                "current contrast page requires an exact ## Evidence or ## Verification heading"
            ),
        )
    ]


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


def frozen_legacy_front_door_findings(*, root: Path) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for relative_path, required_fragments in FROZEN_LEGACY_FRONT_DOOR_REQUIREMENTS.items():
        path = root / relative_path
        if not path.is_file():
            findings.append(
                finding(
                    root=root,
                    category="legacy-authority",
                    path=path,
                    line=1,
                    message="required frozen AutoClaw evidence front door is missing",
                )
            )
            continue
        normalized_text = " ".join(
            path.read_text(encoding="utf-8").lower().replace(">", " ").split()
        )
        missing_fragments = [
            fragment for fragment in required_fragments if fragment not in normalized_text
        ]
        if not missing_fragments:
            continue
        findings.append(
            finding(
                root=root,
                category="legacy-authority",
                path=path,
                line=1,
                message=(
                    "frozen legacy front door is missing required notice/routing text: "
                    + ", ".join(repr(fragment) for fragment in missing_fragments)
                ),
            )
        )
    return findings


def unexpected_version_tree_findings(*, root: Path) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for family, allowed_versions in FROZEN_LEGACY_VERSION_ROOTS_BY_FAMILY.items():
        family_root = root / "docs-internal" / family
        if not family_root.is_dir():
            continue
        for version_root in sorted(family_root.iterdir()):
            if (
                not version_root.is_dir()
                or VERSION_DIRECTORY_PATTERN.fullmatch(version_root.name) is None
                or version_root.name in allowed_versions
            ):
                continue
            findings.append(
                finding(
                    root=root,
                    category="legacy-authority",
                    path=version_root,
                    line=1,
                    message=(
                        f"unexpected {family} version tree {version_root.name!r}; "
                        "Banksia permits only the enumerated frozen evidence roots"
                    ),
                )
            )
    return findings


def live_legacy_authority_findings(
    *,
    root: Path,
    files: tuple[Path, ...],
) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    for path in files:
        relative_path = path.relative_to(root)
        if not is_live_authority_routing_path(relative_path):
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in iter_non_fenced_lines(text):
            if not LEGACY_VERSION_REFERENCE_PATTERN.search(line):
                continue
            if not has_unnegated_authority_claim(line):
                continue
            findings.append(
                finding(
                    root=root,
                    category="legacy-authority",
                    path=path,
                    line=line_number,
                    message=(
                        "live routing must use the versionless Banksia owner, not a "
                        "V1/V2/current evidence lane"
                    ),
                )
            )
    return findings


def is_live_authority_routing_path(relative_path: Path) -> bool:
    if relative_path.parts[:2] == ("docs-internal", "design"):
        return not is_frozen_legacy_version_path(relative_path, family="design")
    if relative_path.parts[:2] == ("docs-internal", "current"):
        return not is_frozen_legacy_version_path(relative_path, family="current")
    if relative_path in {
        Path("AGENTS.md"),
        Path("STYLE.md"),
        Path("docs-internal/README.md"),
        Path("docs-internal/adr/README.md"),
    }:
        return True
    return relative_path.parts[:2] == (".agents", "standards")


def is_frozen_legacy_version_path(relative_path: Path, *, family: str) -> bool:
    if relative_path.parts[:2] != ("docs-internal", family):
        return False
    if len(relative_path.parts) < 3:
        return False
    return relative_path.parts[2] in FROZEN_LEGACY_VERSION_ROOTS_BY_FAMILY[family]


def has_unnegated_authority_claim(line: str) -> bool:
    for claim in LIVE_AUTHORITY_CLAIM_PATTERN.finditer(line):
        clause_start = 0
        for boundary in AUTHORITY_CLAUSE_BOUNDARY_PATTERN.finditer(line, 0, claim.start()):
            clause_start = boundary.end()
        claim_prefix = line[clause_start : claim.start()]
        if LOCAL_AUTHORITY_NEGATION_PATTERN.search(claim_prefix):
            continue
        return True
    return False


def ignored_dependency_findings(
    *,
    root: Path,
    path: Path,
    text: str,
) -> list[ContractFinding]:
    relative_path = path.relative_to(root)
    if not is_versionless_design_path(relative_path):
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
        disallowed_paths = [
            ignored_path
            for ignored_path in ignored_paths
            if not is_allowed_n8n_protocol_path(
                relative_path=relative_path,
                ignored_path=ignored_path,
            )
        ]
        if not disallowed_paths:
            continue
        findings.append(
            finding(
                root=root,
                category="ignored-dependency",
                path=path,
                line=line_number,
                message=(
                    "versionless canon cannot depend on ignored tmp paths: "
                    + ", ".join(disallowed_paths)
                ),
            )
        )
    return findings


def is_versionless_design_path(relative_path: Path) -> bool:
    if relative_path.parts[:2] != ("docs-internal", "design"):
        return False
    if len(relative_path.parts) < 3:
        return False
    return VERSION_DIRECTORY_PATTERN.fullmatch(relative_path.parts[2]) is None


def is_allowed_n8n_protocol_path(*, relative_path: Path, ignored_path: str) -> bool:
    return relative_path == N8N_REFERENCE_PROTOCOL_PATH and ignored_path.startswith(
        N8N_PROTOCOL_ALLOWED_IGNORED_PREFIXES
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
