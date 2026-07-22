from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def test_task_member_prompt_baseline_validator_passes() -> None:
    ensure_repo_root_on_path()
    from scripts.docs.prompt_catalog.validation import validate_prompt_contract

    assert validate_prompt_contract() == ()


def test_task_member_prompt_baseline_readback_is_deterministic() -> None:
    ensure_repo_root_on_path()
    from scripts.docs.prompt_catalog.render import (
        PROMPT_CONTRACT_READBACK_PATH,
        render_prompt_contract_readback,
    )

    rendered = render_prompt_contract_readback()

    assert rendered == render_prompt_contract_readback()
    assert "Status: Reference" in rendered
    assert "deterministic migration-baseline evidence" in rendered
    assert "not Banksia target prompt truth" in rendered
    assert "../../system-prompts.md" in rendered
    assert rendered.count("instructions/") == 13
    assert "assignment | trigger | plan | context | dispatch | next" in rendered
    assert "root_start | accepted_boundary | child_return" in rendered
    assert PROMPT_CONTRACT_READBACK_PATH.relative_to(
        Path(__file__).resolve().parents[4]
    ).as_posix() == (
        "docs-internal/design/appendices/generated/task-member-prompt-contract-readback.md"
    )
    assert PROMPT_CONTRACT_READBACK_PATH.read_text(encoding="utf-8") == rendered
