from __future__ import annotations

from datetime import UTC, datetime

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts.capabilities import EffectiveCapabilitySet
from autoclaw.runtime.contracts.command_runs import CommandRunStartRequest
from autoclaw.runtime.contracts.human_requests import (
    HumanRequestItem,
    HumanRequestResolution,
    HumanRequestTimeout,
    PendingHumanRequest,
)
from autoclaw.runtime.contracts.primitives import (
    CheckpointOutcome,
    EgressBoundary,
    HumanRequestKind,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestStatus,
)
from autoclaw.runtime.contracts.prompt import (
    AcceptedBoundaryTrigger,
    ChildReturnTrigger,
    CommandResultTrigger,
    DispatchRequestRenderInput,
    HumanResultTrigger,
    OperatorContinueTrigger,
    PromptAssignment,
    PromptCheckpointSummary,
    PromptCommandOutcome,
    PromptCommandResult,
    PromptCommandTerminalSource,
    PromptContext,
    PromptDispatch,
    PromptDynamicInput,
    PromptFamily,
    PromptInstructionGuidance,
    PromptLogicalRef,
    PromptNext,
    PromptRefKind,
    PromptTrigger,
    RootStartTrigger,
    RuntimeReadbackRefs,
    SemanticRetryTrigger,
    WatchdogRecoveryTrigger,
)


def sample_checkpoint() -> PromptCheckpointSummary:
    return PromptCheckpointSummary(
        checkpoint_id="checkpoint-1",
        logical_path="_runtime/attempts/attempt-1/latest-checkpoint.md",
        summary="The bounded child assignment completed.",
        outcome=CheckpointOutcome.GREEN,
        refs=(
            PromptLogicalRef(
                kind=PromptRefKind.ARTIFACT,
                logical_path="outputs/report/report.v01.md",
                purpose="Inspect the accepted child result.",
                description="The child report.",
                slot="report",
                version=1,
            ),
        ),
    )


def sample_dynamic_input(
    *,
    node_kind: NodeKind = NodeKind.WORKER,
    trigger: PromptTrigger | None = None,
) -> PromptDynamicInput:
    return PromptDynamicInput(
        assignment=PromptAssignment(
            assignment_id="assignment-1",
            role_id="engineer",
            role_description="Complete one bounded engineering assignment.",
            node_kind=node_kind,
            summary="Repair the bounded authentication defect.",
            instruction="Change only the assigned behavior.",
        ),
        trigger=trigger or RootStartTrigger(flow_id="flow-1"),
        plan=None,
        context=PromptContext(
            capabilities=EffectiveCapabilitySet(),
            allowed_actions=(
                "get_current_context",
                "release_green",
            )
            if node_kind != NodeKind.WORKER
            else ("get_current_context", "return_boundary"),
            readback_refs=RuntimeReadbackRefs(
                instructions="_runtime/dispatch/dispatch-1/instructions.md",
                input="_runtime/dispatch/dispatch-1/input.md",
                workflow_manifest="_runtime/workflow-manifest.md",
            ),
            refs=(),
            constraints=("Do not edit unrelated files.",),
        ),
        dispatch=PromptDispatch(
            task_id="task-1",
            flow_id="flow-1",
            flow_revision_id="flow-revision-1",
            dispatch_id="dispatch-1",
            assignment_id="assignment-1",
            attempt_id="attempt-1",
            node_key="repair-auth",
            node_kind=node_kind,
        ),
        next=PromptNext(instruction="Read current context, then complete the assignment."),
    )


def sample_request(
    *,
    node_kind: NodeKind = NodeKind.WORKER,
    trigger: PromptTrigger | None = None,
) -> DispatchRequestRenderInput:
    family = PromptFamily.WORKER if node_kind == NodeKind.WORKER else PromptFamily.PARENT_ROOT
    return DispatchRequestRenderInput(
        family=family,
        guidance=PromptInstructionGuidance(
            workflow=("Follow the accepted workflow revision.",),
            role=("Stay inside the assigned role.",),
            node=("Use the node-local boundary tools.",),
            policy=("Preserve controller-owned truth.",),
        ),
        dynamic_input=sample_dynamic_input(node_kind=node_kind, trigger=trigger),
    )


def all_trigger_samples() -> tuple[PromptTrigger, ...]:
    checkpoint = sample_checkpoint()
    retry_checkpoint = checkpoint.model_copy(update={"outcome": CheckpointOutcome.RETRY})
    return (
        RootStartTrigger(flow_id="flow-1"),
        AcceptedBoundaryTrigger(
            accepted_boundary_id="boundary-1",
            source_dispatch_id="dispatch-0",
            outcome=EgressBoundary.YIELD,
        ),
        ChildReturnTrigger(
            child_assignment_id="child-assignment-1",
            child_attempt_id="child-attempt-1",
            source_dispatch_id="child-dispatch-1",
            accepted_boundary_id="boundary-1",
            outcome=EgressBoundary.GREEN,
            checkpoint=checkpoint,
        ),
        HumanResultTrigger(
            request=PendingHumanRequest(
                request_id="human-request-1",
                task_id="task-1",
                flow_id="flow-1",
                assignment_id="assignment-1",
                attempt_id="attempt-1",
                summary="Approve the bounded action.",
                kind=HumanRequestKind.APPROVAL,
                source_dispatch_id="dispatch-0",
                items=(
                    HumanRequestItem(
                        id="decision",
                        prompt="Should the bounded action proceed?",
                        response_schema={"type": "string"},
                    ),
                ),
                timeout=HumanRequestTimeout(),
                opened_at=datetime(2026, 7, 18, 1, tzinfo=UTC),
                status=HumanRequestStatus.RESOLVED,
            ),
            resolution=HumanRequestResolution(
                request_id="human-request-1",
                task_id="task-1",
                resolution_kind=HumanRequestResolutionKind.ANSWERED,
                item_responses={"decision": "approved"},
                summary="The operator approved the bounded action.",
                resolved_at=datetime(2026, 7, 18, 2, tzinfo=UTC),
                resolved_by_surface=HumanRequestResolutionSurface.CONTROLLER,
            ),
        ),
        CommandResultTrigger(
            run_id="command-run-1",
            source_dispatch_id="dispatch-0",
            request=CommandRunStartRequest.model_validate(
                {
                    "command": {"kind": "argv", "argv": ["python", "-V"]},
                    "summary": "Read the Python version.",
                }
            ),
            result=PromptCommandResult(
                state=PromptCommandOutcome.SUCCEEDED,
                exit_code=0,
                summary="The command completed successfully.",
                started_at=datetime(2026, 7, 18, 1, tzinfo=UTC),
                ended_at=datetime(2026, 7, 18, 2, tzinfo=UTC),
                terminal_event_source=PromptCommandTerminalSource.PROCESS_OWNER,
            ),
        ),
        WatchdogRecoveryTrigger(source_dispatch_id="dispatch-0", recovery_count=1),
        SemanticRetryTrigger(
            accepted_boundary_id="boundary-1",
            source_dispatch_id="dispatch-0",
            previous_attempt_id="attempt-0",
            checkpoint=retry_checkpoint,
        ),
        OperatorContinueTrigger(
            source_dispatch_id="dispatch-0",
            control_revision=2,
            pause_reason="The task was paused for operator review.",
        ),
    )
