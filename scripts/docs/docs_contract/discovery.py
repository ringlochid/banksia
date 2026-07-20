from __future__ import annotations

from pathlib import Path

from .models import FrontDoor

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_MARKDOWN_DIRECTORIES = (
    Path(".agents/standards"),
    Path("docs"),
    Path("docs-internal/design"),
    Path("docs-internal/current"),
    Path("docs-internal/adr"),
)
CONTRACT_MARKDOWN_FILES = (
    Path("README.md"),
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
    add_versioned_front_doors(front_doors, root=root, family="design")
    add_versioned_front_doors(front_doors, root=root, family="current")
    add_front_door(
        front_doors,
        label="accepted decisions",
        scope_root=root / "docs-internal" / "adr",
        entrypoint=root / "docs-internal" / "adr" / "README.md",
    )
    add_front_door(
        front_doors,
        label="extended standards",
        scope_root=root / ".agents" / "standards",
        entrypoint=root / ".agents" / "standards" / "README.md",
    )
    return front_doors


def add_versioned_front_doors(
    front_doors: list[FrontDoor],
    *,
    root: Path,
    family: str,
) -> None:
    family_root = root / "docs-internal" / family
    if not family_root.exists():
        return
    for version_root in sorted(path for path in family_root.iterdir() if path.is_dir()):
        add_front_door(
            front_doors,
            label=f"{family} {version_root.name}",
            scope_root=version_root,
            entrypoint=version_root / "README.md",
        )


def add_front_door(
    front_doors: list[FrontDoor],
    *,
    label: str,
    scope_root: Path,
    entrypoint: Path,
) -> None:
    if scope_root.exists():
        front_doors.append(FrontDoor(label=label, scope_root=scope_root, entrypoint=entrypoint))
