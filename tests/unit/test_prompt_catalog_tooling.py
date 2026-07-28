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


def test_task_member_prompt_contract_uses_the_internal_system_prompt_owner() -> None:
    ensure_repo_root_on_path()
    from scripts.docs.prompt_catalog.validation import PROMPT_CONTRACT_PATH

    assert PROMPT_CONTRACT_PATH.relative_to(Path(__file__).resolve().parents[2]).as_posix() == (
        "docs-internal/architecture/system-prompts.md"
    )
    assert PROMPT_CONTRACT_PATH.is_file()


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


def test_prompt_behavior_evaluation_uses_scenario_local_action_choices() -> None:
    ensure_repo_root_on_path()
    from scripts.docs.prompt_catalog.behavior_scenarios import evaluation_scenarios
    from scripts.docs.prompt_catalog.evaluation import (
        EvaluationResponse,
        output_schema,
        score_response,
    )

    for scenario in evaluation_scenarios():
        schema = output_schema(scenario)
        properties = schema["properties"]

        assert isinstance(properties, dict)
        assert properties["choice"]["enum"] == list(scenario.choices)
        assert 2 <= len(scenario.choices) <= 3

        response = EvaluationResponse(
            choice=next(iter(scenario.accepted_choices)),
            stop_now=scenario.expected_stop,
            rationale="Any non-empty explanation remains audit evidence, not a scored phrase.",
        )
        assert score_response(scenario, response)["passed"] is True
