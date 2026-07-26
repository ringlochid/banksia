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


def test_prompt_behavior_evaluation_uses_packaged_starter_teams(
    tmp_path: Path,
) -> None:
    ensure_repo_root_on_path()
    from scripts.docs.prompt_catalog.behavior_scenarios import (
        BEHAVIOR_STORIES,
        REQUIRED_SCENARIO_IDS,
        evaluation_scenarios,
    )
    from scripts.docs.prompt_catalog.evaluation import prepare_scenarios
    from scripts.docs.prompt_catalog.validation import (
        load_scenario_team,
        validate_evaluation_scenarios,
    )

    scenarios = evaluation_scenarios()
    prepared = prepare_scenarios(
        provider="codex",
        model="gpt-5.6",
        effort="high",
        workspace=tmp_path,
    )

    assert validate_evaluation_scenarios() == ()
    assert (
        tuple(scenario.story for scenario in scenarios if scenario.story is not None)
        == BEHAVIOR_STORIES
    )
    assert tuple(scenario.id for scenario in scenarios) == REQUIRED_SCENARIO_IDS
    assert tuple(item.scenario for item in prepared) == scenarios
    for item in prepared:
        team = load_scenario_team(item.scenario)
        assert team.current_member.instruction is not None
        assert team.workflow.id in item.request.input_text
        assert team.current_member.instruction in item.request.instructions_text
        assert tuple(member.id for member in team.direct_team)
        assert all(
            member.instruction in item.request.input_text
            for member in team.direct_team
            if member.instruction is not None
        )
