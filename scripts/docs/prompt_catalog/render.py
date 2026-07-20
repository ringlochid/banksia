from __future__ import annotations

from pathlib import Path

from autoclaw.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    PROMPT_TRIGGER_KINDS,
    PromptFamily,
)
from autoclaw.runtime.prompt import (
    INSTRUCTION_ASSETS,
    instruction_asset_path,
    instruction_assets_for_family,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_CONTRACT_READBACK_PATH = (
    REPO_ROOT / "docs-internal/design/v2/prompt-layer/generated/contract-readback.md"
)


def render_prompt_contract_readback() -> str:
    lines = [
        "# V2 prompt contract readback",
        "",
        "Status: Reference",
        "",
        "This page is generated from the shipped V2 prompt contracts and five instruction "
        "assets. Run `make docs-prompt-generate` after changing either input, then run "
        "`make docs-prompt-check`.",
        "",
        "## Instruction assets",
        "",
    ]
    lines.extend(f"- {instruction_asset_path(asset)}" for asset in INSTRUCTION_ASSETS)
    lines.extend(["", "## Family composition", ""])
    for family in PromptFamily:
        paths = ", ".join(
            instruction_asset_path(asset).as_posix()
            for asset in instruction_assets_for_family(family)
        )
        lines.append(f"- {family.value}: {paths}")
    lines.extend(
        [
            "",
            "## Dynamic input",
            "",
            f"`{' | '.join(PROMPT_DYNAMIC_INPUT_KEYS)}`",
            "",
            "## Trigger kinds",
            "",
            f"`{' | '.join(PROMPT_TRIGGER_KINDS)}`",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = ["PROMPT_CONTRACT_READBACK_PATH", "render_prompt_contract_readback"]
