import type { StatusTone } from "../../components/ui";
import type { components } from "../../api/generated/openapi";
import type { TaskEventType } from "../../api/view-models";

export type TaskDetailTab = "evidence" | "summary";

export interface TaskDetailTabOption {
    readonly label: string;
    readonly value: TaskDetailTab;
}

export interface TaskDetailView {
    readonly actionMode: TaskActionMode;
    readonly artifactRefs: readonly TaskDetailRef[];
    readonly commandRuns: readonly CommandRunPreview[];
    readonly eventRows: readonly TaskEventRow[];
    readonly graphEdges: readonly TaskGraphEdge[];
    readonly graphNodes: readonly TaskGraphNode[];
    readonly humanRequests: readonly HumanRequestPreview[];
    readonly runtime: TaskRuntimeView;
    readonly snapshot: TaskSnapshotSummary;
    readonly task: TaskHeaderView;
    readonly trace: TaskTraceSummary;
}

export interface TaskRuntimeView {
    readonly activeAssignmentId: string | null;
    readonly controlRevision: number;
    readonly currentCommandRun: components["schemas"]["CommandRunSummary"] | null;
    readonly currentDispatch: TaskRuntimeDispatchView | null;
    readonly currentHumanRequest: components["schemas"]["HumanRequestSummary"] | null;
    readonly currentPlan: TaskWorkPlanView | null;
    readonly latestDispatchId: string | null;
    readonly pauseReason: components["schemas"]["RuntimeFlowPauseReason"] | null;
    readonly waitingCause: components["schemas"]["RuntimeFlowWaitingCause"] | null;
    readonly watchdogRecoveryCount: number;
}

export interface TaskRuntimeDispatchView {
    readonly adapterStartedAt: string | null;
    readonly assignmentId: string;
    readonly attemptId: string;
    readonly dispatchId: string;
    readonly effectiveCapabilities: components["schemas"]["EffectiveCapabilityReadback"];
    readonly isExperimentalProvider: boolean;
    readonly lastNodeActivityAt: string | null;
    readonly nodeActivityRevision: number;
    readonly openedReason: components["schemas"]["DispatchOpenedReason"];
    readonly predecessorDispatchId: string | null;
    readonly providerStart: components["schemas"]["ProviderStartReadback"] | null;
    readonly requestedProvider: components["schemas"]["ProviderKind"];
    readonly resolvedProvider: components["schemas"]["ProviderKind"];
    readonly selectionBasis: components["schemas"]["ProviderSelectionBasis"];
    readonly status: components["schemas"]["DispatchRuntimeStatus"];
    readonly watchdogDueAt: string | null;
}

export interface TaskWorkPlanView {
    readonly assignmentId: string;
    readonly authoredByDispatchId: string;
    readonly explanation: string | null;
    readonly revision: number;
    readonly steps: readonly components["schemas"]["WorkPlanStepRead"][];
    readonly updatedAt: string;
}

export interface TaskHeaderView {
    readonly activeAttemptId: string | null;
    readonly activeFlowRevisionId: string;
    readonly blockerSummary: string | null;
    readonly currentNodeKey: string | null;
    readonly status: components["schemas"]["RuntimeLifecycleStatus"];
    readonly terminalOutcome: components["schemas"]["RuntimeFlowTerminalOutcome"] | null;
    readonly summary: string;
    readonly taskId: string;
    readonly title: string;
    readonly updatedAt: string;
    readonly workflowKey: string | null;
    readonly workflowManifestRef: components["schemas"]["WorkflowManifestRef"];
}

export interface TaskSnapshotSummary {
    readonly streamHeadEventId: string | null;
    readonly topActionableItems: readonly components["schemas"]["TopActionableItem"][];
}

export interface TaskTraceSummary {
    readonly boundaries: readonly components["schemas"]["BoundaryHistoryEntry"][];
    readonly checkpoints: readonly components["schemas"]["CheckpointHistoryEntry"][];
    readonly dependencyEdges: readonly components["schemas"]["TaskGraphDependencyEntry"][];
    readonly dispatches: readonly components["schemas"]["DispatchHistoryEntry"][];
    readonly graphNodes: readonly components["schemas"]["TaskGraphNodeEntry"][];
}

export interface TaskGraphNode {
    readonly attemptId: string | null;
    readonly checkpointSummary: string | null;
    readonly eventCount: number;
    readonly isActive: boolean;
    readonly isCurrent: boolean;
    readonly nodeKey: string;
    readonly order: number;
    readonly status: "active" | "blocked" | "done" | "quiet" | "staged";
    readonly summary: string;
}

export interface TaskGraphEdge {
    readonly fromNodeKey: string;
    readonly kind: "staged" | "structural";
    readonly toNodeKey: string;
}

export interface TaskEventRow {
    readonly actorRef: string | null;
    readonly attemptId: string | null;
    readonly eventId: string;
    readonly eventSeq: number;
    readonly eventSource: components["schemas"]["TaskEventSource"];
    readonly eventType: TaskEventType;
    readonly flowRevisionId: string | null;
    readonly isMilestone: boolean;
    readonly label: string;
    readonly nodeKey: string | null;
    readonly occurredAt: string;
    readonly payloadSummary: string;
    readonly record: components["schemas"]["TaskEventRecord"];
    readonly tone: StatusTone;
}

export interface TaskDetailRef {
    readonly description: string | null;
    readonly kind: string;
    readonly label: string;
    readonly path: string | null;
    readonly slot: string | null;
}

export interface HumanRequestPreview {
    readonly kind: components["schemas"]["HumanRequestKind"];
    readonly requestId: string;
    readonly status: components["schemas"]["HumanRequestStatus"];
    readonly summary: string;
    readonly title: string;
}

export interface CommandRunPreview {
    readonly description: string | null;
    readonly hasLog: boolean;
    readonly runId: string;
    readonly state: components["schemas"]["CommandRunState"];
    readonly summary: string | null;
}

export interface TaskSelectedContext {
    readonly assignmentRows: readonly DetailRow[];
    readonly boundaryRows: readonly DetailRow[];
    readonly checkpointOutcome: string | null;
    readonly checkpointRows: readonly DetailRow[];
    readonly checkpointSummary: string | null;
    readonly event: TaskEventRow | null;
    readonly evidenceRefs: readonly TaskDetailRef[];
    readonly node: TaskGraphNode | null;
    readonly technicalRefs: readonly TaskDetailRef[];
    readonly traceJson: string;
}

export interface DetailRow {
    readonly label: string;
    readonly value: string;
}

export interface TaskActionMode {
    readonly canCancel: boolean;
    readonly canContinue: boolean;
    readonly canPause: boolean;
    readonly note: string;
}

export const TASK_DETAIL_TABS: readonly TaskDetailTabOption[] = [
    { label: "Summary", value: "summary" },
    { label: "Evidence", value: "evidence" },
];

export const TASK_EVENT_TYPES: readonly TaskEventType[] = [
    "task_started",
    "dispatch_opened",
    "dispatch_start_updated",
    "work_plan_set",
    "work_plan_cleared",
    "checkpoint_recorded",
    "boundary_accepted",
    "child_assignment_staged",
    "child_assignment_committed",
    "structural_revision_adopted",
    "human_request_opened",
    "human_request_resolved",
    "human_request_timed_out",
    "human_request_cancelled",
    "command_run_opened",
    "command_run_started",
    "command_run_progressed",
    "command_run_cancel_requested",
    "command_run_succeeded",
    "command_run_failed",
    "command_run_timed_out",
    "command_run_cancelled",
    "command_run_abandoned",
    "task_paused",
    "task_resumed",
    "task_cancelled",
];
