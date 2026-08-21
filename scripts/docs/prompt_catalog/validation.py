from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePath

from oh_my_subagents.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    PROMPT_TRIGGER_KINDS,
    PromptDynamicInput,
)
from oh_my_subagents.runtime.prompt import (
    INSTRUCTION_ASSETS,
    instruction_asset_path,
    load_instruction_asset,
)
from oh_my_subagents.runtime.team.materialization import plan_initial_task_team
from oh_my_subagents.workflows.bootstrap import STARTER_WORKFLOW_FILENAMES
from oh_my_subagents.workflows.canonical import canonical_workflow_hash
from oh_my_subagents.workflows.contracts import (
    NormalizedMember,
    NormalizedWorkflow,
    PublishedWorkflowRevision,
)
from oh_my_subagents.workflows.ingest import parse_workflow
from scripts.docs.prompt_catalog import behavior_scenarios as scenario_catalog

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_CONTRACT_PATH = REPO_ROOT / "docs-internal/architecture/system-prompts.md"
EXPECTED_ASSET_PATHS = (
    "shared/core.txt",
    "shared/workspace-and-files.txt",
    "shared/checkpoint.txt",
    "positions/task-lead.txt",
    "behaviors/manager.txt",
    "behaviors/contributor.txt",
    "actions/human-request.txt",
    "actions/command-run.txt",
    "situations/continuation.txt",
)
STABLE_TARGET_ASSET_PATHS = EXPECTED_ASSET_PATHS
_REQUIRED_RETURN_SHAPES = {
    "child-says-done": ("service-owner",),
    "nested-wave": (
        "constraint-owner",
        "prototype-manager",
        "common-rubric-evaluator",
        "decision-critic",
    ),
}


@dataclass(frozen=True, slots=True)
class ScenarioTeam:
    workflow: NormalizedWorkflow
    current_member: NormalizedMember
    direct_team: tuple[NormalizedMember, ...]


def validate_prompt_contract() -> tuple[str, ...]:
    errors: list[str] = []
    asset_paths = tuple(instruction_asset_path(asset).as_posix() for asset in INSTRUCTION_ASSETS)
    if asset_paths != EXPECTED_ASSET_PATHS:
        errors.append("instruction assets do not match the Oh My Subagents prompt set")

    for asset in INSTRUCTION_ASSETS:
        try:
            content = load_instruction_asset(asset)
        except (FileNotFoundError, UnicodeDecodeError) as error:
            errors.append(f"cannot load {instruction_asset_path(asset)}: {error}")
            continue
        if not content.strip():
            errors.append(f"instruction asset is empty: {instruction_asset_path(asset)}")

    errors.extend(validate_stable_asset_bodies())
    errors.extend(validate_evaluation_scenarios())

    if tuple(PromptDynamicInput.model_fields) != PROMPT_DYNAMIC_INPUT_KEYS:
        errors.append("dynamic prompt input does not expose the canonical ordered sections")

    if len(PROMPT_TRIGGER_KINDS) != 7 or len(set(PROMPT_TRIGGER_KINDS)) != 7:
        errors.append("prompt trigger kinds must contain exactly seven distinct variants")

    return tuple(errors)


def load_scenario_team(
    scenario: scenario_catalog.EvaluationScenario,
) -> ScenarioTeam:
    workflow = _load_starter_workflow(scenario.workflow_id)
    revision = PublishedWorkflowRevision(
        workflow_id=workflow.id,
        revision_no=1,
        content_hash=canonical_workflow_hash(workflow),
        workflow=workflow,
    )
    plan = plan_initial_task_team(revision, f"t_eval_{scenario.workflow_id}")
    selected = next(
        (member for member in plan.members if member.member_id == scenario.current_member_id),
        None,
    )
    if selected is None:
        raise ValueError(
            f"scenario {scenario.id!r} selects missing Member "
            f"{scenario.current_member_id!r} from {scenario.workflow_id!r}"
        )
    direct_team = tuple(
        member.member for member in plan.members if member.parent_member_id == selected.member_id
    )
    return ScenarioTeam(
        workflow=workflow,
        current_member=selected.member,
        direct_team=direct_team,
    )


def validate_evaluation_scenarios() -> tuple[str, ...]:
    errors = list(scenario_catalog.validate_scenario_inventory())
    for scenario in scenario_catalog.evaluation_scenarios():
        try:
            team = load_scenario_team(scenario)
        except (OSError, UnicodeDecodeError, ValueError) as error:
            errors.append(f"{scenario.id}: {error}")
            continue
        if not team.direct_team:
            errors.append(f"{scenario.id}: selected current Member is not a Manager")
        if not team.current_member.instruction:
            errors.append(f"{scenario.id}: current Member instruction is blank")
        if any(not member.instruction for member in team.direct_team):
            errors.append(f"{scenario.id}: a direct-team instruction is blank")

        direct_ids = {member.id for member in team.direct_team}
        returned_ids = _returned_child_ids(scenario)
        if not set(returned_ids) <= direct_ids:
            errors.append(f"{scenario.id}: Wave return contains a non-direct child")
        expected_return_ids = _REQUIRED_RETURN_SHAPES.get(scenario.id)
        if expected_return_ids is not None and returned_ids != expected_return_ids:
            errors.append(f"{scenario.id}: required direct-team return shape changed")
        if scenario.id == "sequential-dependency" and scenario.wave_return is not None:
            errors.append("sequential-dependency must evaluate planning before the first return")
    return tuple(errors)


def validate_stable_asset_bodies() -> tuple[str, ...]:
    """Keep shipped non-temporary prompt assets byte-exact with normative canon."""

    try:
        contract = PROMPT_CONTRACT_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return (f"cannot read normative prompt contract: {error}",)

    loaded_by_path: dict[str, str] = {}
    for asset in INSTRUCTION_ASSETS:
        try:
            loaded_by_path[instruction_asset_path(asset).as_posix()] = load_instruction_asset(asset)
        except (FileNotFoundError, UnicodeDecodeError):
            continue
    errors: list[str] = []
    for path in STABLE_TARGET_ASSET_PATHS:
        expected = _extract_exact_source_body(contract, path=path)
        if expected is None:
            errors.append(f"normative prompt contract has no exact source body for {path}")
            continue
        actual = loaded_by_path.get(path)
        if actual is not None and actual != expected:
            errors.append(f"instruction asset differs from normative exact source body: {path}")
    return tuple(errors)


def _extract_exact_source_body(contract: str, *, path: str) -> str | None:
    heading = f"### `{path}`"
    lines = contract.splitlines()
    try:
        heading_index = lines.index(heading)
        opening_index = lines.index("```text", heading_index + 1)
        closing_index = lines.index("```", opening_index + 1)
    except ValueError:
        return None
    return "\n".join(lines[opening_index + 1 : closing_index]) + "\n"


def _load_starter_workflow(workflow_id: str) -> NormalizedWorkflow:
    filename = next(
        (
            candidate
            for candidate in STARTER_WORKFLOW_FILENAMES
            if PurePath(candidate).stem == workflow_id
        ),
        None,
    )
    if filename is None:
        raise ValueError(f"unknown packaged Starter Workflow {workflow_id!r}")
    resource = files("oh_my_subagents.workflows.resources.starter_workflows").joinpath(filename)
    workflow = parse_workflow(resource.read_bytes(), source_format="yaml")
    if workflow.id != workflow_id:
        raise ValueError(f"packaged Starter {filename!r} declares unexpected id {workflow.id!r}")
    return workflow


def _returned_child_ids(
    scenario: scenario_catalog.EvaluationScenario,
) -> tuple[str, ...]:
    if scenario.wave_return is None:
        return ()
    return tuple(member.child_id for member in scenario.wave_return.result.members)


__all__ = [
    "EXPECTED_ASSET_PATHS",
    "PROMPT_CONTRACT_PATH",
    "STABLE_TARGET_ASSET_PATHS",
    "ScenarioTeam",
    "load_scenario_team",
    "validate_evaluation_scenarios",
    "validate_prompt_contract",
    "validate_stable_asset_bodies",
]
