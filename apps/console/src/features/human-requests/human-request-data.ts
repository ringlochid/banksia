import { requestJson } from "../../api/client";
import type { components } from "../../api/generated/openapi";
import {
    controlTaskRoute,
    controlTaskSnapshotRoute,
    humanRequestsRoute,
    resolveHumanRequestRoute,
} from "../../api/routes";
import { superviseTaskEventStream, type TaskEventStreamSupervisionResult } from "../../api/sse";

export interface HumanRequestsPageData {
    readonly requestList: components["schemas"]["HumanRequestListResponse"];
    readonly streamHeadEventId: string | null;
    readonly task: components["schemas"]["RuntimeFlowRead"];
}

export async function readHumanRequestsPageData(
    taskId: string,
    signal?: AbortSignal,
): Promise<HumanRequestsPageData> {
    const requestListRoute = humanRequestsRoute(taskId);
    const snapshotRoute = controlTaskSnapshotRoute(taskId);
    const taskRoute = controlTaskRoute(taskId);
    const snapshot = await requestJson<components["schemas"]["OperatorFlowSnapshotResponse"]>({
        path: snapshotRoute.path,
        signal,
    });
    const [requestList, task] = await Promise.all([
        requestJson<components["schemas"]["HumanRequestListResponse"]>({
            path: requestListRoute.path,
            signal,
        }),
        requestJson<components["schemas"]["RuntimeFlowRead"]>({
            path: taskRoute.path,
            signal,
        }),
    ]);

    return {
        requestList,
        streamHeadEventId: snapshot.stream_head_event_id ?? null,
        task,
    };
}

export async function resolveHumanRequest(
    taskId: string,
    requestId: string,
    body: components["schemas"]["HumanRequestResolveRequest"],
): Promise<components["schemas"]["HumanRequestResolveResponse"]> {
    const route = resolveHumanRequestRoute(taskId, requestId);
    return requestJson<components["schemas"]["HumanRequestResolveResponse"]>({
        body,
        method: "POST",
        path: route.path,
    });
}

export async function streamHumanRequestEvents({
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
            if (isHumanRequestSourceEvent(event.event_type)) {
                onSourceEvent();
            }
        },
        reconnectDelayMs: 100,
        resetAfterCursorReset,
        signal,
        taskId,
    });
}

function isHumanRequestSourceEvent(
    eventType: components["schemas"]["TaskEventRecord"]["event_type"],
): boolean {
    return (
        eventType.startsWith("human_request_") ||
        eventType === "task_paused" ||
        eventType === "task_resumed" ||
        eventType === "task_cancelled"
    );
}
