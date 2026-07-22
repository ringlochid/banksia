from __future__ import annotations

from pathlib import Path

from banksia.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    PROMPT_TRIGGER_KINDS,
    PromptFamily,
)
from banksia.runtime.prompt import (
    INSTRUCTION_ASSETS,
    instruction_asset_path,
    instruction_assets_for_family,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_CONTRACT_READBACK_PATH = (
    REPO_ROOT / "docs-internal/design/appendices/generated/task-member-prompt-contract-readback.md"
)


def render_prompt_contract_readback() -> str:
    lines = [
        "# Shipped AutoClaw Task-member prompt baseline readback",
        "",
        "Status: Reference",
        "",
        "This page is generated from the shipped AutoClaw 0.1.8 prompt contracts and five "
        "instruction assets. It is deterministic migration-baseline evidence, not Banksia "
        "target prompt truth. The versionless [Task-member system-prompt contract]"
        "(../../system-prompts.md) is normative; WP-05 replaces these inputs and regenerates "
        "this same versionless readback. Run `make docs-prompt-generate` after changing an "
        "input, then run `make docs-prompt-check`.",
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
