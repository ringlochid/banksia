from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict

from oh_my_subagents.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    provider_subprocess_environment_overrides,
)
from oh_my_subagents.runtime.contracts.prompt import (
    DispatchRequestRenderInput,
    PromptAssignment,
    PromptContinuation,
    PromptDispatch,
    PromptDynamicInput,
    PromptTask,
    PromptWorkspace,
    RenderedDispatchRequest,
)
from oh_my_subagents.runtime.contracts.team_read import (
    CurrentMemberRead,
    DirectTeamMemberRead,
    EffectiveCapabilitiesRead,
    MemberAvailability,
    MemberBehavior,
    ResolvedProviderRead,
    ResolvedSandboxRead,
)
from oh_my_subagents.runtime.prompt import render_dispatch_request
from scripts.docs.prompt_catalog import behavior_scenarios as scenario_catalog
from scripts.docs.prompt_catalog.validation import (
    load_scenario_team,
    validate_evaluation_scenarios,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    choice: str
    stop_now: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    raw_response: str
    structured_response: object | None
    provider_metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class PreparedScenario:
    scenario: scenario_catalog.EvaluationScenario
    request: RenderedDispatchRequest


def output_schema(
    scenario: scenario_catalog.EvaluationScenario,
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "choice": {"type": "string", "enum": list(scenario.choices)},
            "stop_now": {
                "type": "boolean",
                "description": scenario_catalog.STOP_NOW_RUBRIC,
            },
            "rationale": {"type": "string", "minLength": 1, "maxLength": 1_000},
        },
        "required": ["choice", "stop_now", "rationale"],
    }


def render_scenario_request(
    scenario: scenario_catalog.EvaluationScenario,
    *,
    provider: str,
    model: str,
    effort: str,
    workspace: Path,
) -> DispatchRequestRenderInput:
    team = load_scenario_team(scenario)
    assignment_id = f"asn_eval_{scenario.id.replace('-', '_')}"
    direct_team = tuple(
        DirectTeamMemberRead(
            id=member.id,
            title=member.title,
            description=member.description,
            instruction=member.instruction,
            provider=ResolvedProviderRead(kind=provider, model=model),
            capabilities=EffectiveCapabilitiesRead(),
            participation=scenario.participation,
            availability=MemberAvailability.AVAILABLE,
        )
        for member in team.direct_team
    )
    return DispatchRequestRenderInput(
        dynamic_input=PromptDynamicInput(
            task=PromptTask(id="t_prompt_eval", workflow_id=team.workflow.id),
            dispatch=PromptDispatch(
                id=f"dsp_eval_{scenario.id.replace('-', '_')}",
                attempt_id=f"att_eval_{scenario.id.replace('-', '_')}",
                assignment_id=assignment_id,
            ),
            current_member=CurrentMemberRead(
                id=team.current_member.id,
                title=team.current_member.title,
                description=team.current_member.description,
                instruction=team.current_member.instruction,
                position=("task_lead" if team.current_member.id == team.workflow.lead.id else None),
                behavior=MemberBehavior.MANAGER,
                provider=ResolvedProviderRead(
                    kind=provider,
                    model=model,
                    effort=effort,
                    sandbox=ResolvedSandboxRead(mode="read_only", network="deny"),
                ),
                effective_capabilities=EffectiveCapabilitiesRead(),
            ),
            assignment=PromptAssignment(
                id=assignment_id,
                prompt=(f"{scenario.assignment_prompt}\n\n{scenario_catalog.STOP_NOW_RUBRIC}"),
            ),
            continuation=(
                PromptContinuation(trigger=scenario.wave_return)
                if scenario.wave_return is not None
                else None
            ),
            direct_team=direct_team,
            work_plan=None,
            available_actions=scenario.available_actions,
            workspace=PromptWorkspace(
                root=str(workspace),
                task_directory=".oms/t_prompt_eval",
                manifest=".oms/t_prompt_eval/manifest.md",
                workflow_note=(
                    ".oms/t_prompt_eval/workflow-note.md"
                    if team.workflow.note is not None
                    else None
                ),
                notes=".oms/t_prompt_eval/notes",
                artifacts=".oms/t_prompt_eval/artifacts",
                command_runs=".oms/t_prompt_eval/command-runs",
            ),
        ),
        member_instruction=team.current_member.instruction,
        workflow_note=team.workflow.note,
    )


def score_response(
    scenario: scenario_catalog.EvaluationScenario,
    response: EvaluationResponse,
) -> dict[str, object]:
    dimensions = {
        "choice": response.choice in scenario.accepted_choices,
        "stop": response.stop_now is scenario.expected_stop,
    }
    score = sum(dimensions.values())
    return {
        "score": score,
        "maximum_score": len(dimensions),
        "passed": score == len(dimensions),
        "dimensions": dimensions,
        "expected": {
            "accepted_choices": sorted(scenario.accepted_choices),
            "stop_now": scenario.expected_stop,
        },
    }


def prepare_scenarios(
    *,
    provider: str,
    model: str,
    effort: str,
    workspace: Path,
) -> tuple[PreparedScenario, ...]:
    errors = validate_evaluation_scenarios()
    if errors:
        raise ValueError("invalid prompt behavior scenarios: " + "; ".join(errors))

    prepared: list[PreparedScenario] = []
    for scenario in scenario_catalog.evaluation_scenarios():
        request = render_dispatch_request(
            render_scenario_request(
                scenario,
                provider=provider,
                model=model,
                effort=effort,
                workspace=workspace,
            )
        )
        _require_definition_backed_request(scenario, request)
        prepared.append(PreparedScenario(scenario=scenario, request=request))
    return tuple(prepared)


async def run_evaluation(args: argparse.Namespace) -> int:
    output_directory, workspace = prepare_output_directory(Path(args.output_dir))
    prepared = prepare_scenarios(
        provider=args.provider,
        model=args.model,
        effort=args.effort,
        workspace=workspace,
    )
    observations = await _run_provider(args, prepared, workspace=workspace)
    results = _record_results(output_directory, prepared, observations)
    summary = {
        **_evaluation_metadata(args),
        "scenarios": results,
        "passed": all(bool(result["passed"]) for result in results),
    }
    write_json(output_directory / "summary.json", summary)
    print(f"Evaluation evidence: {output_directory}")
    return 0 if summary["passed"] else 1


async def _run_provider(
    args: argparse.Namespace,
    prepared: tuple[PreparedScenario, ...],
    *,
    workspace: Path,
) -> tuple[ProviderObservation, ...]:
    if args.provider == "codex":
        return await run_codex_scenarios(
            prepared,
            model=args.model,
            effort=args.effort,
            workspace=workspace,
        )
    return await run_claude_scenarios(
        prepared,
        model=args.model,
        effort=args.effort,
        max_budget_usd=args.max_budget_usd,
        workspace=workspace,
    )


async def run_codex_scenarios(
    prepared: tuple[PreparedScenario, ...],
    *,
    model: str,
    effort: str,
    workspace: Path,
) -> tuple[ProviderObservation, ...]:
    from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox
    from openai_codex.generated.v2_all import ReasoningEffort

    try:
        resolved_effort = ReasoningEffort(effort)
    except ValueError as error:
        raise ValueError(f"Codex does not support effort '{effort}'") from error

    observations: list[ProviderObservation] = []
    async with AsyncCodex(CodexConfig(env=provider_subprocess_environment_overrides())) as codex:
        for item in prepared:
            thread = await codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                cwd=str(workspace),
                developer_instructions=item.request.instructions_text,
                ephemeral=True,
                model=model,
                sandbox=Sandbox.read_only,
            )
            turn = await thread.turn(
                item.request.input_text,
                effort=resolved_effort,
                output_schema=output_schema(item.scenario),
            )
            result = await turn.run()
            observations.append(
                ProviderObservation(
                    raw_response=result.final_response or "",
                    structured_response=None,
                    provider_metadata={
                        "turn_id": result.id,
                        "status": result.status.value,
                        "duration_ms": result.duration_ms,
                        "usage": json_value(result.usage),
                    },
                )
            )
    return tuple(observations)


async def run_claude_scenarios(
    prepared: tuple[PreparedScenario, ...],
    *,
    model: str,
    effort: str,
    max_budget_usd: float,
    workspace: Path,
) -> tuple[ProviderObservation, ...]:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    from claude_agent_sdk.types import EffortLevel

    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError(f"Claude does not support effort '{effort}'")

    observations: list[ProviderObservation] = []
    for item in prepared:
        options = ClaudeAgentOptions(
            tools=[],
            allowed_tools=[],
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": item.request.instructions_text,
            },
            mcp_servers={},
            strict_mcp_config=True,
            permission_mode="dontAsk",
            model=model,
            cwd=workspace,
            setting_sources=[],
            skills=[],
            max_turns=2,
            max_budget_usd=max_budget_usd,
            effort=cast(EffortLevel, effort),
            output_format={
                "type": "json_schema",
                "schema": output_schema(item.scenario),
            },
            env=provider_subprocess_environment_overrides(
                allowed_keys=frozenset({ANTHROPIC_API_KEY})
            ),
        )
        result_message: ResultMessage | None = None
        async for message in query(prompt=item.request.input_text, options=options):
            if isinstance(message, ResultMessage):
                result_message = message
        if result_message is None:
            raise RuntimeError("Claude evaluation returned no result message")
        if result_message.is_error:
            raise RuntimeError(f"Claude evaluation failed with subtype {result_message.subtype}")
        observations.append(
            ProviderObservation(
                raw_response=result_message.result or "",
                structured_response=result_message.structured_output,
                provider_metadata={
                    "subtype": result_message.subtype,
                    "duration_ms": result_message.duration_ms,
                    "duration_api_ms": result_message.duration_api_ms,
                    "num_turns": result_message.num_turns,
                    "total_cost_usd": result_message.total_cost_usd,
                    "usage": result_message.usage,
                    "model_usage": result_message.model_usage,
                },
            )
        )
    return tuple(observations)


def _require_definition_backed_request(
    scenario: scenario_catalog.EvaluationScenario,
    request: RenderedDispatchRequest,
) -> None:
    team = load_scenario_team(scenario)
    instructions = ElementTree.fromstring(request.instructions_text)
    dynamic = ElementTree.fromstring(request.input_text)

    expected_direct = tuple((member.id, member.instruction or "") for member in team.direct_team)
    rendered_direct = tuple(
        (member.findtext("id", ""), member.findtext("instruction", ""))
        for member in dynamic.findall("./direct_team/member")
    )
    checks = {
        "Workflow id": (
            dynamic.findtext("./task/workflow_id"),
            team.workflow.id,
        ),
        "current Member id": (
            dynamic.findtext("./current_member/id"),
            team.current_member.id,
        ),
        "current Member dynamic instruction": (
            dynamic.findtext("./current_member/instruction"),
            team.current_member.instruction,
        ),
        "current Member system instruction": (
            instructions.findtext("./member_instruction"),
            team.current_member.instruction,
        ),
        "Workflow note": (
            instructions.findtext("./workflow_note"),
            team.workflow.note,
        ),
        "direct-team definitions": (rendered_direct, expected_direct),
    }
    mismatches = [label for label, (actual, expected) in checks.items() if actual != expected]
    if mismatches:
        raise ValueError(
            f"scenario {scenario.id!r} is not definition-backed for " + ", ".join(mismatches)
        )


def _record_results(
    output_directory: Path,
    prepared: tuple[PreparedScenario, ...],
    observations: tuple[ProviderObservation, ...],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for item, observation in zip(prepared, observations, strict=True):
        scenario_result = _score_observation(item.scenario, observation)
        write_json(
            output_directory / f"{item.scenario.id}.json",
            {
                **scenario_result,
                "definition_binding": {
                    "workflow_id": item.scenario.workflow_id,
                    "current_member_id": item.scenario.current_member_id,
                    "story": item.scenario.story,
                },
                "provider_metadata": observation.provider_metadata,
                "raw_response": observation.raw_response,
                "structured_response": observation.structured_response,
                "request": {
                    "instructions": item.request.instructions_text,
                    "input": item.request.input_text,
                },
            },
        )
        results.append(scenario_result)
        print(
            f"{item.scenario.id}: "
            f"{scenario_result.get('score', 0)}/"
            f"{scenario_result.get('maximum_score', 2)} "
            f"{'PASS' if scenario_result['passed'] else 'FAIL'}"
        )
    return results


def _score_observation(
    scenario: scenario_catalog.EvaluationScenario,
    observation: ProviderObservation,
) -> dict[str, object]:
    try:
        response = parse_provider_response(observation)
        return {
            "scenario": scenario.id,
            "response": response.model_dump(mode="json"),
            **score_response(scenario, response),
        }
    except Exception as error:
        return {
            "scenario": scenario.id,
            "passed": False,
            "error": f"{type(error).__name__}: {error}",
        }


def _evaluation_metadata(args: argparse.Namespace) -> dict[str, object]:
    return {
        "provider": args.provider,
        "model": args.model,
        "effort": args.effort,
        "settings": {
            "provider_tools": "disabled",
            "workspace_access": (
                "read_only sandbox" if args.provider == "codex" else "none; tools disabled"
            ),
            "provider_session": (
                "ephemeral thread" if args.provider == "codex" else "fresh unresumed SDK query"
            ),
            "scenario_source": (
                "packaged Starter parsed through the shipped Workflow parser and initial-team "
                "planner"
            ),
            "scoring": (
                "scenario-local action choice and stop flag; rationale retained for human "
                "audit without wording or substring scoring"
            ),
        },
        "versions": provider_versions(args.provider),
    }


def parse_provider_response(observation: ProviderObservation) -> EvaluationResponse:
    value = observation.structured_response
    if value is None:
        value = json.loads(observation.raw_response)
    return EvaluationResponse.model_validate(value)


def prepare_output_directory(output_directory: Path) -> tuple[Path, Path]:
    resolved = (
        output_directory if output_directory.is_absolute() else REPO_ROOT / output_directory
    ).resolve()
    allowed_root = (REPO_ROOT / "tmp").resolve()
    if not resolved.is_relative_to(allowed_root):
        raise ValueError("prompt evaluation output must stay under the ignored tmp/ tree")
    resolved.mkdir(parents=True, exist_ok=True)
    if any(resolved.iterdir()):
        raise ValueError("prompt evaluation output directory must be empty")
    workspace = resolved / "provider-workspace"
    workspace.mkdir()
    return resolved, workspace


def provider_versions(provider: str) -> dict[str, str]:
    distribution = {"codex": "openai-codex", "claude": "claude-agent-sdk"}[provider]
    return {distribution: metadata.version(distribution)}


def json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [json_value(item) for item in value]
    return str(value)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(json_value(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bounded Oh My Subagents Task-member prompt behavior evaluation."
    )
    parser.add_argument("--provider", choices=("codex", "claude"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--effort",
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        default="high",
    )
    parser.add_argument("--max-budget-usd", type=float, default=0.25)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_evaluation(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
