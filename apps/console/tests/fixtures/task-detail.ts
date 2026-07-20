import type { ConsoleMockScenario } from "../../src/mocks/handlers";
import type { components } from "../../src/api/generated/openapi";
import type { TaskEventType } from "../../src/api/view-models";
import { TASK_EVENT_TYPES } from "../../src/features/task-detail/task-detail-model";
import {
    createCommandRunListItem,
    createConsoleMockScenario,
    createHumanRequestRead,
    createRuntimeFlowRead,
    createTaskEventStreamFixture,
    createWorkflowManifestRef,
} from "./console-api";

export const TASK_DETAIL_TASK_ID = "task-runtime-route-copy";
export const TASK_DETAIL_STREAM_HEAD = "evt-006-structural-revision-adopted";
export const TASK_DETAIL_EVENT_BASE_AT = "2026-06-21T15:03:00Z";
export const TASK_DETAIL_UPDATED_AT = "2026-06-21T15:24:00Z";

const TASK_DETAIL_VISUAL_EVENT_TIMES: Partial<Record<TaskEventType, string>> = {
    boundary_accepted: "2026-06-21T15:10:00Z",
    checkpoint_recorded: "2026-06-21T15:09:00Z",
    child_assignment_committed: "2026-06-21T15:12:00Z",
    child_assignment_staged: "2026-06-21T15:11:00Z",
    dispatch_opened: "2026-06-21T15:08:00Z",
    structural_revision_adopted: "2026-06-21T15:13:00Z",
    task_started: "2026-06-21T15:03:00Z",
};

const TASK_DETAIL_VISUAL_EVENT_TYPES: readonly TaskEventType[] = [
    "task_started",
    "dispatch_opened",
    "checkpoint_recorded",
    "boundary_accepted",
    "child_assignment_staged",
    "structural_revision_adopted",
];

const TASK_DETAIL_EVENT_TYPES = [
    ...TASK_DETAIL_VISUAL_EVENT_TYPES,
    ...TASK_EVENT_TYPES.filter((eventType) => !TASK_DETAIL_VISUAL_EVENT_TYPES.includes(eventType)),
];

type TaskEventEnvelope = Omit<components["schemas"]["TaskEventRecord"], "event_type" | "payload">;
type TaskEventBuilder = (
    envelope: TaskEventEnvelope,
    nodeKey: string,
) => components["schemas"]["TaskEventRecord"];

const TASK_EVENT_BUILDERS = {
    task_started: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "task_started",
        payload: payloadForEvent("task_started", nodeKey),
    }),
    dispatch_opened: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "dispatch_opened",
        payload: payloadForEvent("dispatch_opened", nodeKey),
    }),
    dispatch_start_updated: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "dispatch_start_updated",
        payload: payloadForEvent("dispatch_start_updated", nodeKey),
    }),
    work_plan_set: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "work_plan_set",
        payload: payloadForEvent("work_plan_set", nodeKey),
    }),
    work_plan_cleared: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "work_plan_cleared",
        payload: payloadForEvent("work_plan_cleared", nodeKey),
    }),
    checkpoint_recorded: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "checkpoint_recorded",
        payload: payloadForEvent("checkpoint_recorded", nodeKey),
    }),
    boundary_accepted: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "boundary_accepted",
        payload: payloadForEvent("boundary_accepted", nodeKey),
    }),
    child_assignment_staged: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "child_assignment_staged",
        payload: payloadForEvent("child_assignment_staged", nodeKey),
    }),
    child_assignment_committed: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "child_assignment_committed",
        payload: payloadForEvent("child_assignment_committed", nodeKey),
    }),
    structural_revision_adopted: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "structural_revision_adopted",
        payload: payloadForEvent("structural_revision_adopted", nodeKey),
    }),
    human_request_opened: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "human_request_opened",
        payload: payloadForEvent("human_request_opened", nodeKey),
    }),
    human_request_resolved: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "human_request_resolved",
        payload: payloadForEvent("human_request_resolved", nodeKey),
    }),
    human_request_timed_out: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "human_request_timed_out",
        payload: payloadForEvent("human_request_timed_out", nodeKey),
    }),
    human_request_cancelled: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "human_request_cancelled",
        payload: payloadForEvent("human_request_cancelled", nodeKey),
    }),
    command_run_opened: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_opened",
        payload: payloadForEvent("command_run_opened", nodeKey),
    }),
    command_run_started: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_started",
        payload: payloadForEvent("command_run_started", nodeKey),
    }),
    command_run_progressed: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_progressed",
        payload: payloadForEvent("command_run_progressed", nodeKey),
    }),
    command_run_cancel_requested: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_cancel_requested",
        payload: payloadForEvent("command_run_cancel_requested", nodeKey),
    }),
    command_run_succeeded: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_succeeded",
        payload: payloadForEvent("command_run_succeeded", nodeKey),
    }),
    command_run_failed: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_failed",
        payload: payloadForEvent("command_run_failed", nodeKey),
    }),
    command_run_timed_out: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_timed_out",
        payload: payloadForEvent("command_run_timed_out", nodeKey),
    }),
    command_run_cancelled: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_cancelled",
        payload: payloadForEvent("command_run_cancelled", nodeKey),
    }),
    command_run_abandoned: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "command_run_abandoned",
        payload: payloadForEvent("command_run_abandoned", nodeKey),
    }),
    task_paused: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "task_paused",
        payload: payloadForEvent("task_paused", nodeKey),
    }),
    task_resumed: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "task_resumed",
        payload: payloadForEvent("task_resumed", nodeKey),
    }),
    task_cancelled: (envelope, nodeKey) => ({
        ...envelope,
        event_type: "task_cancelled",
        payload: payloadForEvent("task_cancelled", nodeKey),
    }),
} satisfies Record<TaskEventType, TaskEventBuilder>;

export interface TaskDetailScenarioOptions {
    readonly cursorResetCursors?: readonly string[];
    readonly events?: readonly components["schemas"]["TaskEventRecord"][];
    readonly status?: components["schemas"]["RuntimeLifecycleStatus"];
    readonly streamEvents?: readonly components["schemas"]["TaskEventRecord"][];
    readonly streamHeadEventId?: string | null;
}

export function createTaskDetailMockScenario(
    options: TaskDetailScenarioOptions = {},
): ConsoleMockScenario {
    const events = options.events ?? createTaskDetailEventRecords();
    const streamHeadEventId =
        options.streamHeadEventId === undefined
            ? TASK_DETAIL_STREAM_HEAD
            : options.streamHeadEventId;
    const streamHeadIndex =
        streamHeadEventId === null
            ? -1
            : events.findIndex((event) => event.event_id === streamHeadEventId);
    const backfillEvents =
        streamHeadIndex === -1
            ? []
            : events.filter((event) => event.event_seq <= streamHeadIndex + 1);
    const streamEvents =
        options.streamEvents ?? (streamHeadIndex === -1 ? events : events.slice(streamHeadIndex));
    const taskRead = createRuntimeFlowRead({
        active_assignment_id: "assignment-task-detail-build",
        active_attempt_id: "attempt-task-detail-build",
        active_flow_revision_id: "flow-revision-task-detail-1",
        current_dispatch: {
            adapter_started_at: TASK_DETAIL_UPDATED_AT,
            assignment_id: "assignment-task-detail-build",
            attempt_id: "attempt-task-detail-build",
            dispatch_id: "dispatch-task-detail-build-current",
            effective_capabilities: {
                network_access: { effective: "allow", source: "task_policy" },
                provider_native_access: { effective: "restricted", source: "policy_definition" },
            },
            last_node_activity_at: TASK_DETAIL_UPDATED_AT,
            node_activity_revision: 4,
            opened_reason: "boundary",
            predecessor_dispatch_id: "dispatch-task-detail-build-previous",
            provider_start: null,
            requested_provider: "openclaw",
            resolved_provider: "openclaw",
            selection_basis: "explicit",
            status: "open",
            watchdog_due_at: "2026-06-29T14:15:00Z",
        },
        current_node_key: "task_detail_build",
        current_plan: {
            assignment_id: "assignment-task-detail-build",
            authored_by_dispatch_id: "dispatch-task-detail-build-current",
            explanation: "Keep runtime truth explicit while converging the console.",
            revision: 2,
            steps: [
                { status: "completed", step: "Read the accepted runtime contracts." },
                { status: "in_progress", step: "Render exact controller runtime truth." },
                { status: "pending", step: "Run focused console proof." },
            ],
            updated_at: TASK_DETAIL_UPDATED_AT,
        },
        latest_dispatch_id: "dispatch-task-detail-build-current",
        status: options.status ?? "running",
        task_id: TASK_DETAIL_TASK_ID,
        task_summary: "Replace retired runtime labels without widening the task hub.",
        task_title: "Refresh runtime route copy",
        updated_at: TASK_DETAIL_UPDATED_AT,
        workflow_key: "frontend-console-continuation-delivery",
        workflow_manifest_ref: createWorkflowManifestRef(),
    });

    return createConsoleMockScenario({
        commandRunList: {
            items: [
                createCommandRunListItem({
                    description: "Verify command-run runner behavior.",
                    run_id: "run-task-detail-check",
                    state: "running",
                    summary: "Focused integration proof is running.",
                }),
            ],
            next_cursor: null,
            task_id: TASK_DETAIL_TASK_ID,
        },
        humanRequestList: {
            items: [
                createHumanRequestRead({
                    kind: "approval",
                    request_id: "hr-task-detail-approval",
                    summary: "Approval is needed for the last copy trim.",
                }),
            ],
            task_id: TASK_DETAIL_TASK_ID,
        },
        snapshot: {
            current_paths: [
                {
                    description: "Current assignment for Task Detail build.",
                    kind: "assignment",
                    path: "_runtime/attempts/task-detail/assignment.md",
                    slot: null,
                    version: null,
                },
            ],
            flow: taskRead,
            stream_head_event_id: streamHeadEventId,
            top_actionable_items: [
                {
                    current_paths: [],
                    node_key: "task_detail_build",
                    suggested_action: "Implement only Task Detail.",
                    summary: "Task Detail implementation is active.",
                },
            ],
        },
        taskEvents: {
            items: backfillEvents,
            next_cursor: null,
            task_id: TASK_DETAIL_TASK_ID,
            through_event_id: streamHeadEventId,
        },
        taskEventStream: createTaskEventStreamFixture({
            chunksByCursor:
                streamHeadEventId === null
                    ? {}
                    : {
                          [streamHeadEventId]: streamEvents.map(createTaskEventStreamFrame),
                      },
            cursorResetCursors: options.cursorResetCursors ?? [],
            events: streamEvents,
        }),
        taskRead,
        trace: createTaskDetailTrace(),
    });
}

export function createTaskDetailEventRecords(
    options: {
        readonly taskId?: string;
        readonly nodeKeys?: readonly string[];
    } = {},
): readonly components["schemas"]["TaskEventRecord"][] {
    const taskId = options.taskId ?? TASK_DETAIL_TASK_ID;
    const nodeKeys = options.nodeKeys ?? [
        "root",
        "source_contract",
        "task_control_suite",
        "tasks_page",
        "task_detail_page",
        "human_request_page",
        "command_runs_page",
        "task_detail_source_contract",
        "task_detail_build",
        "task_detail_review",
    ];

    return TASK_DETAIL_EVENT_TYPES.map((eventType, index) => {
        const eventSeq = index + 1;
        const eventId = `evt-${String(eventSeq).padStart(3, "0")}-${eventType.replace(/_/g, "-")}`;
        const nodeKey = nodeKeyForEvent(eventType, index, nodeKeys);
        const envelope: TaskEventEnvelope = {
            actor_ref: null,
            attempt_id: `attempt-${nodeKey}`,
            dispatch_id: `dispatch-${nodeKey}`,
            event_hash: `hash-${eventId}`,
            event_id: eventId,
            event_seq: eventSeq,
            event_source: eventSourceForType(eventType),
            flow_revision_id: "flow-revision-task-detail-1",
            node_key: nodeKey,
            occurred_at: occurredAtForEvent(eventType, index),
            prev_event_hash: eventSeq === 1 ? null : `hash-event-${String(eventSeq - 1)}`,
            task_id: taskId,
        };
        return TASK_EVENT_BUILDERS[eventType](envelope, nodeKey);
    });
}

function nodeKeyForEvent(
    eventType: TaskEventType,
    index: number,
    nodeKeys: readonly string[],
): string {
    const nodeByEventType: Partial<Record<TaskEventType, string>> = {
        boundary_accepted: "task_detail_build",
        checkpoint_recorded: "task_detail_source_contract",
        child_assignment_staged: "task_detail_review",
        command_run_cancel_requested: "task_detail_build",
        command_run_cancelled: "task_detail_build",
        command_run_abandoned: "task_detail_build",
        command_run_failed: "task_detail_build",
        command_run_opened: "task_detail_build",
        command_run_progressed: "task_detail_build",
        command_run_started: "task_detail_build",
        command_run_succeeded: "task_detail_build",
        command_run_timed_out: "task_detail_build",
        dispatch_opened: "task_detail_build",
        human_request_cancelled: "task_detail_build",
        human_request_opened: "task_detail_build",
        human_request_resolved: "task_detail_build",
        human_request_timed_out: "task_detail_build",
        structural_revision_adopted: "task_detail_page",
        task_started: "root",
    };
    return (
        nodeByEventType[eventType] ??
        nodeKeys[Math.min(index % nodeKeys.length, nodeKeys.length - 1)]
    );
}

export function createLongTaskDetailEventRecords(): readonly components["schemas"]["TaskEventRecord"][] {
    const nodeKeys = Array.from({ length: 18 }, (_item, index) =>
        index === 0 ? "root" : `worker_node_${String(index).padStart(2, "0")}`,
    );
    const baseEvents = createTaskDetailEventRecords({ nodeKeys });
    const extraEvents = nodeKeys.slice(6).map((nodeKey, index) =>
        TASK_EVENT_BUILDERS.dispatch_opened(
            {
                actor_ref: null,
                attempt_id: `attempt-${nodeKey}`,
                dispatch_id: `dispatch-${nodeKey}`,
                event_hash: `hash-extra-${String(index + 1)}`,
                event_id: `evt-extra-${String(index + 1).padStart(2, "0")}`,
                event_seq: baseEvents.length + index + 1,
                event_source: "controller",
                flow_revision_id: "flow-revision-task-detail-1",
                node_key: nodeKey,
                occurred_at: new Date(
                    Date.parse(TASK_DETAIL_EVENT_BASE_AT) + (baseEvents.length + index) * 60_000,
                ).toISOString(),
                prev_event_hash: `hash-event-${String(baseEvents.length + index)}`,
                task_id: TASK_DETAIL_TASK_ID,
            },
            nodeKey,
        ),
    );
    return [...baseEvents, ...extraEvents];
}

function createTaskDetailTrace(): components["schemas"]["OperatorFlowTraceResponse"] {
    return {
        boundary_history: [
            {
                boundary: "green",
                checkpoint_id: "checkpoint-contract",
                node_key: "task_detail_source_contract",
                occurred_at: "2026-06-29T13:45:00Z",
                source_dispatch_id: "dispatch-task_detail_source_contract",
                successor_dispatch_id: "dispatch-task_detail_page",
            },
            {
                boundary: "yield",
                checkpoint_id: null,
                node_key: "task_detail_page",
                occurred_at: "2026-06-29T13:55:00Z",
                source_dispatch_id: "dispatch-task_detail_page",
                successor_dispatch_id: "dispatch-task_detail_build",
            },
        ],
        checkpoint_history: [
            {
                attempt_id: "attempt-task_detail_source_contract",
                checkpoint_id: "checkpoint-contract",
                checkpoint_kind: "terminal",
                outcome: "green",
                recorded_at: "2026-06-29T13:45:00Z",
                summary: "Runtime page contract is ready.",
            },
            {
                attempt_id: "attempt-task_detail_build",
                checkpoint_id: "checkpoint-build-progress",
                checkpoint_kind: "progress",
                outcome: null,
                recorded_at: "2026-06-29T14:00:00Z",
                summary: "Task Detail build is in progress.",
            },
        ],
        current_paths: [
            {
                description: "Latest checkpoint for the active build node.",
                kind: "checkpoint",
                path: "_runtime/attempts/task-detail/latest-checkpoint.md",
                slot: null,
                version: null,
            },
        ],
        dependency_edges: [
            {
                consumer_node_key: "task_detail_build",
                description: "The build consumes the Task Detail source contract.",
                kind: "artifact",
                order_index: 0,
                provider_node_key: "task_detail_source_contract",
                slot: "task_detail_contract",
            },
            {
                consumer_node_key: "task_detail_review",
                description: "The review consumes the Task Detail implementation.",
                kind: "artifact",
                order_index: 1,
                provider_node_key: "task_detail_build",
                slot: "task_detail_patch",
            },
        ],
        dispatch_history: [
            createDispatchHistoryEntry("root", 0, "closed"),
            createDispatchHistoryEntry("source_contract", 1, "closed"),
            createDispatchHistoryEntry("task_control_suite", 2, "closed"),
            createDispatchHistoryEntry("tasks_page", 3, "closed"),
            createDispatchHistoryEntry("task_detail_page", 4, "closed"),
            createDispatchHistoryEntry("task_detail_source_contract", 5, "closed"),
            createDispatchHistoryEntry("task_detail_build", 6, "open"),
        ],
        graph_nodes: [
            {
                child_node_keys: ["source_contract", "task_control_suite"],
                depended_on_by_node_keys: [],
                depends_on_node_keys: [],
                description: "Coordinate the runtime route refresh.",
                node_key: "root",
                node_kind: "root",
                order_index: 0,
                parent_node_key: null,
                policy: null,
                role: "planning_lead",
            },
            {
                child_node_keys: [],
                depended_on_by_node_keys: [],
                depends_on_node_keys: [],
                description: "Capture the runtime route source contract.",
                node_key: "source_contract",
                node_kind: "worker",
                order_index: 1,
                parent_node_key: "root",
                policy: "browser_first_review",
                role: "source_reviewer",
            },
            {
                child_node_keys: [
                    "tasks_page",
                    "task_detail_page",
                    "human_request_page",
                    "command_runs_page",
                ],
                depended_on_by_node_keys: [],
                depends_on_node_keys: [],
                description: "Build the task control suite surface.",
                node_key: "task_control_suite",
                node_kind: "parent",
                order_index: 2,
                parent_node_key: "root",
                policy: "browser_first_worker",
                role: "ui_delivery_lead",
            },
            {
                child_node_keys: [],
                depended_on_by_node_keys: [],
                depends_on_node_keys: [],
                description: "Refresh the runtime task list page.",
                node_key: "tasks_page",
                node_kind: "worker",
                order_index: 3,
                parent_node_key: "task_control_suite",
                policy: "browser_first_worker",
                role: "ui_engineer",
            },
            {
                child_node_keys: [
                    "task_detail_source_contract",
                    "task_detail_build",
                    "task_detail_review",
                ],
                depended_on_by_node_keys: [],
                depends_on_node_keys: [],
                description: "Coordinate the Task Detail page work.",
                node_key: "task_detail_page",
                node_kind: "parent",
                order_index: 4,
                parent_node_key: "task_control_suite",
                policy: "browser_first_worker",
                role: "ui_delivery_lead",
            },
            {
                child_node_keys: [],
                depended_on_by_node_keys: [],
                depends_on_node_keys: [],
                description: "Prepare the human request page route.",
                node_key: "human_request_page",
                node_kind: "worker",
                order_index: 5,
                parent_node_key: "task_control_suite",
                policy: "browser_first_worker",
                role: "ui_engineer",
            },
            {
                child_node_keys: [],
                depended_on_by_node_keys: [],
                depends_on_node_keys: [],
                description: "Prepare the command runs page route.",
                node_key: "command_runs_page",
                node_kind: "worker",
                order_index: 6,
                parent_node_key: "task_control_suite",
                policy: "browser_first_worker",
                role: "ui_engineer",
            },
            {
                child_node_keys: [],
                depended_on_by_node_keys: ["task_detail_build"],
                depends_on_node_keys: [],
                description: "Confirm Task Detail contract boundaries.",
                node_key: "task_detail_source_contract",
                node_kind: "worker",
                order_index: 7,
                parent_node_key: "task_detail_page",
                policy: "browser_first_review",
                role: "source_reviewer",
            },
            {
                child_node_keys: [],
                depended_on_by_node_keys: ["task_detail_review"],
                depends_on_node_keys: ["task_detail_source_contract"],
                description: "Implement the Task Detail page.",
                node_key: "task_detail_build",
                node_kind: "worker",
                order_index: 8,
                parent_node_key: "task_detail_page",
                policy: "browser_first_worker",
                role: "ui_engineer",
            },
            {
                child_node_keys: [],
                depended_on_by_node_keys: [],
                depends_on_node_keys: ["task_detail_build"],
                description: "Review the Task Detail implementation.",
                node_key: "task_detail_review",
                node_kind: "worker",
                order_index: 9,
                parent_node_key: "task_detail_page",
                policy: "browser_first_review",
                role: "delivery_reviewer",
            },
        ],
        next_cursor: null,
        scope: "whole",
        task_id: TASK_DETAIL_TASK_ID,
    };
}

function createDispatchHistoryEntry(
    nodeKey: string,
    index: number,
    status: components["schemas"]["DispatchHistoryEntry"]["status"],
): components["schemas"]["DispatchHistoryEntry"] {
    const createdAt = new Date(
        Date.parse("2026-06-29T13:30:00Z") + index * 5 * 60_000,
    ).toISOString();
    const isClosed = status === "closed";
    return {
        adapter_started_at: createdAt,
        assignment_id: `assignment-${nodeKey}`,
        attempt_id: `attempt-${nodeKey}`,
        closed_at: isClosed ? createdAt : null,
        closed_reason: isClosed ? "boundary" : null,
        created_at: createdAt,
        dispatch_id: `dispatch-${nodeKey}`,
        effective_capabilities: {
            network_access: { effective: "allow", source: "default" },
            provider_native_access: { effective: "full", source: "default" },
        },
        last_node_activity_at: status === "open" ? createdAt : null,
        node_activity_revision: status === "open" ? 1 : 0,
        node_key: nodeKey,
        opened_reason: nodeKey === "root" ? "root" : "boundary",
        predecessor_dispatch_id: index === 0 ? null : `dispatch-predecessor-${String(index)}`,
        requested_provider: "codex",
        resolved_provider: "codex",
        selection_basis: "default",
        status,
    };
}

function payloadForEvent(
    eventType: "task_started",
    nodeKey: string,
): components["schemas"]["TaskStartedEventPayload"];
function payloadForEvent(
    eventType: "dispatch_opened",
    nodeKey: string,
): components["schemas"]["DispatchOpenedEventPayload"];
function payloadForEvent(
    eventType: "dispatch_start_updated",
    nodeKey: string,
): components["schemas"]["DispatchStartUpdatedEventPayload"];
function payloadForEvent(
    eventType: "work_plan_set",
    nodeKey: string,
): components["schemas"]["WorkPlanSetEventPayload"];
function payloadForEvent(
    eventType: "work_plan_cleared",
    nodeKey: string,
): components["schemas"]["WorkPlanClearedEventPayload"];
function payloadForEvent(
    eventType: "checkpoint_recorded",
    nodeKey: string,
): components["schemas"]["CheckpointRecordedEventPayload"];
function payloadForEvent(
    eventType: "boundary_accepted",
    nodeKey: string,
): components["schemas"]["BoundaryAcceptedEventPayload"];
function payloadForEvent(
    eventType: "child_assignment_staged",
    nodeKey: string,
): components["schemas"]["ChildAssignmentStagedEventPayload"];
function payloadForEvent(
    eventType: "child_assignment_committed",
    nodeKey: string,
): components["schemas"]["ChildAssignmentCommittedEventPayload"];
function payloadForEvent(
    eventType: "structural_revision_adopted",
    nodeKey: string,
): components["schemas"]["StructuralRevisionAdoptedEventPayload"];
function payloadForEvent(
    eventType: "human_request_opened",
    nodeKey: string,
): components["schemas"]["HumanRequestOpenedEventPayload"];
function payloadForEvent(
    eventType: "human_request_resolved" | "human_request_timed_out" | "human_request_cancelled",
    nodeKey: string,
): components["schemas"]["HumanRequestTerminalEventPayload"];
function payloadForEvent(
    eventType: "command_run_opened",
    nodeKey: string,
): components["schemas"]["CommandRunOpenedEventPayload"];
function payloadForEvent(
    eventType: "command_run_started",
    nodeKey: string,
): components["schemas"]["CommandRunStartedEventPayload"];
function payloadForEvent(
    eventType: "command_run_progressed",
    nodeKey: string,
): components["schemas"]["CommandRunProgressedEventPayload"];
function payloadForEvent(
    eventType: "command_run_cancel_requested",
    nodeKey: string,
): components["schemas"]["CommandRunCancelRequestedEventPayload"];
function payloadForEvent(
    eventType:
        | "command_run_succeeded"
        | "command_run_failed"
        | "command_run_timed_out"
        | "command_run_cancelled"
        | "command_run_abandoned",
    nodeKey: string,
): components["schemas"]["CommandRunTerminalEventPayload"];
function payloadForEvent(
    eventType: "task_paused",
    nodeKey: string,
): components["schemas"]["TaskPausedEventPayload"];
function payloadForEvent(
    eventType: "task_resumed",
    nodeKey: string,
): components["schemas"]["TaskResumedEventPayload"];
function payloadForEvent(
    eventType: "task_cancelled",
    nodeKey: string,
): components["schemas"]["TaskCancelledEventPayload"];
function payloadForEvent(
    eventType: TaskEventType,
    nodeKey: string,
): components["schemas"]["TaskEventRecord"]["payload"] {
    switch (eventType) {
        case "task_started":
            return {
                compiled_plan_id: "compiled-plan-task-detail-1",
                flow_id: "flow-task-detail-1",
                manifest_ref: "_runtime/workflow-manifest.md",
                workflow_key: "frontend-console-continuation-delivery",
                workflow_revision_no: 1,
            };
        case "dispatch_opened":
            return dispatchOpenedPayload(nodeKey, null);
        case "dispatch_start_updated":
            return {
                attempt_count: 1,
                dispatch_id: `dispatch-${nodeKey}`,
                last_error_code: null,
                next_attempt_at: null,
                provider_start_revision: 1,
                retry_kind: null,
                state: "accepted",
            };
        case "work_plan_set":
            return {
                assignment_id: `assignment-${nodeKey}`,
                authored_by_dispatch_id: `dispatch-${nodeKey}`,
                explanation: "Keep the runtime contract cut bounded.",
                revision: 1,
                steps: [{ status: "in_progress", step: "Update target-shaped console fixtures." }],
                updated_at: TASK_DETAIL_UPDATED_AT,
            };
        case "work_plan_cleared":
            return {
                assignment_id: `assignment-${nodeKey}`,
                authored_by_dispatch_id: `dispatch-${nodeKey}`,
                explanation: "The focused plan is no longer needed.",
                revision: 2,
                updated_at: TASK_DETAIL_UPDATED_AT,
            };
        case "checkpoint_recorded":
            return {
                assignment_id: `assignment-${nodeKey}`,
                attempt_id: `attempt-${nodeKey}`,
                authored_by_dispatch_id: `dispatch-${nodeKey}`,
                checkpoint_id: "checkpoint-build-progress",
                checkpoint_kind: "progress",
                checkpoint_ref: "_runtime/attempts/task-detail/latest-checkpoint.md",
                outcome: null,
                produced_artifacts: [
                    {
                        path: "tmp/autoclaw-frontend/continuation-implementation/07-task-detail/report.md",
                        publication_id: "publication-task-detail-1",
                        slot: "frontend_scope_patch",
                        version: 1,
                    },
                ],
                summary: "Checkpoint recorded.",
                transient_surfaces: [],
            };
        case "boundary_accepted":
            return {
                assignment_decision_id: "decision-task-detail-1",
                assignment_id: `assignment-${nodeKey}`,
                attempt_id: `attempt-${nodeKey}`,
                checkpoint_id: "checkpoint-build-progress",
                checkpoint_ref: "_runtime/attempts/task-detail/latest-checkpoint.md",
                outcome: "green",
                resulting_flow_status: "running",
                source_dispatch_id: `dispatch-${nodeKey}`,
            };
        case "child_assignment_staged":
        case "child_assignment_committed":
            return {
                child_assignment_id: "assignment-task_detail_review",
                child_attempt_id: "attempt-task_detail_review",
                child_node_key: "task_detail_review",
                flow_revision_id: "flow-revision-task-detail-1",
                parent_assignment_id: "assignment-task_detail_page",
                source_dispatch_id: "dispatch-task_detail-page",
            };
        case "structural_revision_adopted":
            return {
                adopted_by_dispatch_id: "dispatch-task_detail-page",
                adopted_flow_revision_id: "flow-revision-task-detail-1",
                cause: "The Task Detail review child was admitted.",
                operation: "add_child",
                source_flow_revision_id: "flow-revision-task-detail-0",
                target_node_key: "task_detail_review",
            };
        case "human_request_opened":
            return {
                due_at: "2026-06-21T16:30:00Z",
                kind: "approval",
                opened_at: TASK_DETAIL_UPDATED_AT,
                request_id: "hr-task-detail-approval",
                source_dispatch_id: `dispatch-${nodeKey}`,
                summary: "Approval is needed for the last copy trim.",
            };
        case "human_request_resolved":
        case "human_request_timed_out":
        case "human_request_cancelled":
            return {
                due_at: "2026-06-21T16:30:00Z",
                kind: "approval",
                request_id: "hr-task-detail-approval",
                resolution_kind:
                    eventType === "human_request_resolved"
                        ? "answered"
                        : eventType === "human_request_timed_out"
                          ? "timed_out"
                          : "cancelled",
                resolution_summary: "The request reached a terminal controller state.",
                resolved_at: TASK_DETAIL_UPDATED_AT,
                resolved_by_actor_ref: "local_operator",
                resolved_by_surface:
                    eventType === "human_request_resolved" ? "control_api" : "controller",
                source_dispatch_id: `dispatch-${nodeKey}`,
                status:
                    eventType === "human_request_resolved"
                        ? "resolved"
                        : eventType === "human_request_timed_out"
                          ? "timed_out"
                          : "cancelled",
                summary: "Human request state changed.",
            };
        case "command_run_opened":
            return {
                command: "npm --prefix apps/console run typecheck",
                created_at: TASK_DETAIL_UPDATED_AT,
                description: "Verify the target-shaped runtime client.",
                ownership_revision: 0,
                run_id: "run-task-detail-check",
                source_dispatch_id: `dispatch-${nodeKey}`,
                state: "pending_start",
                timeout_seconds: 900,
                workdir: ".",
            };
        case "command_run_started":
            return {
                command: "npm --prefix apps/console run typecheck",
                description: "Verify the target-shaped runtime client.",
                due_at: "2026-06-21T16:00:00Z",
                log_refs: ["tmp/command-runs/run-task-detail-check.log"],
                ownership_revision: 1,
                run_id: "run-task-detail-check",
                source_dispatch_id: `dispatch-${nodeKey}`,
                started_at: TASK_DETAIL_UPDATED_AT,
                state: "running",
                workdir: ".",
            };
        case "command_run_progressed":
            return {
                log_ref: "tmp/command-runs/run-task-detail-check.log",
                occurred_at: TASK_DETAIL_UPDATED_AT,
                ownership_revision: 1,
                run_id: "run-task-detail-check",
                source_dispatch_id: `dispatch-${nodeKey}`,
                state: "running",
                summary: "The focused TypeScript check is still running.",
            };
        case "command_run_cancel_requested":
            return {
                ownership_revision: 1,
                requested_at: TASK_DETAIL_UPDATED_AT,
                run_id: "run-task-detail-check",
                source_dispatch_id: `dispatch-${nodeKey}`,
                state: "cancellation_requested",
            };
        case "command_run_succeeded":
            return commandTerminalPayload("succeeded", nodeKey);
        case "command_run_failed":
            return commandTerminalPayload("failed", nodeKey);
        case "command_run_timed_out":
            return commandTerminalPayload("timed_out", nodeKey);
        case "command_run_cancelled":
            return commandTerminalPayload("cancelled", nodeKey);
        case "command_run_abandoned":
            return commandTerminalPayload("abandoned", nodeKey);
        case "task_paused":
            return {
                actor_ref: "local_operator",
                control_revision: 2,
                pause_reason: "paused_by_operator",
                summary: "The local operator paused the task.",
            };
        case "task_resumed":
            return {
                actor_ref: "local_operator",
                control_revision: 3,
                summary: "The local operator resumed the task.",
            };
        case "task_cancelled":
            return {
                actor_ref: "local_operator",
                control_revision: 4,
                summary: "The local operator cancelled the task.",
            };
    }
}

function dispatchOpenedPayload(
    nodeKey: string,
    predecessorNodeKey: string | null,
): components["schemas"]["DispatchOpenedEventPayload"] {
    return {
        assignment_id: `assignment-${nodeKey}`,
        attempt_id: `attempt-${nodeKey}`,
        dispatch_id: `dispatch-${nodeKey}`,
        input_ref: `_runtime/dispatches/${nodeKey}/input.md`,
        instructions_ref: `_runtime/dispatches/${nodeKey}/instructions.md`,
        node_key: nodeKey,
        opened_reason: nodeKey === "root" ? "root" : "boundary",
        predecessor_dispatch_id:
            predecessorNodeKey === null ? null : `dispatch-${predecessorNodeKey}`,
        requested_provider: "codex",
        resolved_provider: "codex",
        selection_basis: "default",
        status: "starting",
    };
}

function commandTerminalPayload(
    state: components["schemas"]["CommandRunTerminalEventPayload"]["state"],
    nodeKey: string,
): components["schemas"]["CommandRunTerminalEventPayload"] {
    return {
        ended_at: TASK_DETAIL_UPDATED_AT,
        exit_code: state === "succeeded" ? 0 : null,
        failure_code: state === "abandoned" ? "command_ownership_lost" : null,
        log_refs: ["tmp/command-runs/run-task-detail-check.log"],
        ownership_revision: 1,
        run_id: "run-task-detail-check",
        source_dispatch_id: `dispatch-${nodeKey}`,
        started_at: TASK_DETAIL_UPDATED_AT,
        state,
        summary: "Command run state changed.",
    };
}

function occurredAtForEvent(eventType: TaskEventType, index: number): string {
    const visualTime = TASK_DETAIL_VISUAL_EVENT_TIMES[eventType];
    if (visualTime !== undefined) {
        return visualTime;
    }
    return new Date(Date.parse(TASK_DETAIL_EVENT_BASE_AT) + (index + 6) * 60_000).toISOString();
}

function eventSourceForType(eventType: TaskEventType): components["schemas"]["TaskEventSource"] {
    if (eventType === "task_started") {
        return "controller";
    }
    if (eventType.startsWith("task_") || eventType.startsWith("human_request_")) {
        return "control_api";
    }
    return "controller";
}

function createTaskEventStreamFrame(event: components["schemas"]["TaskEventRecord"]): string {
    return `id: ${event.event_id}\ndata: ${JSON.stringify(event)}\n\n`;
}
