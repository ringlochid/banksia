"""Shared task-member prompt fixtures for unit and integration proof."""

from __future__ import annotations

from typing import Literal

from oh_my_subagents.runtime.contracts import FileReference
from oh_my_subagents.runtime.contracts.primitives import CheckpointOutcome, HumanRequestKind
from oh_my_subagents.runtime.contracts.prompt import (
    DelegationWaveMemberResult,
    DelegationWaveSettledResult,
    DelegationWaveSettledSource,
    DelegationWaveSettledTrigger,
    DispatchRequestRenderInput,
    PromptAssignment,
    PromptCheckpointSummary,
    PromptContinuation,
    PromptDispatch,
    PromptDynamicInput,
    PromptTask,
    PromptWorkspace,
)
from oh_my_subagents.runtime.contracts.team_read import (
    CurrentMemberRead,
    DirectTeamMemberRead,
    EffectiveCapabilitiesRead,
    MemberAvailability,
    MemberBehavior,
    MemberParticipation,
    ResolvedProviderRead,
    ResolvedSandboxRead,
)
from oh_my_subagents.runtime.work_plan import WorkPlanStepRead, WorkPlanStepStatus, WorkPlanView
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID

type HumanRequestKindValue = Literal["input", "direction", "approval", "review"]
type CommandRunCapability = Literal["allow", "deny"]


def sample_dynamic_input(
    *,
    manager: bool = False,
    task_lead: bool = False,
    continuation: bool = False,
    assignment_prompt: str = "Inspect and fix the exact issue.",
    provider_kind: str = "codex",
    human_request: tuple[HumanRequestKindValue, ...] = (),
    command_run: CommandRunCapability = "deny",
) -> PromptDynamicInput:
    capabilities = EffectiveCapabilitiesRead(
        human_request=tuple(HumanRequestKind(kind) for kind in human_request),
        command_run=command_run,
    )
    direct_team = _sample_direct_team(manager)
    return PromptDynamicInput(
        task=PromptTask(id="t_7m4k2d9x", workflow_id=GENERIC_WORKFLOW_ID),
        dispatch=PromptDispatch(
            id="dsp_123",
            attempt_id="att_123",
            assignment_id="asn_123",
        ),
        current_member=CurrentMemberRead(
            id="lead" if task_lead else "implementation",
            title="Delivery lead" if task_lead else "Implementation",
            description="Own the current result.",
            instruction="Preserve public compatibility.",
            position="task_lead" if task_lead else None,
            behavior=MemberBehavior.MANAGER if manager else MemberBehavior.CONTRIBUTOR,
            provider=ResolvedProviderRead(
                kind=provider_kind,
                model="gpt-5.6",
                effort="high",
                sandbox=ResolvedSandboxRead(mode="workspace_write", network="deny"),
            ),
            effective_capabilities=capabilities,
        ),
        assignment=PromptAssignment(
            id="asn_123",
            prompt=assignment_prompt,
            files=(
                FileReference(
                    path=".oms/t_7m4k2d9x/artifacts/review.md",
                    description="Inspect this review before deciding.",
                ),
            ),
        ),
        continuation=(PromptContinuation(trigger=sample_wave_return()) if continuation else None),
        direct_team=direct_team,
        work_plan=WorkPlanView(
            explanation="Keep the review independent.",
            steps=(
                WorkPlanStepRead(
                    step="Inspect the bounded change.",
                    status=WorkPlanStepStatus.IN_PROGRESS,
                ),
            ),
        ),
        available_actions=_sample_actions(
            manager=manager,
            human_request=human_request,
            command_run=command_run,
        ),
        workspace=PromptWorkspace(
            root="/work/acme",
            task_directory=".oms/t_7m4k2d9x",
            manifest=".oms/t_7m4k2d9x/manifest.md",
            workflow_note=".oms/t_7m4k2d9x/workflow-note.md",
            notes=".oms/t_7m4k2d9x/notes",
            artifacts=".oms/t_7m4k2d9x/artifacts",
            command_runs=".oms/t_7m4k2d9x/command-runs",
        ),
    )


def _sample_direct_team(manager: bool) -> tuple[DirectTeamMemberRead, ...]:
    if not manager:
        return ()
    return (
        DirectTeamMemberRead(
            id="reviewer",
            title="Independent reviewer",
            description="Review the bounded result.",
            instruction="Challenge consequential claims.",
            provider=ResolvedProviderRead(kind="claude"),
            capabilities=EffectiveCapabilitiesRead(),
            participation=MemberParticipation.REQUIRED,
            availability=MemberAvailability.AVAILABLE,
        ),
    )


def _sample_actions(
    *,
    manager: bool,
    human_request: tuple[HumanRequestKindValue, ...],
    command_run: CommandRunCapability,
) -> tuple[str, ...]:
    actions = ["get_current_context", "set_work_plan", "checkpoint"]
    if manager:
        actions.append("delegate")
    actions.append("add_child")
    if manager:
        actions.extend(("update_child", "remove_child"))
    if human_request:
        actions.append("open_human_request")
    if command_run == "allow":
        actions.append("start_command_run")
    return tuple(actions)


def sample_wave_return() -> DelegationWaveSettledTrigger:
    return DelegationWaveSettledTrigger(
        source=DelegationWaveSettledSource(
            delegation_wave_id="wave_123",
            source_dispatch_id="dsp_child",
        ),
        result=DelegationWaveSettledResult(
            members=(
                DelegationWaveMemberResult(
                    child_id="reviewer",
                    assignment=PromptAssignment(
                        id="asn_child",
                        prompt="Review the exact implementation.",
                        files=(
                            FileReference(
                                path="src/change.py",
                                description="Changed source.",
                            ),
                        ),
                    ),
                    outcome=CheckpointOutcome.GREEN,
                    checkpoint=PromptCheckpointSummary(
                        id="cp_123",
                        summary="The bounded review is complete.",
                        details="One residual risk remains documented.",
                        files=(
                            FileReference(
                                path=".oms/t_7m4k2d9x/artifacts/review.md",
                                description="Independent review.",
                            ),
                        ),
                        outcome=CheckpointOutcome.GREEN,
                    ),
                ),
            ),
        ),
    )


def sample_request(
    *,
    manager: bool = False,
    task_lead: bool = False,
    continuation: bool = False,
    assignment_prompt: str = "Inspect and fix the exact issue.",
    provider_kind: str = "codex",
    human_request: tuple[HumanRequestKindValue, ...] = (),
    command_run: CommandRunCapability = "deny",
) -> DispatchRequestRenderInput:
    return DispatchRequestRenderInput(
        dynamic_input=sample_dynamic_input(
            manager=manager,
            task_lead=task_lead,
            continuation=continuation,
            assignment_prompt=assignment_prompt,
            provider_kind=provider_kind,
            human_request=human_request,
            command_run=command_run,
        ),
        member_instruction="Preserve the public API.",
        workflow_note="Treat public API changes as an explicit non-goal.",
    )
