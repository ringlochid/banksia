from __future__ import annotations

from banksia.runtime.contracts import FileReference
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
from banksia.runtime.work_plan import WorkPlanStepRead, WorkPlanStepStatus, WorkPlanView


def sample_dynamic_input(
    *,
    manager: bool = False,
    task_lead: bool = False,
    continuation: bool = False,
    assignment_prompt: str = "Inspect and fix the exact issue.",
    provider_name: str = "codex",
    human_request: tuple[str, ...] = (),
    command_run: str = "deny",
) -> PromptDynamicInput:
    capabilities = PromptEffectiveCapabilities(
        human_request=human_request,
        command_run=command_run,
    )
    direct_team = (
        (
            PromptDirectMember(
                id="reviewer",
                title="Independent reviewer",
                description="Review the bounded result.",
                instruction="Challenge consequential claims.",
                provider=PromptProvider(name="claude"),
                capabilities=PromptEffectiveCapabilities(),
                participation=PromptParticipation.REQUIRED,
                availability=PromptAvailability.AVAILABLE,
            ),
        )
        if manager
        else ()
    )
    actions = ["get_current_context", "set_work_plan", "checkpoint", "add_child"]
    if manager:
        actions.extend(("update_child", "remove_child", "assign_child"))
    if human_request:
        actions.append("open_human_request")
    if command_run == "allow":
        actions.append("start_command_run")
    return PromptDynamicInput(
        task=PromptTask(id="t_7m4k2d9x", workflow_id="reviewed-delivery"),
        dispatch=PromptDispatch(
            id="dsp_123",
            attempt_id="att_123",
            assignment_id="asn_123",
        ),
        current_member=PromptCurrentMember(
            id="lead" if task_lead else "implementation",
            title="Delivery lead" if task_lead else "Implementation",
            description="Own the current result.",
            instruction="Preserve public compatibility.",
            position="task_lead" if task_lead else None,
            behavior=PromptBehavior.MANAGER if manager else PromptBehavior.CONTRIBUTOR,
            provider=PromptProvider(
                name=provider_name,
                model="gpt-5.6",
                effort="high",
                sandbox=PromptSandbox(mode="workspace_write", network="deny"),
            ),
            effective_capabilities=capabilities,
        ),
        assignment=PromptAssignment(
            id="asn_123",
            prompt=assignment_prompt,
            files=(
                FileReference(
                    path=".banksia/t_7m4k2d9x/artifacts/review.md",
                    description="Inspect this review before deciding.",
                ),
            ),
        ),
        continuation=(PromptContinuation(trigger=sample_child_return()) if continuation else None),
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
        available_actions=tuple(actions),
        workspace=PromptWorkspace(
            root="/work/acme",
            task_directory=".banksia/t_7m4k2d9x",
            manifest=".banksia/t_7m4k2d9x/manifest.md",
            workflow_note=".banksia/t_7m4k2d9x/workflow-note.md",
            notes=".banksia/t_7m4k2d9x/notes",
            artifacts=".banksia/t_7m4k2d9x/artifacts",
            command_runs=".banksia/t_7m4k2d9x/command-runs",
        ),
    )


def sample_child_return() -> ChildReturnTrigger:
    return ChildReturnTrigger(
        source=ChildReturnSource(
            accepted_boundary_id="bnd_123",
            source_dispatch_id="dsp_child",
            child_assignment_id="asn_child",
            child_attempt_id="att_child",
        ),
        result=ChildReturnResult(
            assignment=PromptAssignment(
                id="asn_child",
                prompt="Review the exact implementation.",
                files=(FileReference(path="src/change.py", description="Changed source."),),
            ),
            outcome=EgressBoundary.GREEN,
            checkpoint=PromptCheckpointSummary(
                id="cp_123",
                summary="The bounded review is complete.",
                details="One residual risk remains documented.",
                files=(
                    FileReference(
                        path=".banksia/t_7m4k2d9x/artifacts/review.md",
                        description="Independent review.",
                    ),
                ),
                outcome=CheckpointOutcome.GREEN,
            ),
        ),
    )


def sample_request(**dynamic_overrides: object) -> DispatchRequestRenderInput:
    return DispatchRequestRenderInput(
        dynamic_input=sample_dynamic_input(**dynamic_overrides),
        member_instruction="Preserve the public API.",
        workflow_note="Treat public API changes as an explicit non-goal.",
    )
