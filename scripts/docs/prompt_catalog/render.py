from __future__ import annotations

from pathlib import Path

from banksia.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    PROMPT_TRIGGER_KINDS,
)
from banksia.runtime.prompt import (
    INSTRUCTION_ASSETS,
    instruction_asset_path,
)
from scripts.docs.prompt_catalog.behavior_scenarios import evaluation_scenarios

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_CONTRACT_READBACK_PATH = (
    REPO_ROOT / "docs-internal/verification/generated/task-member-prompt-contract-readback.md"
)


def render_prompt_contract_readback() -> str:
    lines = [
        "# Banksia Task-member prompt contract readback",
        "",
        "Status: Reference",
        "",
        "This page is generated from the shipped Banksia prompt contracts and controller-owned "
        "instruction assets. It is a deterministic implementation readback, not an independent "
        "source of product truth. The versionless [Task-member system-prompt contract]"
        "(../../architecture/system-prompts.md) is normative. Run "
        "`make docs-prompt-generate` after changing an input, then run "
        "`make docs-prompt-check`.",
        "",
        "## Instruction assets",
        "",
    ]
    lines.extend(f"- {instruction_asset_path(asset)}" for asset in INSTRUCTION_ASSETS)
    lines.extend(
        [
            "",
            "## Stable composition order",
            "",
            "1. `shared/core.txt`",
            "2. `shared/workspace-and-files.txt`",
            "3. `shared/checkpoint.txt`",
            "4. `positions/task-lead.txt` when the current Member is the Task lead",
            "5. exactly one behavior asset: `behaviors/manager.txt` or `behaviors/contributor.txt`",
            "6. `actions/human-request.txt` when an allowed Human Request action is exposed",
            "7. `actions/command-run.txt` when Command Run is allowed and exposed",
            "8. `situations/continuation.txt` when a Continuation exists",
            "9. the nonblank authored Member instruction",
            "10. the nonblank authored Workflow note",
            "",
            "## Dynamic input",
            "",
            f"`{' | '.join(PROMPT_DYNAMIC_INPUT_KEYS)}`",
            "",
            "## Trigger kinds",
            "",
            f"`{' | '.join(PROMPT_TRIGGER_KINDS)}`",
            "",
            "## Rendering invariants",
            "",
            "- one `<banksia_system>` instruction root and one "
            "`<banksia_dispatch_request>` input root",
            "- controller-owned fixed element names with escaped values as element text",
            "- stable field order and omission of absent optional sections",
            "- UTF-8-compatible Unicode, LF line endings, and exactly one final newline",
            "",
            "## Definition-backed behavior evaluation",
            "",
            "Every scenario loads the named packaged Starter through the shipped Workflow "
            "parser and initial-team planner. The rendered system and dynamic inputs must "
            "contain that exact current Member, its authored instruction, the Workflow note, "
            "and every direct-team instruction before a provider run is admitted.",
            "",
            "| Scenario | Starter Workflow | Current Member | Behavior under evaluation |",
            "| --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        (
            f"| `{scenario.id}` | `{scenario.workflow_id}` | "
            f"`{scenario.current_member_id}` | {scenario.focus} |"
        )
        for scenario in evaluation_scenarios()
    )
    return "\n".join(lines) + "\n"


__all__ = ["PROMPT_CONTRACT_READBACK_PATH", "render_prompt_contract_readback"]
