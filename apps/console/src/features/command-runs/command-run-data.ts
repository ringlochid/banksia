import {
    isApiAbortError,
    mapUnknownApiError,
    requestJson,
    type ConsoleErrorView,
} from "../../api/client";
import type { components } from "../../api/generated/openapi";
import {
    cancelCommandRunRoute,
    commandRunLogRoute,
    commandRunRoute,
    commandRunsRoute,
    controlTaskRoute,
    controlTaskSnapshotRoute,
} from "../../api/routes";
import { superviseTaskEventStream, type TaskEventStreamSupervisionResult } from "../../api/sse";
import { mapCommandRunDetailView, type CommandRunDetailView } from "./command-run-model";

const COMMAND_RUN_PAGE_SIZE = 25;

export type CommandRunListResponse = components["schemas"]["CommandRunListResponse"];
export type CommandRunCancelResponse = components["schemas"]["CommandRunCancelResponse"];
export type CommandRunLogReadResponse = components["schemas"]["CommandRunLogReadResponse"];

export async function readCommandRunsPageData(
    taskId: string,
    signal: AbortSignal,
): Promise<{
    readonly commandRunList: CommandRunListResponse;
    readonly streamHeadEventId: string | null;
    readonly task: components["schemas"]["RuntimeFlowRead"];
}> {
    const taskRoute = controlTaskRoute(taskId);
    const snapshotRoute = controlTaskSnapshotRoute(taskId);
    const snapshot = await requestJson<components["schemas"]["OperatorFlowSnapshotResponse"]>({
        path: snapshotRoute.path,
        signal,
    });
    const [commandRunList, task] = await Promise.all([
        readCommandRunPage({ cursor: null, signal, taskId }),
        requestJson<components["schemas"]["RuntimeFlowRead"]>({
            path: taskRoute.path,
            signal,
        }),
    ]);

    return {
        commandRunList,
        streamHeadEventId: snapshot.stream_head_event_id ?? null,
        task,
    };
}

export async function readCommandRunPage({
    cursor,
    signal,
    taskId,
}: {
    readonly cursor: string | null;
    readonly signal: AbortSignal | undefined;
    readonly taskId: string;
}): Promise<CommandRunListResponse> {
    const route = commandRunsRoute(taskId, {
        cursor,
        limit: COMMAND_RUN_PAGE_SIZE,
    });
    return requestJson<CommandRunListResponse>({
        path: route.path,
        query: route.query,
        signal,
    });
}

export async function readCommandRunDetail(
    taskId: string,
    runId: string,
    signal?: AbortSignal,
): Promise<CommandRunDetailView> {
    const route = commandRunRoute(taskId, runId);
    const record = await requestJson<components["schemas"]["CommandRunRecord"]>({
        path: route.path,
        signal,
    });
    return mapCommandRunDetailView(record);
}

export async function readCommandRunLog(
    taskId: string,
    runId: string,
): Promise<CommandRunLogReadResponse> {
    const route = commandRunLogRoute(taskId, runId);
    return requestJson<CommandRunLogReadResponse>({
        path: route.path,
    });
}

export async function cancelCommandRun(
    taskId: string,
    runId: string,
): Promise<CommandRunCancelResponse> {
    const route = cancelCommandRunRoute(taskId, runId);
    return requestJson<CommandRunCancelResponse>({
        method: "POST",
        path: route.path,
    });
}

export function toErrorView(error: unknown): ConsoleErrorView {
    return mapUnknownApiError(error);
}

export function isAbortError(error: unknown): boolean {
    return isApiAbortError(error);
}

export async function streamCommandRunEvents({
    cursor,
    onSourceEvent,
    resetAfterCursorReset,
    signal,
    taskId,
}: {
    readonly cursor: string | null;
    readonly onSourceEvent: () => void;
    readonly resetAfterCursorReset: () => Promise<string | null>;
    readonly signal: AbortSignal;
    readonly taskId: string;
}): Promise<TaskEventStreamSupervisionResult> {
    return superviseTaskEventStream({
        cursor,
        maxReconnectAttempts: 2,
        onEvent: (event) => {
            if (isCommandRunSourceEvent(event.event_type)) {
                onSourceEvent();
            }
        },
        reconnectDelayMs: 100,
        resetAfterCursorReset,
        signal,
        taskId,
    });
}

function isCommandRunSourceEvent(
    eventType: components["schemas"]["TaskEventRecord"]["event_type"],
): boolean {
    return (
        eventType.startsWith("command_run_") ||
        eventType === "task_paused" ||
        eventType === "task_resumed" ||
        eventType === "task_cancelled"
    );
}
