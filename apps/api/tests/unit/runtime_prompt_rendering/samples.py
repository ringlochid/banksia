from __future__ import annotations

from datetime import UTC, datetime

from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.command_runs import CommandRunStartRequest
from banksia.runtime.contracts.human_requests import (
    HumanRequestItem,
    HumanRequestResolution,
    HumanRequestTimeout,
    PendingHumanRequest,
)
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.primitives import (
    CheckpointOutcome,
    EgressBoundary,
    HumanRequestKind,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestStatus,
)
from banksia.runtime.contracts.prompt import (
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
    PromptNext,
    PromptTrigger,
    RootStartTrigger,
    RuntimeReadbackRefs,
    SemanticRetryTrigger,
    WatchdogRecoveryTrigger,
)
from banksia.runtime.contracts.refs import FileReference


def sample_checkpoint() -> PromptCheckpointSummary:
    return PromptCheckpointSummary(
        checkpoint_id="checkpoint-1",
        summary="The bounded child assignment completed.",
        details="The report contains the reviewed implementation findings.",
        outcome=CheckpointOutcome.GREEN,
        files=(
            FileReference(
                path=".banksia/t_7m4k2d9x/artifacts/report.md",
                description="The child report.",
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
            member_id="engineer",
            member_title="Engineer",
            node_kind=node_kind,
            prompt="Repair the bounded authentication defect.",
        ),
        trigger=trigger or RootStartTrigger(flow_id="flow-1"),
        plan=None,
        context=PromptContext(
            capabilities=EffectiveCapabilitySet(),
            allowed_actions=(
                "get_current_context",
                "checkpoint",
            ),
            readback_refs=RuntimeReadbackRefs(
                instructions="_runtime/dispatch/dispatch-1/instructions.md",
                input="_runtime/dispatch/dispatch-1/input.md",
                workflow_manifest="manifest.md",
            ),
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
            member=("Stay inside the assigned Member boundary.",),
            node=("Use the node-local boundary tools.",),
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
        _sample_command_result_trigger(),
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


def _sample_command_result_trigger() -> CommandResultTrigger:
    return CommandResultTrigger(
        run_id="c_01234567",
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
            output_path=".banksia/t_01234567/command-runs/c_01234567/output.log",
            output_observed_bytes=15,
            output_written_bytes=15,
            output_complete=True,
            output_encoding="raw_bytes",
            terminal_event_source=PromptCommandTerminalSource.PROCESS_OWNER,
        ),
    )
