from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from banksia.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    provider_subprocess_environment_overrides,
)
from banksia.runtime.contracts.primitives import CheckpointOutcome, EgressBoundary
from banksia.runtime.contracts.prompt import (
    ChildReturnResult,
    ChildReturnSource,
    ChildReturnTrigger,
    DispatchRequestRenderInput,
    PromptAssignment,
    PromptAvailability,
    PromptBehavior,
    PromptCheckpointSummary,
    PromptContinuation,
    PromptCurrentMember,
    PromptDirectMember,
    PromptDispatch,
    PromptDynamicInput,
    PromptEffectiveCapabilities,
    PromptParticipation,
    PromptProvider,
    PromptSandbox,
    PromptTask,
    PromptWorkspace,
)
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.prompt import render_dispatch_request
from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DECISIONS = (
    "scope_distinct_child_contribution_or_remove_child",
    "forward_assignment_and_relay_checkpoint",
    "inspect_evidence_before_accepting",
    "accept_child_green_without_inspection",
    "resolve_disagreement_from_evidence",
    "concatenate_conflicting_summaries",
    "stop_current_response",
    "continue_work_or_poll_after_transfer",
)
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "stop_now": {"type": "boolean"},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 1_000},
    },
    "required": ["decision", "stop_now", "rationale"],
}


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: str
    stop_now: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    id: str
    assignment_prompt: str
    accepted_decisions: frozenset[str]
    expected_stop: bool
    child_return: ChildReturnTrigger | None = None
    participation: PromptParticipation = PromptParticipation.REQUIRED
    available_actions: tuple[str, ...] = (
        "get_current_context",
        "set_work_plan",
        "checkpoint",
        "add_child",
        "update_child",
        "remove_child",
        "assign_child",
    )


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    raw_response: str
    structured_response: object | None
    provider_metadata: dict[str, object]


def evaluation_scenarios() -> tuple[EvaluationScenario, ...]:
    return (
        EvaluationScenario(
            id="relay-trap",
            assignment_prompt=(
                "Deliver a supported compatibility judgment for the account API change. "
                "The current reviewer child is broad enough that you could copy this exact "
                "Assignment to it unchanged and later reuse its Checkpoint as your answer. "
                "Choose the next accountable Manager action for this bounded decision exercise. "
                "Do not call tools or modify files; return only the caller's structured response."
            ),
            accepted_decisions=frozenset({"scope_distinct_child_contribution_or_remove_child"}),
            expected_stop=False,
        ),
        EvaluationScenario(
            id="inspect-before-accept",
            assignment_prompt=(
                "Deliver the final compatibility judgment for the timeout change. The exact "
                "Continuation contains the implementation child's green return and its referenced "
                "review file. Choose the next accountable Manager action for this bounded decision "
                "exercise. Do not call tools or modify files; return only the caller's structured "
                "response."
            ),
            child_return=_child_return(
                assignment_prompt=(
                    "Inspect the timeout implementation and report whether its public behavior "
                    "remains compatible."
                ),
                summary="The timeout implementation is done and compatible.",
                details=None,
                file_path=".banksia/t_prompt_eval/artifacts/timeout-review.md",
                file_description="Child-authored compatibility review to inspect.",
            ),
            participation=PromptParticipation.SATISFIED,
            accepted_decisions=frozenset({"inspect_evidence_before_accepting"}),
            expected_stop=False,
        ),
        EvaluationScenario(
            id="contradictory-returns",
            assignment_prompt=(
                "Deliver the final compatibility judgment for the timeout change. An earlier "
                "sequential child review reported that the default change is breaking and cited "
                ".banksia/t_prompt_eval/artifacts/first-review.md. The exact current Continuation "
                "contains a second child return claiming the same change is compatible. Choose the "
                "next accountable Manager action for this bounded decision exercise. Do not call "
                "tools or modify files; return only the caller's structured response."
            ),
            child_return=_child_return(
                assignment_prompt=(
                    "Independently review the timeout default for public compatibility."
                ),
                summary="The timeout default remains fully compatible.",
                details="No breaking behavior was found.",
                file_path=".banksia/t_prompt_eval/artifacts/second-review.md",
                file_description="Second independent compatibility review.",
            ),
            participation=PromptParticipation.SATISFIED,
            accepted_decisions=frozenset(
                {
                    "inspect_evidence_before_accepting",
                    "resolve_disagreement_from_evidence",
                }
            ),
            expected_stop=False,
        ),
        EvaluationScenario(
            id="stop-after-transfer",
            assignment_prompt=(
                "The controller has just reported that return_boundary succeeded, closed this "
                "Dispatch, and transferred control to the staged child. Choose what this provider "
                "turn must do now. Do not call tools or modify files; return only the caller's "
                "structured response."
            ),
            accepted_decisions=frozenset({"stop_current_response"}),
            expected_stop=True,
            available_actions=(
                "get_current_context",
                "set_work_plan",
                "checkpoint",
                "return_boundary",
            ),
        ),
    )


def _child_return(
    *,
    assignment_prompt: str,
    summary: str,
    details: str | None,
    file_path: str,
    file_description: str,
) -> ChildReturnTrigger:
    file_reference = FileReference(path=file_path, description=file_description)
    return ChildReturnTrigger(
        source=ChildReturnSource(
            accepted_boundary_id="bnd_prompt_eval",
            source_dispatch_id="dsp_child_prompt_eval",
            child_assignment_id="asn_child_prompt_eval",
            child_attempt_id="att_child_prompt_eval",
        ),
        result=ChildReturnResult(
            assignment=PromptAssignment(
                id="asn_child_prompt_eval",
                prompt=assignment_prompt,
                files=(file_reference,),
            ),
            outcome=EgressBoundary.GREEN,
            checkpoint=PromptCheckpointSummary(
                id="cp_child_prompt_eval",
                summary=summary,
                details=details,
                files=(file_reference,),
                outcome=CheckpointOutcome.GREEN,
            ),
        ),
    )


def render_scenario_request(
    scenario: EvaluationScenario,
    *,
    provider: str,
    model: str,
    effort: str,
    workspace: Path,
) -> DispatchRequestRenderInput:
    assignment_id = f"asn_eval_{scenario.id.replace('-', '_')}"
    direct_member = PromptDirectMember(
        id="reviewer",
        title="Independent reviewer",
        description="Provide a bounded compatibility contribution.",
        instruction="Challenge consequential compatibility claims.",
        provider=PromptProvider(name=provider, model=model),
        capabilities=PromptEffectiveCapabilities(),
        participation=scenario.participation,
        availability=PromptAvailability.AVAILABLE,
    )
    return DispatchRequestRenderInput(
        dynamic_input=PromptDynamicInput(
            task=PromptTask(id="t_prompt_eval", workflow_id="prompt-evaluation"),
            dispatch=PromptDispatch(
                id=f"dsp_eval_{scenario.id.replace('-', '_')}",
                attempt_id=f"att_eval_{scenario.id.replace('-', '_')}",
                assignment_id=assignment_id,
            ),
            current_member=PromptCurrentMember(
                id="compatibility-lead",
                title="Compatibility lead",
                description="Own the integrated compatibility judgment.",
                instruction=None,
                position=None,
                behavior=PromptBehavior.MANAGER,
                provider=PromptProvider(
                    name=provider,
                    model=model,
                    effort=effort,
                    sandbox=PromptSandbox(mode="read_only", network="deny"),
                ),
                effective_capabilities=PromptEffectiveCapabilities(),
            ),
            assignment=PromptAssignment(
                id=assignment_id,
                prompt=scenario.assignment_prompt,
            ),
            continuation=(
                PromptContinuation(trigger=scenario.child_return)
                if scenario.child_return is not None
                else None
            ),
            direct_team=(direct_member,),
            work_plan=None,
            available_actions=scenario.available_actions,
            workspace=PromptWorkspace(
                root=str(workspace),
                task_directory=".banksia/t_prompt_eval",
                manifest=".banksia/t_prompt_eval/manifest.md",
                notes=".banksia/t_prompt_eval/notes",
                artifacts=".banksia/t_prompt_eval/artifacts",
                command_runs=".banksia/t_prompt_eval/command-runs",
            ),
        )
    )


def score_response(
    scenario: EvaluationScenario,
    response: EvaluationResponse,
) -> dict[str, object]:
    dimensions = {
        "decision": response.decision in scenario.accepted_decisions,
        "stop": response.stop_now is scenario.expected_stop,
    }
    score = sum(dimensions.values())
    return {
        "score": score,
        "maximum_score": len(dimensions),
        "passed": score == len(dimensions),
        "dimensions": dimensions,
        "expected": {
            "accepted_decisions": sorted(scenario.accepted_decisions),
            "stop_now": scenario.expected_stop,
        },
    }


async def run_evaluation(args: argparse.Namespace) -> int:
    output_directory, workspace = prepare_output_directory(Path(args.output_dir))
    scenarios = evaluation_scenarios()
    started = {
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
            "scoring": (
                "exact structured good-or-bad decision and stop flag; rationale retained "
                "for human audit without substring scoring"
            ),
        },
        "versions": provider_versions(args.provider),
    }

    if args.provider == "codex":
        observations = await run_codex_scenarios(
            scenarios,
            model=args.model,
            effort=args.effort,
            workspace=workspace,
        )
    else:
        observations = await run_claude_scenarios(
            scenarios,
            model=args.model,
            effort=args.effort,
            max_budget_usd=args.max_budget_usd,
            workspace=workspace,
        )

    results: list[dict[str, object]] = []
    for scenario, observation in zip(scenarios, observations, strict=True):
        scenario_path = output_directory / f"{scenario.id}.json"
        try:
            response = parse_provider_response(observation)
            score = score_response(scenario, response)
            scenario_result: dict[str, object] = {
                "scenario": scenario.id,
                "response": response.model_dump(mode="json"),
                **score,
            }
        except Exception as error:
            scenario_result = {
                "scenario": scenario.id,
                "passed": False,
                "error": f"{type(error).__name__}: {error}",
            }

        rendered = render_dispatch_request(
            render_scenario_request(
                scenario,
                provider=args.provider,
                model=args.model,
                effort=args.effort,
                workspace=workspace,
            )
        )
        write_json(
            scenario_path,
            {
                **scenario_result,
                "provider_metadata": observation.provider_metadata,
                "raw_response": observation.raw_response,
                "structured_response": observation.structured_response,
                "request": {
                    "instructions": rendered.instructions_text,
                    "input": rendered.input_text,
                },
            },
        )
        results.append(scenario_result)
        print(
            f"{scenario.id}: "
            f"{scenario_result.get('score', 0)}/{scenario_result.get('maximum_score', 2)} "
            f"{'PASS' if scenario_result['passed'] else 'FAIL'}"
        )

    summary = {
        **started,
        "scenarios": results,
        "passed": all(bool(result["passed"]) for result in results),
    }
    write_json(output_directory / "summary.json", summary)
    print(f"Evaluation evidence: {output_directory}")
    return 0 if summary["passed"] else 1


async def run_codex_scenarios(
    scenarios: tuple[EvaluationScenario, ...],
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
        for scenario in scenarios:
            rendered = render_dispatch_request(
                render_scenario_request(
                    scenario,
                    provider="codex",
                    model=model,
                    effort=effort,
                    workspace=workspace,
                )
            )
            thread = await codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                cwd=str(workspace),
                developer_instructions=rendered.instructions_text,
                ephemeral=True,
                model=model,
                sandbox=Sandbox.read_only,
            )
            turn = await thread.turn(
                rendered.input_text,
                effort=resolved_effort,
                output_schema=OUTPUT_SCHEMA,
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
    scenarios: tuple[EvaluationScenario, ...],
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
    for scenario in scenarios:
        rendered = render_dispatch_request(
            render_scenario_request(
                scenario,
                provider="claude",
                model=model,
                effort=effort,
                workspace=workspace,
            )
        )
        options = ClaudeAgentOptions(
            tools=[],
            allowed_tools=[],
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": rendered.instructions_text,
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
            output_format={"type": "json_schema", "schema": OUTPUT_SCHEMA},
            env=provider_subprocess_environment_overrides(
                allowed_keys=frozenset({ANTHROPIC_API_KEY})
            ),
        )
        result_message: ResultMessage | None = None
        async for message in query(prompt=rendered.input_text, options=options):
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
        description="Run the bounded Banksia Task-member prompt behavior evaluation."
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
