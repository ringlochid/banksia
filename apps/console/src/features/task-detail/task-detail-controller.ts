import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import { isApiAbortError, mapUnknownApiError, type ConsoleErrorView } from "../../api/client";
import type { components } from "../../api/generated/openapi";
import { mergeTaskEvents } from "../../api/sse";
import {
    readTaskDetailBootstrap,
    streamTaskDetailEvents,
    writeTaskControlAction,
    type TaskControlAction,
    type TaskDetailBootstrap,
} from "./task-detail-data";
import {
    buildSelectedContext,
    buildTaskDetailView,
    getDefaultEventId,
    getDefaultNodeKey,
    type TaskDetailTab,
    type TaskDetailView,
} from "./task-detail-model";

export type TaskEventStreamStatus = "closed" | "connecting" | "live" | "reconnecting" | "reset";

export interface TaskDetailController {
    readonly actionError: ConsoleErrorView | null;
    readonly actionPending: TaskControlAction | null;
    readonly closeDetail: () => void;
    readonly detailOpen: boolean;
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
    readonly isRefreshing: boolean;
    readonly openDetail: () => void;
    readonly refresh: () => void;
    readonly selectedContext: ReturnType<typeof buildSelectedContext> | null;
    readonly selectedEventId: string | null;
    readonly selectedNodeKey: string | null;
    readonly selectEvent: (eventId: string) => void;
    readonly selectNode: (nodeKey: string) => void;
    readonly setDetailTab: (tab: TaskDetailTab) => void;
    readonly streamError: ConsoleErrorView | null;
    readonly streamResetStaleCursor: string | null;
    readonly streamStatus: TaskEventStreamStatus;
    readonly tab: TaskDetailTab;
    readonly taskAction: (action: TaskControlAction) => void;
    readonly view: TaskDetailView | null;
}

interface TaskDetailState {
    readonly actionError: ConsoleErrorView | null;
    readonly hasExplicitSelection: boolean;
    readonly actionPending: TaskControlAction | null;
    readonly bootstrap: TaskDetailBootstrap | null;
    readonly detailOpen: boolean;
    readonly error: ConsoleErrorView | null;
    readonly events: readonly components["schemas"]["TaskEventRecord"][];
    readonly isLoading: boolean;
    readonly isRefreshing: boolean;
    readonly refreshToken: number;
    readonly selectedEventId: string | null;
    readonly selectedNodeKey: string | null;
    readonly streamError: ConsoleErrorView | null;
    readonly streamResetStaleCursor: string | null;
    readonly streamStatus: TaskEventStreamStatus;
    readonly tab: TaskDetailTab;
}

type TaskDetailAction =
    | { readonly type: "action-error"; readonly error: ConsoleErrorView }
    | { readonly action: TaskControlAction; readonly type: "action-start" }
    | { readonly task: components["schemas"]["RuntimeFlowRead"]; readonly type: "action-success" }
    | {
          readonly bootstrap: TaskDetailBootstrap;
          readonly isRefresh: boolean;
          readonly type: "bootstrap-success";
      }
    | { readonly bootstrap: TaskDetailBootstrap; readonly type: "cursor-reset-bootstrap" }
    | { readonly isRefresh: boolean; readonly type: "load-start" }
    | { readonly error: ConsoleErrorView; readonly type: "load-error" }
    | { readonly type: "close-detail" }
    | { readonly event: components["schemas"]["TaskEventRecord"]; readonly type: "live-event" }
    | {
          readonly events: readonly components["schemas"]["TaskEventRecord"][];
          readonly type: "live-events";
      }
    | { readonly type: "open-detail" }
    | { readonly type: "refresh" }
    | { readonly eventId: string; readonly type: "select-event" }
    | { readonly nodeKey: string; readonly type: "select-node" }
    | { readonly status: TaskEventStreamStatus; readonly type: "stream-status" }
    | { readonly staleCursor: string | null; readonly type: "stream-reset" }
    | { readonly error: ConsoleErrorView; readonly type: "stream-error" }
    | { readonly tab: TaskDetailTab; readonly type: "tab" };

const initialState: TaskDetailState = {
    actionError: null,
    actionPending: null,
    bootstrap: null,
    detailOpen: false,
    error: null,
    events: [],
    hasExplicitSelection: false,
    isLoading: true,
    isRefreshing: false,
    refreshToken: 0,
    selectedEventId: null,
    selectedNodeKey: null,
    streamError: null,
    streamResetStaleCursor: null,
    streamStatus: "closed",
    tab: "summary",
};

export function useTaskDetailController(taskId: string | null): TaskDetailController {
    const [state, dispatch] = useReducer(taskDetailReducer, initialState);
    const hasBootstrapRef = useRef(false);
    const readGenerationRef = useRef(0);

    useEffect(() => {
        const readGeneration = readGenerationRef.current + 1;
        readGenerationRef.current = readGeneration;
        if (taskId === null) {
            dispatch({
                error: {
                    code: "missing_task_id",
                    fieldErrors: [],
                    isRetryable: false,
                    source: "http",
                    status: null,
                    suggestedNextStep: "Open Task Detail from a task row.",
                    summary: "Task Detail requires a task id in the route.",
                    title: "Missing Task Id",
                },
                type: "load-error",
            });
            return;
        }

        const currentTaskId = taskId;
        const abortController = new AbortController();
        let sourceRefreshTimer: ReturnType<typeof setTimeout> | null = null;
        let sourceRefreshInFlight = false;
        let sourceRefreshQueued = false;
        const isRefresh = hasBootstrapRef.current;
        const isCurrentRead = () =>
            readGenerationRef.current === readGeneration && !abortController.signal.aborted;

        async function refreshCommittedSource(): Promise<void> {
            if (sourceRefreshInFlight) {
                sourceRefreshQueued = true;
                return;
            }

            sourceRefreshInFlight = true;
            try {
                const refreshedBootstrap = await readTaskDetailBootstrap(
                    currentTaskId,
                    abortController.signal,
                );
                if (!isCurrentRead()) {
                    return;
                }
                hasBootstrapRef.current = true;
                dispatch({
                    bootstrap: refreshedBootstrap,
                    isRefresh: true,
                    type: "bootstrap-success",
                });
            } catch (error) {
                if (isCurrentRead() && !isAbortError(error)) {
                    dispatch({ error: toErrorView(error), type: "stream-error" });
                }
            } finally {
                sourceRefreshInFlight = false;
                if (sourceRefreshQueued && isCurrentRead()) {
                    sourceRefreshQueued = false;
                    void refreshCommittedSource();
                }
            }
        }

        function scheduleCommittedSourceRefresh(): void {
            if (sourceRefreshTimer !== null) {
                clearTimeout(sourceRefreshTimer);
            }
            sourceRefreshTimer = setTimeout(() => {
                sourceRefreshTimer = null;
                if (isCurrentRead()) {
                    void refreshCommittedSource();
                }
            }, 25);
        }

        async function runTaskDetailRead(): Promise<void> {
            dispatch({ isRefresh, type: "load-start" });
            try {
                const bootstrap = await readTaskDetailBootstrap(
                    currentTaskId,
                    abortController.signal,
                );
                if (!isCurrentRead()) {
                    return;
                }
                hasBootstrapRef.current = true;
                dispatch({ bootstrap, isRefresh, type: "bootstrap-success" });
                dispatch({ status: "connecting", type: "stream-status" });

                const streamCursor = bootstrap.snapshot.stream_head_event_id ?? null;
                const streamResult = await streamTaskDetailEvents({
                    cursor: streamCursor,
                    onEvent: (event) => {
                        if (!isCurrentRead()) {
                            return;
                        }
                        dispatch({ event, type: "live-event" });
                        scheduleCommittedSourceRefresh();
                    },
                    onReconnect: () => {
                        if (isCurrentRead()) {
                            dispatch({ status: "reconnecting", type: "stream-status" });
                        }
                    },
                    resetAfterCursorReset: async (staleCursor) => {
                        if (!isCurrentRead()) {
                            return null;
                        }
                        dispatch({ staleCursor, type: "stream-reset" });
                        const resetBootstrap = await readTaskDetailBootstrap(
                            currentTaskId,
                            abortController.signal,
                        );
                        if (!isCurrentRead()) {
                            return null;
                        }
                        hasBootstrapRef.current = true;
                        dispatch({
                            bootstrap: resetBootstrap,
                            type: "cursor-reset-bootstrap",
                        });
                        dispatch({ status: "reconnecting", type: "stream-status" });
                        return resetBootstrap.snapshot.stream_head_event_id ?? null;
                    },
                    signal: abortController.signal,
                    taskId: currentTaskId,
                });
                if (!isCurrentRead()) {
                    return;
                }

                if (streamResult.events.length > 0) {
                    dispatch({ events: streamResult.events, type: "live-events" });
                }
                if (streamResult.didResetCursor) {
                    dispatch({
                        staleCursor: streamResult.staleCursor,
                        type: "stream-reset",
                    });
                }
                dispatch({ status: "closed", type: "stream-status" });
            } catch (error) {
                if (!isCurrentRead() || isAbortError(error)) {
                    return;
                }
                if (!hasBootstrapRef.current) {
                    dispatch({ error: toErrorView(error), type: "load-error" });
                    return;
                }
                dispatch({ error: toErrorView(error), type: "stream-error" });
            }
        }

        void runTaskDetailRead();

        return () => {
            if (sourceRefreshTimer !== null) {
                clearTimeout(sourceRefreshTimer);
            }
            abortController.abort();
        };
    }, [state.refreshToken, taskId]);

    const view = useMemo(() => {
        if (state.bootstrap === null) {
            return null;
        }

        return buildTaskDetailView({
            bootstrap: state.bootstrap,
            events: state.events,
        });
    }, [state.bootstrap, state.events]);

    const selectedContext = useMemo(() => {
        if (view === null) {
            return null;
        }

        return buildSelectedContext({
            eventId: state.selectedEventId,
            nodeKey: state.selectedNodeKey,
            view,
        });
    }, [state.selectedEventId, state.selectedNodeKey, view]);

    const taskAction = useCallback(
        (action: TaskControlAction) => {
            if (state.bootstrap === null || taskId === null) {
                return;
            }

            dispatch({ action, type: "action-start" });
            void writeTaskControlAction({
                action,
                activeFlowRevisionId: state.bootstrap.task.active_flow_revision_id,
                controlRevision: state.bootstrap.task.control_revision,
                taskId,
            })
                .then((task) => {
                    dispatch({ task, type: "action-success" });
                })
                .catch(async (error: unknown) => {
                    if (isAbortError(error)) {
                        return;
                    }
                    const errorView = toErrorView(error);
                    dispatch({ error: errorView, type: "action-error" });
                    if (!isStaleActionError(errorView.code)) {
                        return;
                    }

                    try {
                        const refreshedBootstrap = await readTaskDetailBootstrap(taskId);
                        hasBootstrapRef.current = true;
                        dispatch({
                            bootstrap: refreshedBootstrap,
                            isRefresh: true,
                            type: "bootstrap-success",
                        });
                    } catch (refreshError) {
                        if (!isAbortError(refreshError)) {
                            dispatch({
                                error: toErrorView(refreshError),
                                type: "stream-error",
                            });
                        }
                    }
                });
        },
        [state.bootstrap, taskId],
    );

    return {
        actionError: state.actionError,
        actionPending: state.actionPending,
        closeDetail: () => {
            dispatch({ type: "close-detail" });
        },
        detailOpen: state.detailOpen,
        error: state.error,
        isLoading: state.isLoading,
        isRefreshing: state.isRefreshing,
        openDetail: () => {
            dispatch({ type: "open-detail" });
        },
        refresh: () => {
            dispatch({ type: "refresh" });
        },
        selectedContext,
        selectedEventId: state.selectedEventId,
        selectedNodeKey: state.selectedNodeKey,
        selectEvent: (eventId) => {
            dispatch({ eventId, type: "select-event" });
        },
        selectNode: (nodeKey) => {
            dispatch({ nodeKey, type: "select-node" });
        },
        setDetailTab: (tab) => {
            dispatch({ tab, type: "tab" });
        },
        streamError: state.streamError,
        streamResetStaleCursor: state.streamResetStaleCursor,
        streamStatus: state.streamStatus,
        tab: state.tab,
        taskAction,
        view,
    };
}

function taskDetailReducer(state: TaskDetailState, action: TaskDetailAction): TaskDetailState {
    switch (action.type) {
        case "load-start":
            return {
                ...state,
                actionError: null,
                error: null,
                isLoading: !action.isRefresh,
                isRefreshing: action.isRefresh,
                streamError: null,
            };
        case "bootstrap-success":
            return applyBootstrapSuccess(state, action.bootstrap);
        case "cursor-reset-bootstrap":
            return applyCursorResetBootstrap(state, action.bootstrap);
        case "load-error":
            return {
                ...state,
                bootstrap: null,
                error: action.error,
                events: [],
                isLoading: false,
                isRefreshing: false,
                streamStatus: "closed",
                streamResetStaleCursor: null,
            };
        case "live-event":
            return applyLiveEvents(state, [action.event], "live");
        case "live-events":
            return applyLiveEvents(state, action.events, state.streamStatus);
        case "stream-status":
            return {
                ...state,
                streamStatus: action.status,
            };
        case "stream-reset":
            return {
                ...state,
                streamError: null,
                streamResetStaleCursor: action.staleCursor,
                streamStatus: "reset",
            };
        case "stream-error":
            return {
                ...state,
                streamError: action.error,
                streamResetStaleCursor: null,
                streamStatus: "closed",
            };
        case "select-node":
            return applyNodeSelection(state, action.nodeKey);
        case "select-event":
            return applyEventSelection(state, action.eventId);
        case "open-detail":
            return {
                ...state,
                detailOpen: true,
            };
        case "close-detail":
            return {
                ...state,
                detailOpen: false,
            };
        case "tab":
            return {
                ...state,
                tab: action.tab,
            };
        case "refresh":
            return {
                ...state,
                refreshToken: state.refreshToken + 1,
            };
        case "action-start":
            return {
                ...state,
                actionError: null,
                actionPending: action.action,
            };
        case "action-success":
            return applyActionSuccess(state, action.task);
        case "action-error":
            return {
                ...state,
                actionError: action.error,
                actionPending: null,
            };
    }
}

function applyBootstrapSuccess(
    state: TaskDetailState,
    bootstrap: TaskDetailBootstrap,
): TaskDetailState {
    const events = mergeTaskEvents(state.events, bootstrap.events);
    const view = buildTaskDetailView({
        bootstrap,
        events,
    });
    const selectedNodeKey = state.selectedNodeKey ?? getDefaultNodeKey(view);
    const selectedEventId = state.selectedEventId ?? getDefaultEventId(view, selectedNodeKey);

    return {
        ...state,
        bootstrap,
        error: null,
        events,
        isLoading: false,
        isRefreshing: false,
        selectedEventId,
        selectedNodeKey,
        streamError: null,
    };
}

function applyCursorResetBootstrap(
    state: TaskDetailState,
    bootstrap: TaskDetailBootstrap,
): TaskDetailState {
    const events = bootstrap.events;
    const view = buildTaskDetailView({ bootstrap, events });
    const selectedNodeKey = view.graphNodes.some((node) => node.nodeKey === state.selectedNodeKey)
        ? state.selectedNodeKey
        : getDefaultNodeKey(view);
    const selectedEventId = events.some((event) => event.event_id === state.selectedEventId)
        ? state.selectedEventId
        : getDefaultEventId(view, selectedNodeKey);

    return {
        ...state,
        bootstrap,
        error: null,
        events,
        isLoading: false,
        isRefreshing: false,
        selectedEventId,
        selectedNodeKey,
        streamError: null,
    };
}

function applyActionSuccess(
    state: TaskDetailState,
    task: components["schemas"]["RuntimeFlowRead"],
): TaskDetailState {
    if (state.bootstrap === null) {
        return {
            ...state,
            actionPending: null,
        };
    }

    return {
        ...state,
        actionError: null,
        actionPending: null,
        bootstrap: {
            ...state.bootstrap,
            task,
        },
    };
}

function applyLiveEvents(
    state: TaskDetailState,
    events: readonly components["schemas"]["TaskEventRecord"][],
    streamStatus: TaskEventStreamStatus,
): TaskDetailState {
    const focusEvent = state.hasExplicitSelection ? null : latestNodeEvent(events);
    return {
        ...state,
        events: mergeTaskEvents(state.events, events),
        selectedEventId: focusEvent?.event_id ?? state.selectedEventId,
        selectedNodeKey: focusEvent?.node_key ?? state.selectedNodeKey,
        streamError: null,
        streamStatus,
    };
}

function latestNodeEvent(
    events: readonly components["schemas"]["TaskEventRecord"][],
): components["schemas"]["TaskEventRecord"] | null {
    for (let index = events.length - 1; index >= 0; index -= 1) {
        const event = events[index];
        if (event.node_key !== null) {
            return event;
        }
    }
    return null;
}

function applyNodeSelection(state: TaskDetailState, nodeKey: string): TaskDetailState {
    if (state.bootstrap === null) {
        return {
            ...state,
            hasExplicitSelection: true,
            selectedNodeKey: nodeKey,
        };
    }

    const view = buildTaskDetailView({
        bootstrap: state.bootstrap,
        events: state.events,
    });

    return {
        ...state,
        hasExplicitSelection: true,
        selectedEventId: getDefaultEventId(view, nodeKey),
        selectedNodeKey: nodeKey,
    };
}

function applyEventSelection(state: TaskDetailState, eventId: string): TaskDetailState {
    const selectedEvent = state.events.find((event) => event.event_id === eventId);

    return {
        ...state,
        hasExplicitSelection: true,
        selectedEventId: eventId,
        selectedNodeKey: selectedEvent?.node_key ?? state.selectedNodeKey,
    };
}

function toErrorView(error: unknown): ConsoleErrorView {
    return mapUnknownApiError(error);
}

function isAbortError(error: unknown): boolean {
    return isApiAbortError(error);
}

function isStaleActionError(code: string): boolean {
    return code.startsWith("stale_") || code === "conflict";
}
