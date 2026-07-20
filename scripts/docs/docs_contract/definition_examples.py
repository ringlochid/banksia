from __future__ import annotations

import re
from pathlib import Path

from .models import ContractFinding

DEFINITION_SEED_ROOT = Path("apps/api/src/autoclaw/definitions/seeds")
DEFINITION_EXAMPLE_ROOT = Path("docs/reference/definitions")
DEFINITION_FAMILIES = ("roles", "policies", "workflows")
YAML_BLOCK_PATTERN = re.compile(r"^```yaml\n(?P<body>.*?)\n```$", re.MULTILINE | re.DOTALL)
DEFINITION_ID_PATTERN = re.compile(r"^id:\s*(?P<definition_id>\S+)\s*$", re.MULTILINE)


def definition_example_findings(root: Path) -> list[ContractFinding]:
    seed_root = root / DEFINITION_SEED_ROOT
    if not seed_root.exists():
        return []

    findings: list[ContractFinding] = []
    for family in DEFINITION_FAMILIES:
        family_seed_root = seed_root / family
        for seed_path in sorted(family_seed_root.glob("*.yaml")):
            findings.extend(_compare_seed_to_example(root=root, family=family, seed_path=seed_path))
    return findings


def _compare_seed_to_example(
    *,
    root: Path,
    family: str,
    seed_path: Path,
) -> list[ContractFinding]:
    seed_text = seed_path.read_text(encoding="utf-8").rstrip()
    definition_id_match = DEFINITION_ID_PATTERN.search(seed_text)
    if definition_id_match is None:
        return []

    definition_id = definition_id_match.group("definition_id")
    example_name = definition_id.replace("_", "-")
    example_path = root / DEFINITION_EXAMPLE_ROOT / family / f"{example_name}.md"
    if not example_path.exists():
        return [
            _finding(
                root=root,
                path=example_path,
                message=f"missing public example for shipped {family[:-1]} {definition_id!r}",
            )
        ]

    example_text = example_path.read_text(encoding="utf-8")
    yaml_blocks = tuple(YAML_BLOCK_PATTERN.finditer(example_text))
    if len(yaml_blocks) != 1:
        return [
            _finding(
                root=root,
                path=example_path,
                message="expected exactly one fenced YAML definition",
            )
        ]
    if yaml_blocks[0].group("body").rstrip() == seed_text:
        return []
    return [
        _finding(
            root=root,
            path=example_path,
            message=f"public example differs from shipped seed {seed_path.name!r}",
        )
    ]


def _finding(*, root: Path, path: Path, message: str) -> ContractFinding:
    return ContractFinding(
        category="definition-example",
        path=path.relative_to(root),
        line=1,
        message=message,
    )
