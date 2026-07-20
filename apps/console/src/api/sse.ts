import { getConsoleConfig, type ConsoleConfig } from "../app/config";

import {
    AutoClawApiError,
    createApiErrorFromResponse,
    createApiTransportError,
    isCursorResetError,
    resolveApiUrl,
    type ConsoleErrorView,
} from "./client";
import type { components } from "./generated/openapi";
import { isTaskEventRecord, type TaskEventRecord } from "./task-event-validation";

export interface ServerSentEventFrame {
    readonly data: string;
    readonly event: string | null;
    readonly id: string | null;
}

export interface TaskEventStreamRequest {
    readonly headers: Headers;
    readonly url: URL;
}

export interface TaskEventStreamOptions {
    readonly config?: ConsoleConfig;
    readonly cursor?: string | null;
    readonly fetchImpl?: typeof fetch;
    readonly onEvent?: (event: components["schemas"]["TaskEventRecord"]) => void;
    readonly signal?: AbortSignal;
    readonly taskId: string;
}

export interface TaskEventStreamReadResult {
    readonly cursorResetRequired: boolean;
    readonly didResetCursor: boolean;
    readonly error: ConsoleErrorView | null;
    readonly events: readonly components["schemas"]["TaskEventRecord"][];
    readonly lastEventId: string | null;
    readonly staleCursor: string | null;
}

export interface TaskEventStreamReconnectOptions extends TaskEventStreamOptions {
    readonly resetAfterCursorReset: (
        staleCursor: string | null,
    ) => Promise<string | null> | string | null;
}

export interface TaskEventStreamSupervisionOptions extends TaskEventStreamReconnectOptions {
    readonly maxReconnectAttempts?: number;
    readonly onReconnect?: (attempt: number, cursor: string | null) => void;
    readonly reconnectDelayMs?: number;
}

export interface TaskEventStreamSupervisionResult extends TaskEventStreamReadResult {
    readonly reconnectAttempts: number;
    readonly reconnectExhausted: boolean;
}

export function taskEventStreamUrl(
    taskId: string,
    options: {
        readonly config?: ConsoleConfig;
        readonly cursor?: string | null;
    } = {},
): string {
    return buildTaskEventStreamRequest(taskId, options).url.toString();
}

export function buildTaskEventStreamRequest(
    taskId: string,
    options: {
        readonly config?: ConsoleConfig;
        readonly cursor?: string | null;
    } = {},
): TaskEventStreamRequest {
    const config = options.config ?? getConsoleConfig();
    const url = resolveApiUrl(
        `/control/tasks/${encodeURIComponent(taskId)}/events/stream`,
        config,
        options.cursor === null || options.cursor === undefined
            ? undefined
            : { cursor: options.cursor },
    );
    const headers = new Headers({ Accept: "text/event-stream" });

    return { headers, url };
}

export async function readTaskEventStream({
    config = getConsoleConfig(),
    cursor = null,
    fetchImpl = fetch,
    onEvent,
    signal,
    taskId,
}: TaskEventStreamOptions): Promise<TaskEventStreamReadResult> {
    const request = buildTaskEventStreamRequest(taskId, { config, cursor });
    let response: Response;
    try {
        response = await fetchImpl(request.url, {
            headers: request.headers,
            method: "GET",
            signal,
        });
    } catch (error) {
        throw createApiTransportError(error);
    }

    if (!response.ok) {
        const apiError = await createApiErrorFromResponse(response);
        if (isCursorResetError(apiError.errorView)) {
            return {
                cursorResetRequired: true,
                didResetCursor: false,
                error: apiError.errorView,
                events: [],
                lastEventId: null,
                staleCursor: cursor,
            };
        }
        throw apiError;
    }

    if (response.body === null) {
        return {
            cursorResetRequired: false,
            didResetCursor: false,
            error: null,
            events: [],
            lastEventId: null,
            staleCursor: null,
        };
    }

    const seenEventIds = new Set<string>();
    const events: components["schemas"]["TaskEventRecord"][] = [];

    for await (const frame of readServerSentEventFrames(response.body, signal)) {
        const event = readTaskEventFromFrame(frame, taskId);
        if (event === null || seenEventIds.has(event.event_id)) {
            continue;
        }

        seenEventIds.add(event.event_id);
        events.push(event);
        onEvent?.(event);
        if (signal?.aborted) {
            break;
        }
    }

    const orderedEvents = mergeTaskEvents(events);
    return {
        cursorResetRequired: false,
        didResetCursor: false,
        error: null,
        events: orderedEvents,
        lastEventId: lastTaskEventCursor(orderedEvents),
        staleCursor: null,
    };
}

export async function reconnectTaskEventStream(
    options: TaskEventStreamReconnectOptions,
): Promise<TaskEventStreamReadResult> {
    const firstResult = await readTaskEventStream(options);
    if (!firstResult.cursorResetRequired) {
        return firstResult;
    }

    const refreshedStreamHead = await options.resetAfterCursorReset(firstResult.staleCursor);
    const secondResult = await readTaskEventStream({
        ...options,
        cursor: refreshedStreamHead,
    });
    return {
        ...secondResult,
        didResetCursor: true,
        staleCursor: firstResult.staleCursor,
    };
}

export async function superviseTaskEventStream({
    maxReconnectAttempts = 3,
    onEvent,
    onReconnect,
    reconnectDelayMs = 1_000,
    ...options
}: TaskEventStreamSupervisionOptions): Promise<TaskEventStreamSupervisionResult> {
    const reconnectLimit = Math.max(0, Math.floor(maxReconnectAttempts));
    const seenEventIds = new Set<string>();
    let allEvents: readonly TaskEventRecord[] = [];
    let currentCursor = options.cursor ?? null;
    let didResetCursor = false;
    let staleCursor: string | null = null;

    for (let reconnectAttempts = 0; reconnectAttempts <= reconnectLimit; reconnectAttempts += 1) {
        let refreshedCursor = currentCursor;
        try {
            const result = await reconnectTaskEventStream({
                ...options,
                cursor: currentCursor,
                onEvent: (event) => {
                    if (seenEventIds.has(event.event_id)) {
                        return;
                    }
                    seenEventIds.add(event.event_id);
                    onEvent?.(event);
                },
                resetAfterCursorReset: async (resetCursor) => {
                    refreshedCursor = await options.resetAfterCursorReset(resetCursor);
                    return refreshedCursor;
                },
            });
            allEvents = mergeTaskEvents(allEvents, result.events);
            for (const event of result.events) {
                seenEventIds.add(event.event_id);
            }
            currentCursor = result.lastEventId ?? refreshedCursor;
            didResetCursor = didResetCursor || result.didResetCursor;
            staleCursor = result.staleCursor ?? staleCursor;

            if (options.signal?.aborted === true) {
                return {
                    ...result,
                    didResetCursor,
                    events: allEvents,
                    lastEventId: lastTaskEventCursor(allEvents),
                    reconnectAttempts,
                    reconnectExhausted: false,
                    staleCursor,
                };
            }

            if (reconnectAttempts >= reconnectLimit) {
                return {
                    ...result,
                    didResetCursor,
                    events: allEvents,
                    lastEventId: lastTaskEventCursor(allEvents),
                    reconnectAttempts,
                    reconnectExhausted: true,
                    staleCursor,
                };
            }
        } catch (error) {
            if (!isRetryableStreamError(error) || reconnectAttempts >= reconnectLimit) {
                throw error;
            }
        }

        onReconnect?.(reconnectAttempts + 1, currentCursor);
        await waitForReconnectDelay(reconnectDelayMs, options.signal);
    }

    throw new Error("Task event stream supervision exceeded its reconnect bound");
}

export async function* readServerSentEventFrames(
    body: ReadableStream<Uint8Array>,
    signal?: AbortSignal,
): AsyncGenerator<ServerSentEventFrame> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
        while (!signal?.aborted) {
            const readResult = await reader.read();
            buffer += decoder.decode(readResult.value, { stream: !readResult.done });

            let boundary = findFrameBoundary(buffer);
            while (boundary !== null && !signal?.aborted) {
                const rawFrame = buffer.slice(0, boundary.index);
                buffer = buffer.slice(boundary.index + boundary.length);
                const frame = parseServerSentEventFrame(rawFrame);
                if (frame !== null) {
                    yield frame;
                }
                boundary = findFrameBoundary(buffer);
            }

            if (readResult.done) {
                break;
            }
        }

        if (buffer.trim() !== "" && !signal?.aborted) {
            const frame = parseServerSentEventFrame(buffer);
            if (frame !== null) {
                yield frame;
            }
        }
    } finally {
        reader.releaseLock();
    }
}

export function parseServerSentEventFrame(rawFrame: string): ServerSentEventFrame | null {
    const dataLines: string[] = [];
    let event: string | null = null;
    let id: string | null = null;

    for (const line of rawFrame.split(/\r?\n/)) {
        if (line === "" || line.startsWith(":")) {
            continue;
        }

        const separatorIndex = line.indexOf(":");
        const field = separatorIndex === -1 ? line : line.slice(0, separatorIndex);
        const rawValue = separatorIndex === -1 ? "" : line.slice(separatorIndex + 1);
        const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;

        if (field === "data") {
            dataLines.push(value);
        } else if (field === "event") {
            event = value;
        } else if (field === "id") {
            id = value;
        }
    }

    if (dataLines.length === 0 && event === null && id === null) {
        return null;
    }

    return {
        data: dataLines.join("\n"),
        event,
        id,
    };
}

export function mergeTaskEvents(
    ...eventBatches: readonly (readonly components["schemas"]["TaskEventRecord"][])[]
): readonly components["schemas"]["TaskEventRecord"][] {
    const eventById = new Map<string, components["schemas"]["TaskEventRecord"]>();
    for (const eventBatch of eventBatches) {
        for (const event of eventBatch) {
            eventById.set(event.event_id, event);
        }
    }

    return [...eventById.values()].sort((left, right) => left.event_seq - right.event_seq);
}

export function lastTaskEventCursor(
    events: readonly components["schemas"]["TaskEventRecord"][],
): string | null {
    return events.at(-1)?.event_id ?? null;
}

function readTaskEventFromFrame(
    frame: ServerSentEventFrame,
    expectedTaskId: string,
): components["schemas"]["TaskEventRecord"] | null {
    if (frame.data.trim() === "") {
        return null;
    }

    const parsedData = parseJsonFrameData(frame.data);
    if (!isTaskEventRecord(parsedData)) {
        throw new AutoClawApiError({
            code: "invalid_sse_event",
            title: "Invalid SSE Event",
            summary:
                "The task event stream returned an event that did not match the task-event shape.",
            status: null,
            isRetryable: true,
            suggestedNextStep: "Reconnect to the task event stream.",
            fieldErrors: [],
            source: "stream",
        });
    }

    if (parsedData.task_id !== expectedTaskId) {
        throw taskEventStreamError(
            "cross_task_sse_event",
            "Cross-task SSE Event",
            "The task event stream returned an event for a different task.",
        );
    }

    if (frame.id !== null && frame.id !== parsedData.event_id) {
        throw new AutoClawApiError({
            code: "conflicting_sse_event_id",
            title: "Conflicting SSE Event Id",
            summary: "The task event stream frame id did not match the payload event id.",
            status: null,
            isRetryable: true,
            suggestedNextStep: "Reconnect to the task event stream.",
            fieldErrors: [],
            source: "stream",
        });
    }

    if (frame.event !== null && frame.event !== parsedData.event_type) {
        throw new AutoClawApiError({
            code: "conflicting_sse_event_type",
            title: "Conflicting SSE Event Type",
            summary: "The task event stream frame type did not match the payload event type.",
            status: null,
            isRetryable: true,
            suggestedNextStep: "Reconnect to the task event stream.",
            fieldErrors: [],
            source: "stream",
        });
    }

    return parsedData;
}

function parseJsonFrameData(data: string): unknown {
    try {
        return JSON.parse(data) as unknown;
    } catch {
        return null;
    }
}

function taskEventStreamError(code: string, title: string, summary: string): AutoClawApiError {
    return new AutoClawApiError({
        code,
        title,
        summary,
        status: null,
        isRetryable: true,
        suggestedNextStep: "Reconnect to the task event stream.",
        fieldErrors: [],
        source: "stream",
    });
}

function isRetryableStreamError(error: unknown): boolean {
    return (
        error instanceof AutoClawApiError &&
        error.errorView.source !== "abort" &&
        error.errorView.isRetryable
    );
}

async function waitForReconnectDelay(delayMs: number, signal?: AbortSignal): Promise<void> {
    if (signal?.aborted === true) {
        throw createApiTransportError(new DOMException("Aborted", "AbortError"));
    }
    if (delayMs <= 0) {
        return;
    }

    await new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
            signal?.removeEventListener("abort", handleAbort);
            resolve();
        }, delayMs);
        const handleAbort = () => {
            window.clearTimeout(timeoutId);
            reject(createApiTransportError(new DOMException("Aborted", "AbortError")));
        };
        signal?.addEventListener("abort", handleAbort, { once: true });
    });
}

function findFrameBoundary(
    buffer: string,
): { readonly index: number; readonly length: number } | null {
    const lineFeedBoundary = buffer.indexOf("\n\n");
    const carriageBoundary = buffer.indexOf("\r\n\r\n");

    if (lineFeedBoundary === -1 && carriageBoundary === -1) {
        return null;
    }

    if (lineFeedBoundary === -1) {
        return { index: carriageBoundary, length: 4 };
    }

    if (carriageBoundary === -1 || lineFeedBoundary < carriageBoundary) {
        return { index: lineFeedBoundary, length: 2 };
    }

    return { index: carriageBoundary, length: 4 };
}
