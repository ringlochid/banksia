from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def test_task_member_prompt_contract_validator_passes() -> None:
    ensure_repo_root_on_path()
    from scripts.docs.prompt_catalog.validation import validate_prompt_contract

    assert validate_prompt_contract() == ()


def test_task_member_prompt_contract_readback_is_deterministic() -> None:
    ensure_repo_root_on_path()
    from scripts.docs.prompt_catalog.render import (
        PROMPT_CONTRACT_READBACK_PATH,
        render_prompt_contract_readback,
    )

    rendered = render_prompt_contract_readback()

    assert rendered == render_prompt_contract_readback()
    assert "Status: Reference" in rendered
    assert "deterministic implementation readback" in rendered
    assert "not an independent source of product truth" in rendered
    assert "../../architecture/system-prompts.md" in rendered
    assert rendered.count(".txt`") == 9
    assert (
        "task | dispatch | current_member | assignment | continuation | direct_team | "
        "work_plan | available_actions | workspace"
    ) in rendered
    assert "delegation_wave_settled | human_result | command_result" in rendered
    assert "root_start" not in rendered
    assert PROMPT_CONTRACT_READBACK_PATH.relative_to(
        Path(__file__).resolve().parents[2]
    ).as_posix() == ("docs-internal/verification/generated/task-member-prompt-contract-readback.md")
    assert PROMPT_CONTRACT_READBACK_PATH.read_text(encoding="utf-8") == rendered
