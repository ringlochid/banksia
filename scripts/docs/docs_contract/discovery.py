from __future__ import annotations

from pathlib import Path

from .models import FrontDoor

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_MARKDOWN_DIRECTORIES = (
    Path(".agents/standards"),
    Path("docs"),
    Path("docs-internal/architecture"),
    Path("docs-internal/interfaces"),
    Path("docs-internal/operations"),
    Path("docs-internal/verification"),
    Path("docs-internal/adr"),
)
CONTRACT_MARKDOWN_FILES = (
    Path("README.md"),
    Path("CONTRIBUTING.md"),
    Path("AGENTS.md"),
    Path("STYLE.md"),
    Path("docs-internal/README.md"),
)


def iter_contract_markdown_files(root: Path = ROOT) -> list[Path]:
    paths = [
        path
        for relative_directory in CONTRACT_MARKDOWN_DIRECTORIES
        if (directory := root / relative_directory).exists()
        for path in sorted(directory.rglob("*.md"))
    ]
    paths.extend(
        path for relative_file in CONTRACT_MARKDOWN_FILES if (path := root / relative_file).exists()
    )
    return sorted(set(paths), key=lambda path: path.relative_to(root).as_posix())


def discover_front_doors(root: Path = ROOT) -> list[FrontDoor]:
    front_doors: list[FrontDoor] = []
    add_front_door(
        front_doors,
        label="public docs",
        scope_root=root / "docs",
        entrypoint=root / "docs" / "README.md",
    )
    add_front_door(
        front_doors,
        label="internal docs",
        scope_root=root / "docs-internal",
        entrypoint=root / "docs-internal" / "README.md",
    )
    add_front_door(
        front_doors,
        label="extended standards",
        scope_root=root / ".agents" / "standards",
        entrypoint=root / ".agents" / "standards" / "README.md",
    )
    return front_doors


def add_front_door(
    front_doors: list[FrontDoor],
    *,
    label: str,
    scope_root: Path,
    entrypoint: Path,
) -> None:
    if scope_root.exists():
        front_doors.append(FrontDoor(label=label, scope_root=scope_root, entrypoint=entrypoint))
