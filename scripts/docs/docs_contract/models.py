from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class ContractFinding:
    category: str
    path: Path
    line: int
    message: str


@dataclass(frozen=True)
class FrontDoor:
    label: str
    scope_root: Path
    entrypoint: Path


@dataclass(frozen=True)
class ContractReport:
    root: Path
    files: tuple[Path, ...]
    front_doors: tuple[FrontDoor, ...]
    findings: tuple[ContractFinding, ...]
