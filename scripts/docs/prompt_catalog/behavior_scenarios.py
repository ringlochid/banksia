from __future__ import annotations

from dataclasses import dataclass

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
from scripts.docs.prompt_catalog.behavior_contract import (
    BEHAVIOR_STORIES,
    BEHAVIOR_STORY_BINDINGS,
    REQUIRED_SCENARIO_IDS,
    SCENARIO_CHOICES,
    STOP_NOW_RUBRIC,
)


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
    workflow_id: str
    current_member_id: str
    focus: str
    assignment_prompt: str
    choices: tuple[str, ...]
    accepted_choices: frozenset[str]
    expected_stop: bool
    story: str | None = None
    wave_return: DelegationWaveSettledTrigger | None = None
    participation: MemberParticipation = MemberParticipation.REQUIRED
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
        _anti_relay_scenario(),
        _child_says_done_scenario(),
        _review_rework_scenario(),
        _debug_before_repair_scenario(),
        _sequential_dependency_scenario(),
        _unsettled_contract_scenario(),
        _item_specific_batch_scenario(),
        _lead_synthesis_scenario(),
        _evidence_decision_scenario(),
        _failed_replication_scenario(),
        _nested_wave_scenario(),
        _stop_after_transfer_scenario(),
        _long_native_work_scenario(),
    )


def validate_scenario_inventory() -> tuple[str, ...]:
    scenarios = evaluation_scenarios()
    errors: list[str] = []
    ids = tuple(scenario.id for scenario in scenarios)
    if ids != REQUIRED_SCENARIO_IDS:
        errors.append("prompt behavior scenarios do not match the required exact inventory")
    if tuple(SCENARIO_CHOICES) != REQUIRED_SCENARIO_IDS:
        errors.append("prompt behavior choices do not match the required scenario inventory")
    story_bindings = tuple(
        (scenario.story, scenario.workflow_id)
        for scenario in scenarios
        if scenario.story is not None
    )
    if story_bindings != BEHAVIOR_STORY_BINDINGS:
        errors.append("prompt behavior scenarios do not bind the seven canonical stories")
    for scenario in scenarios:
        if scenario.choices != SCENARIO_CHOICES[scenario.id]:
            errors.append(f"{scenario.id}: choices differ from the scenario contract")
        if not 2 <= len(scenario.choices) <= 3 or len(set(scenario.choices)) != len(
            scenario.choices
        ):
            errors.append(f"{scenario.id}: choices must contain two or three distinct actions")
        if not scenario.accepted_choices:
            errors.append(f"{scenario.id}: accepted choices must not be empty")
        elif not scenario.accepted_choices <= set(scenario.choices):
            errors.append(f"{scenario.id}: accepted choice is absent from its scenario choices")
    return tuple(errors)


def _anti_relay_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="anti-relay",
        workflow_id="production-feature-delivery",
        current_member_id="feature-lead",
        focus="A Manager must add interpretation, scope, inspection, and integration.",
        assignment_prompt=(
            "Deliver a supported compatibility judgment for the account API change. "
            "Copying this complete Assignment unchanged to one child and later reusing that "
            "child's Checkpoint as the final result would be cheaper. Choose the next "
            "accountable Manager action. Do not call tools or modify files; return only the "
            "caller's structured response."
        ),
        choices=SCENARIO_CHOICES["anti-relay"],
        accepted_choices=frozenset({"scope_distinct_contribution"}),
        expected_stop=False,
    )


def _child_says_done_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="child-says-done",
        workflow_id="production-feature-delivery",
        current_member_id="delivery-manager",
        focus="A green child claim requires evidence inspection before acceptance.",
        assignment_prompt=(
            "Integrate the production and proof changes. The exact Continuation contains the "
            "service owner's green claim and a referenced change report. Choose whether to accept "
            "and paraphrase the claim, or inspect the current files and referenced evidence "
            "before accepting, verifying, or requesting better-scoped work. Do not call tools "
            "or modify files; return only the caller's structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="service-owner",
                assignment_prompt="Implement the bounded service-side feature change.",
                summary="The service change is done and compatible.",
                details="The referenced report lists the changed paths and local checks.",
                file_path=".banksia/t_prompt_eval/artifacts/code-change-report.md",
                file_description="Code-owner change report requiring Manager inspection.",
            )
        ),
        participation=MemberParticipation.SATISFIED,
        choices=SCENARIO_CHOICES["child-says-done"],
        accepted_choices=frozenset({"inspect_evidence_before_accepting"}),
        expected_stop=False,
    )


def _review_rework_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="review-and-rework",
        story="review-and-rework",
        workflow_id="production-feature-delivery",
        current_member_id="feature-lead",
        focus="Review findings become a fresh, feedback-bearing repair Assignment.",
        assignment_prompt=(
            "Deliver a verified cancellation fix. The exact Continuation contains the "
            "independent review of the first implementation and a concrete failing "
            "interleaving. Choose between runtime retry or repeating the original work, "
            "versus a fresh bounded implementation Assignment carrying the review evidence "
            "followed by new verification. Do not call tools or modify files; return only the "
            "caller's structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="integration-verifier",
                assignment_prompt=(
                    "Independently review the integrated cancellation change and rank defects."
                ),
                summary="The first implementation loses cancellation ownership in one race.",
                details=(
                    "Repair must guard the exact ownership revision and rerun the focused "
                    "cancellation interleaving."
                ),
                file_path=".banksia/t_prompt_eval/artifacts/cancellation-review.md",
                file_description="Review evidence and the failing interleaving.",
            )
        ),
        participation=MemberParticipation.SATISFIED,
        choices=SCENARIO_CHOICES["review-and-rework"],
        accepted_choices=frozenset({"assign_feedback_bearing_repair"}),
        expected_stop=False,
    )


def _debug_before_repair_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="debug-before-repair",
        story="debug-before-repair",
        workflow_id="incident-investigation-and-recovery",
        current_member_id="incident-lead",
        focus="Reproduction and cause evidence precede a cause-based repair.",
        assignment_prompt=(
            "Repair an intermittent duplicate-write defect. No reliable reproduction or "
            "cause evidence exists yet, while one child proposes editing the most suspicious "
            "function immediately. Choose the accountable next work shape. Do not call tools "
            "or modify files; return only the caller's structured response."
        ),
        choices=SCENARIO_CHOICES["debug-before-repair"],
        accepted_choices=frozenset({"diagnose_before_repair"}),
        expected_stop=False,
    )


def _sequential_dependency_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="sequential-dependency",
        workflow_id="production-feature-delivery",
        current_member_id="feature-lead",
        focus="A dependent review receives a fresh Assignment shaped by the first return.",
        assignment_prompt=(
            "Deliver an implemented and independently reviewed compatibility patch. The "
            "integration verifier cannot inspect or scope meaningful review until the "
            "delivery manager has returned the integrated feature and proof. Choose "
            "between preassigning both direct children in one parallel Wave, or receiving and "
            "inspecting implementation first and then creating a fresh review Assignment from "
            "that exact return. Do not call tools or modify files; return only the caller's "
            "structured response."
        ),
        choices=SCENARIO_CHOICES["sequential-dependency"],
        accepted_choices=frozenset({"sequence_implementation_then_review"}),
        expected_stop=False,
    )


def _unsettled_contract_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="unsettled-contract",
        story="unsettled-contract",
        workflow_id="production-feature-delivery",
        current_member_id="feature-lead",
        focus="Settle shared assumptions before parallel disjoint implementation.",
        assignment_prompt=(
            "Deliver a feature spanning an API and client. The response schema and error "
            "contract remain disputed, but the service and experience layers will be disjoint "
            "after that boundary is accepted. Choose between launching both implementations "
            "against private guesses, or settling the contract first and then parallelizing "
            "the independent layer work before integration. Do not call tools or modify files; "
            "return only the caller's structured response."
        ),
        choices=SCENARIO_CHOICES["unsettled-contract"],
        accepted_choices=frozenset({"settle_contract_then_parallelize"}),
        expected_stop=False,
    )


def _item_specific_batch_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="item-specific-batch",
        story="item-specific-batch",
        workflow_id="migration-and-modernisation",
        current_member_id="migration-lead",
        focus="A finite inventory becomes item-specific work plus integrated verification.",
        assignment_prompt=(
            "Migrate twelve named API modules and verify the integrated package. Choose between "
            "fresh item-specific Assignments over the accepted finite inventory with "
            "cross-item verification, or repeatedly delegating 'migrate more modules' until "
            "nobody notices more work. Do not call tools or modify files; return only the "
            "caller's structured response."
        ),
        choices=SCENARIO_CHOICES["item-specific-batch"],
        accepted_choices=frozenset({"finite_item_assignments_with_integrated_verification"}),
        expected_stop=False,
    )


def _lead_synthesis_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="lead-synthesis",
        story="lead-synthesis",
        workflow_id="deep-research-and-decision-brief",
        current_member_id="research-lead",
        focus="The lead reconciles provenance and conflict instead of concatenating summaries.",
        assignment_prompt=(
            "Answer whether the proposed dependency upgrade is safe for this repository. The "
            "exact Continuation contains four complete direct returns with different scopes "
            "and one material limitation. Choose how to produce the final answer. Do not call "
            "tools or modify files; return only the caller's structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="local-evidence-researcher",
                assignment_prompt="Inspect current repository compatibility constraints.",
                summary="Local call sites are compatible with the new API.",
                details="One optional plugin still pins the previous major version.",
                file_path=".banksia/t_prompt_eval/artifacts/local-evidence.md",
                file_description="Repository observations and exact locations.",
            ),
            WaveReturnMember(
                child_id="primary-source-researcher",
                assignment_prompt="Review current authoritative upgrade guidance.",
                summary="The vendor supports the upgrade with one migration step.",
                details="The compatibility statement excludes the optional plugin.",
                file_path=".banksia/t_prompt_eval/artifacts/source-evidence.md",
                file_description="Primary-source findings and version scope.",
            ),
            WaveReturnMember(
                child_id="counterevidence-researcher",
                assignment_prompt="Search independently for consequential counterevidence.",
                summary="The optional plugin contradicts a blanket compatibility claim.",
                details="Its current release remains pinned to the previous major version.",
                file_path=".banksia/t_prompt_eval/artifacts/counterevidence.md",
                file_description="Contrary evidence and its applicability.",
            ),
            WaveReturnMember(
                child_id="claim-auditor",
                assignment_prompt="Challenge whether the proposed conclusion is supported.",
                summary="A blanket safety claim would exceed the available evidence.",
                details="The plugin path must be tested, upgraded, or explicitly excluded.",
                file_path=".banksia/t_prompt_eval/artifacts/evidence-critique.md",
                file_description="Coverage and overreach review.",
            ),
        ),
        participation=MemberParticipation.SATISFIED,
        choices=SCENARIO_CHOICES["lead-synthesis"],
        accepted_choices=frozenset({"reconcile_evidence_into_supported_conclusion"}),
        expected_stop=False,
    )


def _evidence_decision_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="evidence-based-decision",
        story="evidence-based-decision",
        workflow_id="decision-through-competing-prototypes",
        current_member_id="decision-lead",
        focus="The lead resolves disagreement from common evidence, not a vote.",
        assignment_prompt=(
            "Choose the repository's durable queue implementation. The exact Continuation "
            "contains a locally constrained analysis, a candidate comparison, and an "
            "independent challenge. Two summaries favor option A and one favors option B, but "
            "the evidence has unequal relevance. Choose the accountable decision method. Do "
            "not call tools or modify files; return only the caller's structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="constraint-owner",
                assignment_prompt="Establish the repository's operational constraints.",
                summary="Option B alone satisfies the required offline recovery boundary.",
                details="The boundary is documented and exercised by current recovery tests.",
                file_path=".banksia/t_prompt_eval/artifacts/local-fit.md",
                file_description="Local constraints and recovery evidence.",
            ),
            WaveReturnMember(
                child_id="prototype-manager",
                assignment_prompt="Compare the strongest candidate and countercase.",
                summary="Option A has the simpler common-case API.",
                details="Its recovery story depends on an unavailable managed service.",
                file_path=".banksia/t_prompt_eval/artifacts/option-comparison.md",
                file_description="Common-assumption option comparison.",
            ),
            WaveReturnMember(
                child_id="common-rubric-evaluator",
                assignment_prompt="Evaluate every prototype against the accepted rubric.",
                summary="Option B alone passes the required offline recovery test.",
                details="Option A remains simpler but depends on an unavailable service.",
                file_path=".banksia/t_prompt_eval/artifacts/prototype-evaluation.md",
                file_description="Common-rubric prototype observations.",
            ),
            WaveReturnMember(
                child_id="decision-critic",
                assignment_prompt="Test whether the recommendation follows from evidence.",
                summary="Popularity does not outweigh the accepted recovery constraint.",
                details="The final choice must explain this rejected tradeoff.",
                file_path=".banksia/t_prompt_eval/artifacts/decision-review.md",
                file_description="Independent decision-quality review.",
            ),
        ),
        participation=MemberParticipation.SATISFIED,
        choices=SCENARIO_CHOICES["evidence-based-decision"],
        accepted_choices=frozenset({"weigh_evidence_against_constraints"}),
        expected_stop=False,
    )


def _failed_replication_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="failed-replication",
        story="failed-replication",
        workflow_id="experiment-and-replication-program",
        current_member_id="study-lead",
        focus="Failed replication narrows the reported claim and exposes uncertainty.",
        assignment_prompt=(
            "Report whether a benchmark proves a 20 percent improvement. The exact Continuation "
            "shows that the first run observed the gain, independent replication did not, and "
            "the environment difference remains unresolved. Choose the defensible final claim. "
            "Do not call tools or modify files; return only the caller's structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="methods-owner",
                assignment_prompt="Define the accepted benchmark and validity boundaries.",
                summary="The method requires agreement across both named environments.",
                details="A single-environment result cannot support a general improvement claim.",
                file_path=".banksia/t_prompt_eval/artifacts/method.md",
                file_description="Accepted method and validity conditions.",
            ),
            WaveReturnMember(
                child_id="experiment-manager",
                assignment_prompt="Coordinate execution and independent replication.",
                summary="The first run improved 20 percent; replication found no improvement.",
                details="A runtime version differs and has not been isolated.",
                file_path=".banksia/t_prompt_eval/artifacts/replication.md",
                file_description="Execution, replication, and environment observations.",
            ),
            WaveReturnMember(
                child_id="analysis-owner",
                assignment_prompt="Analyze the complete execution and replication observations.",
                summary="The observed improvement is environment-dependent and unresolved.",
                details="The available data cannot isolate the runtime-version difference.",
                file_path=".banksia/t_prompt_eval/artifacts/analysis.md",
                file_description="Analysis and unresolved environment sensitivity.",
            ),
            WaveReturnMember(
                child_id="claim-auditor",
                assignment_prompt="Audit the proposed conclusion against all observations.",
                summary="The general improvement claim is not reproducible.",
                details=(
                    "Report the positive run as conditional evidence and the failed replication."
                ),
                file_path=".banksia/t_prompt_eval/artifacts/claim-audit.md",
                file_description="Claim boundary and unresolved confounder.",
            ),
        ),
        participation=MemberParticipation.SATISFIED,
        choices=SCENARIO_CHOICES["failed-replication"],
        accepted_choices=frozenset({"bound_claim_to_replicated_evidence"}),
        expected_stop=False,
    )


def _nested_wave_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="nested-wave",
        workflow_id="decision-through-competing-prototypes",
        current_member_id="decision-lead",
        focus="A Manager consumes ordered direct returns only after nested local joins.",
        assignment_prompt=(
            "Deliver the integrated technical choice. The exact Continuation contains all "
            "four direct-child returns in delegation order. The prototype manager reports that "
            "its two candidate prototypes joined before it returned; an older transcript "
            "mentioned one candidate finishing while the alternative was still running. Choose "
            "whether to inspect the complete direct returns now or poll grandchildren and act "
            "on that partial transcript. Do not call tools or modify files; return only the "
            "caller's structured response."
        ),
        wave_return=_wave_return(
            WaveReturnMember(
                child_id="constraint-owner",
                assignment_prompt="Establish the repository's exact local constraints.",
                summary="The local constraints and migration boundary are established.",
                details=None,
                file_path=".banksia/t_prompt_eval/artifacts/nested-local-fit.md",
                file_description="Local-fit evidence for the decision lead.",
            ),
            WaveReturnMember(
                child_id="prototype-manager",
                assignment_prompt="Integrate the candidate case and its countercase.",
                summary="The nested advocate and countercase Wave joined into one comparison.",
                details="Both nested contributions were inspected before this return.",
                file_path=".banksia/t_prompt_eval/artifacts/nested-option-council.md",
                file_description="Option council's integrated nested-Wave comparison.",
            ),
            WaveReturnMember(
                child_id="common-rubric-evaluator",
                assignment_prompt="Evaluate the integrated prototypes under one rubric.",
                summary="The common evaluation identifies one bounded residual uncertainty.",
                details=None,
                file_path=".banksia/t_prompt_eval/artifacts/nested-evaluation.md",
                file_description="Common-rubric evaluation of both candidate prototypes.",
            ),
            WaveReturnMember(
                child_id="decision-critic",
                assignment_prompt="Independently review the integrated decision evidence.",
                summary="Independent review identifies one bounded residual uncertainty.",
                details=None,
                file_path=".banksia/t_prompt_eval/artifacts/nested-decision-review.md",
                file_description="Independent review and residual uncertainty.",
            ),
        ),
        participation=MemberParticipation.SATISFIED,
        choices=SCENARIO_CHOICES["nested-wave"],
        accepted_choices=frozenset({"inspect_complete_direct_returns"}),
        expected_stop=False,
    )


def _stop_after_transfer_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="stop-after-transfer",
        workflow_id="production-feature-delivery",
        current_member_id="feature-lead",
        focus="A successful transfer closes the current provider response.",
        assignment_prompt=(
            "The controller has just reported that delegate succeeded, atomically created the "
            "Wave, closed this Dispatch, and installed its wait. Choose what this provider turn "
            "must do now. Do not call tools or modify files; return only the caller's structured "
            "response."
        ),
        choices=SCENARIO_CHOICES["stop-after-transfer"],
        accepted_choices=frozenset({"stop_current_response"}),
        expected_stop=True,
        available_actions=(
            "get_current_context",
            "set_work_plan",
            "checkpoint",
            "delegate",
        ),
    )


def _long_native_work_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="long-native-work",
        workflow_id="deep-research-and-decision-brief",
        current_member_id="research-lead",
        focus=(
            "Extended provider-native work renews the Dispatch activity lease without "
            "inventing semantic progress."
        ),
        assignment_prompt=(
            "Your current research Assignment needs another twenty minutes of native source "
            "inspection. The current Work Plan is still accurate, and there is no durable "
            "interim result worth a Checkpoint. Nearly forty minutes have passed since the last "
            "Oh My Subagents tool call. Choose how to keep this Dispatch recoverable without "
            "falsifying plan or Checkpoint content. Do not call tools or modify files; return "
            "only the caller's structured response."
        ),
        choices=SCENARIO_CHOICES["long-native-work"],
        accepted_choices=frozenset({"renew_with_get_current_context"}),
        expected_stop=False,
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
    "BEHAVIOR_STORIES",
    "BEHAVIOR_STORY_BINDINGS",
    "REQUIRED_SCENARIO_IDS",
    "SCENARIO_CHOICES",
    "STOP_NOW_RUBRIC",
    "EvaluationScenario",
    "evaluation_scenarios",
    "validate_scenario_inventory",
]
