import { requestJson } from "../../api/client";
import type { components } from "../../api/generated/openapi";
import {
    commandRunsRoute,
    controlTaskActionRoute,
    controlTaskEventsRoute,
    controlTaskRoute,
    controlTaskSnapshotRoute,
    controlTaskTraceRoute,
    humanRequestsRoute,
} from "../../api/routes";
import {
    mergeTaskEvents,
    superviseTaskEventStream,
    type TaskEventStreamSupervisionResult,
} from "../../api/sse";

export type TaskControlAction = "cancel" | "continue" | "pause";

export interface TaskDetailBootstrap {
    readonly commandRuns: components["schemas"]["CommandRunListResponse"];
    readonly events: components["schemas"]["TaskEventRecord"][];
    readonly humanRequests: components["schemas"]["HumanRequestListResponse"];
    readonly snapshot: components["schemas"]["OperatorFlowSnapshotResponse"];
    readonly task: components["schemas"]["RuntimeFlowRead"];
    readonly trace: components["schemas"]["OperatorFlowTraceResponse"];
}

export interface TaskDetailStreamOptions {
    readonly cursor: string | null;
    readonly onEvent: (event: components["schemas"]["TaskEventRecord"]) => void;
    readonly onReconnect: () => void;
    readonly resetAfterCursorReset: (staleCursor: string | null) => Promise<string | null>;
    readonly signal: AbortSignal;
    readonly taskId: string;
}

const TASK_EVENT_PAGE_SIZE = 200;
const TRACE_PAGE_SIZE = 120;
const SIBLING_PREVIEW_PAGE_SIZE = 6;

export async function readTaskDetailBootstrap(
    taskId: string,
    signal?: AbortSignal,
): Promise<TaskDetailBootstrap> {
    const taskRoute = controlTaskRoute(taskId);
    const snapshotRoute = controlTaskSnapshotRoute(taskId);
    const traceRoute = controlTaskTraceRoute(taskId, {
        limit: TRACE_PAGE_SIZE,
        scope: "whole",
        sort: "occurred_at_asc",
    });
    const humanRequests = humanRequestsRoute(taskId);
    const commandRuns = commandRunsRoute(taskId, { limit: SIBLING_PREVIEW_PAGE_SIZE });

    const snapshot = await requestJson<components["schemas"]["OperatorFlowSnapshotResponse"]>({
        path: snapshotRoute.path,
        signal,
    });
    const [task, trace, humanRequestList, commandRunList, events] = await Promise.all([
        requestJson<components["schemas"]["RuntimeFlowRead"]>({
            path: taskRoute.path,
            signal,
        }),
        requestJson<components["schemas"]["OperatorFlowTraceResponse"]>({
            path: traceRoute.path,
            query: traceRoute.query,
            signal,
        }),
        requestJson<components["schemas"]["HumanRequestListResponse"]>({
            path: humanRequests.path,
            signal,
        }),
        requestJson<components["schemas"]["CommandRunListResponse"]>({
            path: commandRuns.path,
            query: commandRuns.query,
            signal,
        }),
        readTaskEventBackfill(taskId, snapshot.stream_head_event_id ?? null, signal),
    ]);

    return {
        commandRuns: commandRunList,
        events,
        humanRequests: humanRequestList,
        snapshot,
        task,
        trace,
    };
}

export async function readTaskEventBackfill(
    taskId: string,
    throughEventId: string | null,
    signal?: AbortSignal,
): Promise<components["schemas"]["TaskEventRecord"][]> {
    if (throughEventId === null) {
        return [];
    }

    let cursor: string | null = null;
    let events: components["schemas"]["TaskEventRecord"][] = [];

    do {
        const route = controlTaskEventsRoute(taskId, {
            cursor: cursor ?? undefined,
            limit: TASK_EVENT_PAGE_SIZE,
            through_event_id: throughEventId,
        });
        const response = await requestJson<components["schemas"]["TaskEventListResponse"]>({
            path: route.path,
            query: route.query,
            signal,
        });

        events = [...mergeTaskEvents(events, response.items)];
        cursor = response.next_cursor ?? null;
    } while (cursor !== null);

    return events;
}

export async function streamTaskDetailEvents({
    cursor,
    onEvent,
    onReconnect,
    resetAfterCursorReset,
    signal,
    taskId,
}: TaskDetailStreamOptions): Promise<TaskEventStreamSupervisionResult> {
    return superviseTaskEventStream({
        cursor,
        maxReconnectAttempts: 2,
        onEvent,
        onReconnect,
        reconnectDelayMs: 100,
        resetAfterCursorReset,
        signal,
        taskId,
    });
}

export async function writeTaskControlAction({
    activeFlowRevisionId,
    action,
    controlRevision,
    signal,
    taskId,
}: {
    readonly activeFlowRevisionId: string;
    readonly action: TaskControlAction;
    readonly controlRevision: number;
    readonly signal?: AbortSignal;
    readonly taskId: string;
}): Promise<components["schemas"]["RuntimeFlowRead"]> {
    const route = controlTaskActionRoute(taskId, action);
    const response = await requestJson<
        components["schemas"]["RuntimeFlowPauseResponse"] | components["schemas"]["RuntimeFlowRead"]
    >({
        body: {
            expected_active_flow_revision_id: activeFlowRevisionId,
            expected_control_revision: controlRevision,
        } satisfies components["schemas"]["RuntimeFlowControlRequest"],
        method: "POST",
        path: route.path,
        signal,
    });

    if (isPauseResponse(response)) {
        return response.flow;
    }

    return response;
}

function isPauseResponse(
    response:
        | components["schemas"]["RuntimeFlowPauseResponse"]
        | components["schemas"]["RuntimeFlowRead"],
): response is components["schemas"]["RuntimeFlowPauseResponse"] {
    return "flow" in response;
}
