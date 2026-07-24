from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from banksia.runtime.contracts.primitives import CheckpointOutcome
from banksia.runtime.contracts.prompt import (
    DelegationWaveMemberResult,
    DelegationWaveSettledResult,
    DelegationWaveSettledSource,
    DelegationWaveSettledTrigger,
    PromptAssignment,
    PromptCheckpointSummary,
)
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.team_read import MemberParticipation

DECISIONS = (
    "scope_distinct_child_contribution_or_remove_child",
    "forward_assignment_and_relay_checkpoint",
    "inspect_evidence_before_accepting",
    "accept_child_green_without_inspection",
    "resolve_disagreement_from_evidence",
    "concatenate_conflicting_summaries",
    "sequence_dependent_work_with_fresh_followup_assignment",
    "parallelize_dependent_implementation_and_review",
    "plan_disjoint_parallel_contributions_then_integrate",
    "parallelize_overlapping_high_value_writes",
    "inspect_ordered_direct_returns_after_local_joins",
    "poll_nested_children_or_act_on_partial_return",
    "plan_fresh_feedback_bearing_repair_assignment",
    "runtime_retry_or_repeat_original_assignment_after_review",
    "scope_finite_batch_assignments_and_integrated_verification",
    "delegate_unbounded_repetitive_batch",
    "stop_current_response",
    "continue_work_or_poll_after_transfer",
)
STOP_NOW_RUBRIC = (
    "For this evaluation response, stop_now is true only when the scenario says a controller "
    "operation already succeeded and closed or suspended this Dispatch before this response. "
    "The end of this bounded answer is not a transfer, and a proposed future action has not "
    "transferred authority yet."
)
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "stop_now": {
            "type": "boolean",
            "description": STOP_NOW_RUBRIC,
        },
        "rationale": {"type": "string", "minLength": 1, "maxLength": 1_000},
    },
    "required": ["decision", "stop_now", "rationale"],
}


@dataclass(frozen=True, slots=True)
class WaveReturnMember:
    child_id: str
    assignment_prompt: str
    summary: str
    details: str | None
    file_path: str
    file_description: str


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    id: str
    assignment_prompt: str
    accepted_decisions: frozenset[str]
    expected_stop: bool
    wave_return: DelegationWaveSettledTrigger | None = None
    participation: MemberParticipation = MemberParticipation.REQUIRED
    direct_team_ids: tuple[str, ...] = ("reviewer",)
    available_actions: tuple[str, ...] = (
        "get_current_context",
        "set_work_plan",
        "checkpoint",
        "add_child",
        "update_child",
        "remove_child",
        "delegate",
    )


def evaluation_scenarios() -> tuple[EvaluationScenario, ...]:
    return (
        _relay_trap_scenario(),
        _inspect_before_accept_scenario(),
        _contradictory_returns_scenario(),
        _sequential_dependency_scenario(),
        _safe_parallelism_scenario(),
        _nested_collect_all_scenario(),
        _implement_review_repair_scenario(),
        _bounded_batch_scope_scenario(),
        _stop_after_transfer_scenario(),
    )


def _relay_trap_scenario() -> EvaluationScenario:
    return EvaluationScenario(
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
    )


def _inspect_before_accept_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="inspect-before-accept",
        assignment_prompt=(
            "Deliver the final compatibility judgment for the timeout change. The exact "
            "Continuation contains the implementation child's green return and its referenced "
            "review file. Choose the next accountable Manager action for this bounded decision "
            "exercise. Do not call tools or modify files; return only the caller's structured "
            "response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="reviewer",
                assignment_prompt=(
                    "Inspect the timeout implementation and report whether its public behavior "
                    "remains compatible."
                ),
                summary="The timeout implementation is done and compatible.",
                details=None,
                file_path=".banksia/t_prompt_eval/artifacts/timeout-review.md",
                file_description="Child-authored compatibility review to inspect.",
            )
        ),
        participation=MemberParticipation.SATISFIED,
        accepted_decisions=frozenset({"inspect_evidence_before_accepting"}),
        expected_stop=False,
    )


def _contradictory_returns_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="contradictory-returns",
        assignment_prompt=(
            "Deliver the final compatibility judgment for the timeout change. An earlier "
            "sequential child review reported that the default change is breaking and cited "
            ".banksia/t_prompt_eval/artifacts/first-review.md. The exact current Continuation "
            "contains a second child return claiming the same change is compatible. Choose the "
            "next accountable Manager action for this bounded decision exercise. Do not call "
            "tools or modify files; return only the caller's structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="reviewer",
                assignment_prompt=(
                    "Independently review the timeout default for public compatibility."
                ),
                summary="The timeout default remains fully compatible.",
                details="No breaking behavior was found.",
                file_path=".banksia/t_prompt_eval/artifacts/second-review.md",
                file_description="Second independent compatibility review.",
            )
        ),
        participation=MemberParticipation.SATISFIED,
        accepted_decisions=frozenset(
            {
                "inspect_evidence_before_accepting",
                "resolve_disagreement_from_evidence",
            }
        ),
        expected_stop=False,
    )


def _sequential_dependency_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="sequential-dependency",
        assignment_prompt=(
            "Deliver an implemented and independently reviewed compatibility patch. The "
            "reviewer cannot scope a meaningful review until the implementer has returned the "
            "exact patch and verification evidence. Choose between preassigning both children "
            "in one parallel Wave or first using a one-member implementation Wave, inspecting "
            "that return, and then creating a fresh reviewer Assignment shaped by it. Do not "
            "call tools or modify files; return only the caller's structured response."
        ),
        accepted_decisions=frozenset({"sequence_dependent_work_with_fresh_followup_assignment"}),
        expected_stop=False,
        direct_team_ids=("implementer", "reviewer"),
    )


def _safe_parallelism_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="safe-parallelism",
        assignment_prompt=(
            "Deliver one integrated compatibility assessment. The API reader can inspect "
            "runtime behavior while the documentation reader independently checks published "
            "promises; both contributions are read-only and use disjoint evidence until your "
            "integration. A competing proposal asks two children to edit the same public "
            "schema concurrently. Choose the accountable Manager work shape. Do not call "
            "tools or modify files; return only the caller's structured response."
        ),
        accepted_decisions=frozenset({"plan_disjoint_parallel_contributions_then_integrate"}),
        expected_stop=False,
        direct_team_ids=("api-reader", "documentation-reader"),
    )


def _nested_collect_all_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="nested-collect-all",
        assignment_prompt=(
            "Deliver the integrated release judgment. The exact current Continuation contains "
            "both direct-child returns in delegation order. The implementation lead reports "
            "that its own nested E/F Wave fully joined before it returned; an older provider "
            "transcript mentioned E finishing while F was still running. Choose whether to "
            "inspect both complete direct returns now or poll grandchildren/use that partial "
            "transcript. Do not call tools or modify files; return only the caller's "
            "structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="implementation-lead",
                assignment_prompt=(
                    "Coordinate the implementation subtree, integrate E and F, and return one "
                    "verified contribution."
                ),
                summary="The nested implementation Wave joined and the patch is integrated.",
                details="Both nested contributions were inspected before this return.",
                file_path=".banksia/t_prompt_eval/artifacts/integrated-patch-review.md",
                file_description="Implementation lead's integrated nested-Wave evidence.",
            ),
            WaveReturnMember(
                child_id="independent-reviewer",
                assignment_prompt=(
                    "Independently review the integrated release candidate without editing."
                ),
                summary="Independent review found one documented residual risk.",
                details="The risk does not invalidate the patch but must inform release judgment.",
                file_path=".banksia/t_prompt_eval/artifacts/independent-review.md",
                file_description="Independent release review and residual-risk evidence.",
            ),
        ),
        participation=MemberParticipation.SATISFIED,
        accepted_decisions=frozenset({"inspect_ordered_direct_returns_after_local_joins"}),
        expected_stop=False,
        direct_team_ids=("implementation-lead", "independent-reviewer"),
    )


def _implement_review_repair_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="implement-review-repair",
        assignment_prompt=(
            "Deliver a verified concurrency fix. The exact Continuation contains the "
            "reviewer's completed assessment of the first implementation and concrete failure "
            "evidence. Choose between runtime retry/repeating the original implementation "
            "prompt or a fresh implementer Assignment that carries the review feedback and is "
            "followed by new verification. Do not call tools or modify files; return only the "
            "caller's structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="reviewer",
                assignment_prompt=(
                    "Review the first concurrency implementation independently and report "
                    "actionable defects."
                ),
                summary="The first implementation loses cancellation ownership in one race.",
                details=(
                    "Repair must guard the exact ownership revision and rerun the focused "
                    "cancellation interleaving."
                ),
                file_path=".banksia/t_prompt_eval/artifacts/concurrency-review.md",
                file_description="Concrete review feedback and failing interleaving.",
            )
        ),
        participation=MemberParticipation.SATISFIED,
        accepted_decisions=frozenset({"plan_fresh_feedback_bearing_repair_assignment"}),
        expected_stop=False,
        direct_team_ids=("implementer", "reviewer"),
    )


def _bounded_batch_scope_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="bounded-batch-scope",
        assignment_prompt=(
            "Migrate the twelve explicitly named API modules in the Assignment inventory and "
            "verify the integrated package. The batch worker can receive fresh item-specific "
            "Assignments in finite Waves; the verifier owns final cross-item checks. Choose "
            "between that bounded map with stable per-item scope and integrated verification, "
            "or repeatedly delegating the generic instruction 'migrate more modules' until no "
            "work is noticed. Do not call tools or modify files; return only the caller's "
            "structured response."
        ),
        accepted_decisions=frozenset(
            {"scope_finite_batch_assignments_and_integrated_verification"}
        ),
        expected_stop=False,
        direct_team_ids=("batch-worker", "verifier"),
    )


def _stop_after_transfer_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="stop-after-transfer",
        assignment_prompt=(
            "The controller has just reported that delegate succeeded, atomically created "
            "the Wave, closed this Dispatch, and installed its wait. Choose what this "
            "provider turn must do now. Do not call tools or modify files; return only the "
            "caller's structured response."
        ),
        accepted_decisions=frozenset({"stop_current_response"}),
        expected_stop=True,
        available_actions=(
            "get_current_context",
            "set_work_plan",
            "checkpoint",
            "delegate",
        ),
    )


def _wave_return(
    *members: WaveReturnMember,
) -> DelegationWaveSettledTrigger:
    results: list[DelegationWaveMemberResult] = []
    for member in members:
        identifier = member.child_id.replace("-", "_")
        file_reference = FileReference(
            path=member.file_path,
            description=member.file_description,
        )
        results.append(
            DelegationWaveMemberResult(
                child_id=member.child_id,
                assignment=PromptAssignment(
                    id=f"asn_{identifier}_prompt_eval",
                    prompt=member.assignment_prompt,
                    files=(file_reference,),
                ),
                outcome=CheckpointOutcome.GREEN,
                checkpoint=PromptCheckpointSummary(
                    id=f"cp_{identifier}_prompt_eval",
                    summary=member.summary,
                    details=member.details,
                    files=(file_reference,),
                    outcome=CheckpointOutcome.GREEN,
                ),
            )
        )
    return DelegationWaveSettledTrigger(
        source=DelegationWaveSettledSource(
            delegation_wave_id="wave_prompt_eval",
            source_dispatch_id="dsp_child_prompt_eval",
        ),
        result=DelegationWaveSettledResult(members=tuple(results)),
    )


__all__ = [
    "DECISIONS",
    "OUTPUT_SCHEMA",
    "STOP_NOW_RUBRIC",
    "EvaluationScenario",
    "evaluation_scenarios",
]
