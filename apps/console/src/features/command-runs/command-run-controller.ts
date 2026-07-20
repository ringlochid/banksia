import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getNextCursor, type ConsoleErrorView } from "../../api/client";
import type { components } from "../../api/generated/openapi";
import { mapCommandRunRow, type CommandRunRow } from "../../api/view-models";
import {
    cancelCommandRun,
    isAbortError,
    readCommandRunDetail,
    readCommandRunLog,
    readCommandRunPage,
    readCommandRunsPageData,
    streamCommandRunEvents,
    toErrorView,
    type CommandRunListResponse,
} from "./command-run-data";
import {
    mapCommandRunRowView,
    type CommandRunDetailView,
    type CommandRunRowView,
} from "./command-run-model";

const EMPTY_ROWS: readonly CommandRunRowView[] = [];

export interface CommandRunLogState {
    readonly content: string | null;
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
    readonly isVisible: boolean;
    readonly logRef: string | null;
}

export interface CommandRunsController {
    readonly cancelErrorsByRunId: Readonly<Record<string, ConsoleErrorView | undefined>>;
    readonly cancelRun: (runId: string) => void;
    readonly detailErrorsByRunId: Readonly<Record<string, ConsoleErrorView | undefined>>;
    readonly detailViewsByRunId: Readonly<Record<string, CommandRunDetailView | undefined>>;
    readonly error: ConsoleErrorView | null;
    readonly expandedRunId: string | null;
    readonly isCancellingRunId: string | null;
    readonly isDetailLoadingRunId: string | null;
    readonly isLoading: boolean;
    readonly isLoadingMore: boolean;
    readonly isRefreshing: boolean;
    readonly loadMore: () => void;
    readonly logStatesByRunId: Readonly<Record<string, CommandRunLogState | undefined>>;
    readonly nextCursor: string | null;
    readonly refresh: () => void;
    readonly retryDetail: (runId: string) => void;
    readonly rows: readonly CommandRunRowView[];
    readonly statusSummary: string;
    readonly taskId: string | null;
    readonly taskPauseReason: components["schemas"]["RuntimeFlowPauseReason"] | null;
    readonly taskStatus: components["schemas"]["RuntimeLifecycleStatus"] | null;
    readonly taskTitle: string | null;
    readonly taskWaitingCause: components["schemas"]["RuntimeFlowWaitingCause"] | null;
    readonly toggleExpandedRun: (runId: string) => void;
    readonly toggleLogs: (runId: string) => void;
}

interface CommandRunsPageState {
    readonly error: ConsoleErrorView | null;
    readonly hasLoaded: boolean;
    readonly isLoading: boolean;
    readonly isLoadingMore: boolean;
    readonly isRefreshing: boolean;
    readonly listGeneration: number;
    readonly nextCursor: string | null;
    readonly rows: readonly CommandRunRowView[];
    readonly settledTaskId: string | null;
    readonly task: components["schemas"]["RuntimeFlowRead"] | null;
}

const initialPageState: CommandRunsPageState = {
    error: null,
    hasLoaded: false,
    isLoading: true,
    isLoadingMore: false,
    isRefreshing: false,
    listGeneration: 0,
    nextCursor: null,
    rows: EMPTY_ROWS,
    settledTaskId: null,
    task: null,
};

const missingTaskIdError: ConsoleErrorView = {
    code: "missing_task_id",
    fieldErrors: [],
    isRetryable: false,
    source: "http",
    status: null,
    suggestedNextStep: "Open Command Runs from a selected task.",
    summary: "The route did not include a task id.",
    title: "Missing Task Id",
};

const commandLogMismatchError: ConsoleErrorView = {
    code: "stale_command_log_read",
    fieldErrors: [],
    isRetryable: true,
    source: "unknown",
    status: null,
    suggestedNextStep: "Retry the log read from the current command-run detail.",
    summary: "The command log changed while it was loading.",
    title: "Command Log Changed",
};

export function useCommandRunsController(taskId: string | null): CommandRunsController {
    const [pageState, setPageState] = useState<CommandRunsPageState>(initialPageState);
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const [detailViewsByRunId, setDetailViewsByRunId] = useState<
        Readonly<Record<string, CommandRunDetailView | undefined>>
    >({});
    const [detailErrorsByRunId, setDetailErrorsByRunId] = useState<
        Readonly<Record<string, ConsoleErrorView | undefined>>
    >({});
    const [isDetailLoadingRunId, setIsDetailLoadingRunId] = useState<string | null>(null);
    const [logStatesByRunId, setLogStatesByRunId] = useState<
        Readonly<Record<string, CommandRunLogState | undefined>>
    >({});
    const [cancelErrorsByRunId, setCancelErrorsByRunId] = useState<
        Readonly<Record<string, ConsoleErrorView | undefined>>
    >({});
    const [isCancellingRunId, setIsCancellingRunId] = useState<string | null>(null);
    const [refreshToken, setRefreshToken] = useState(0);
    const listGenerationRef = useRef(0);
    const expandedRunIdRef = useRef<string | null>(null);
    const detailRequestGenerationsRef = useRef(new Map<string, number>());
    const logRequestGenerationsRef = useRef(new Map<string, number>());
    expandedRunIdRef.current = expandedRunId;

    const commitDetailView = useCallback(
        (runId: string, requestGeneration: number, detail: CommandRunDetailView) => {
            if (detailRequestGenerationsRef.current.get(runId) !== requestGeneration) {
                return;
            }

            setDetailViewsByRunId((currentDetails) => ({
                ...currentDetails,
                [runId]: detail,
            }));
            setDetailErrorsByRunId((currentErrors) => ({
                ...currentErrors,
                [runId]: undefined,
            }));
            setIsDetailLoadingRunId((currentRunId) =>
                currentRunId === runId ? null : currentRunId,
            );
            setLogStatesByRunId((currentStates) => {
                const currentLogState = currentStates[runId];
                if (
                    currentLogState === undefined ||
                    currentLogState.logRef === detail.preferredLogRef
                ) {
                    return currentStates;
                }

                nextRequestGeneration(logRequestGenerationsRef.current, runId);
                return { ...currentStates, [runId]: undefined };
            });
        },
        [],
    );

    useEffect(() => {
        if (taskId === null) {
            return;
        }

        const abortController = new AbortController();
        let sourceRefreshTimer: ReturnType<typeof setTimeout> | null = null;
        const listGeneration = listGenerationRef.current + 1;
        listGenerationRef.current = listGeneration;
        beginCommandRunListRead(setPageState, taskId, listGeneration);

        const applyPageData = ({
            commandRunList,
            task,
        }: Awaited<ReturnType<typeof readCommandRunsPageData>>) => {
            applyCommandRunListPage({
                listGeneration,
                page: commandRunList,
                setPageState,
                task,
                taskId,
            });
        };

        const refreshExpandedDetail = async () => {
            const runId = expandedRunIdRef.current;
            if (runId === null) {
                return;
            }

            const requestGeneration = nextRequestGeneration(
                detailRequestGenerationsRef.current,
                runId,
            );
            try {
                const detail = await readCommandRunDetail(taskId, runId, abortController.signal);
                if (
                    listGenerationRef.current !== listGeneration ||
                    expandedRunIdRef.current !== runId
                ) {
                    return;
                }
                commitDetailView(runId, requestGeneration, detail);
            } catch (error) {
                if (
                    isAbortError(error) ||
                    listGenerationRef.current !== listGeneration ||
                    detailRequestGenerationsRef.current.get(runId) !== requestGeneration
                ) {
                    return;
                }
                setDetailErrorsByRunId((currentErrors) => ({
                    ...currentErrors,
                    [runId]: toErrorView(error),
                }));
            }
        };

        const refreshCommittedSource = async () => {
            try {
                const response = await readCommandRunsPageData(taskId, abortController.signal);
                applyPageData(response);
                await refreshExpandedDetail();
                return response;
            } catch (error) {
                applyCommandRunListError({ error, listGeneration, setPageState, taskId });
                return null;
            }
        };

        const scheduleCommittedSourceRefresh = () => {
            if (sourceRefreshTimer !== null) {
                clearTimeout(sourceRefreshTimer);
            }
            sourceRefreshTimer = setTimeout(() => {
                sourceRefreshTimer = null;
                void refreshCommittedSource();
            }, 25);
        };

        void readCommandRunsPageData(taskId, abortController.signal)
            .then((response) => {
                applyPageData(response);
                void streamCommandRunEvents({
                    cursor: response.streamHeadEventId,
                    onSourceEvent: scheduleCommittedSourceRefresh,
                    resetAfterCursorReset: async () => {
                        const refreshedResponse = await refreshCommittedSource();
                        return refreshedResponse?.streamHeadEventId ?? null;
                    },
                    signal: abortController.signal,
                    taskId,
                }).catch(() => {
                    // The stream is only a refresh hint. Preserve committed REST truth.
                });
            })
            .catch((error: unknown) => {
                applyCommandRunListError({ error, listGeneration, setPageState, taskId });
            });

        return () => {
            if (sourceRefreshTimer !== null) {
                clearTimeout(sourceRefreshTimer);
            }
            abortController.abort();
        };
    }, [commitDetailView, refreshToken, taskId]);

    const visibleRows =
        taskId !== null && pageState.settledTaskId === taskId ? pageState.rows : EMPTY_ROWS;
    const effectiveError =
        taskId === null
            ? missingTaskIdError
            : pageState.settledTaskId === taskId
              ? pageState.error
              : null;
    const effectiveIsLoading =
        taskId !== null && pageState.settledTaskId !== taskId
            ? true
            : taskId === null
              ? false
              : pageState.isLoading;

    const refresh = useCallback(() => {
        setCancelErrorsByRunId({});
        setDetailErrorsByRunId({});
        setLogStatesByRunId({});
        setRefreshToken((value) => value + 1);
    }, []);

    const fetchDetail = useCallback(
        (runId: string) => {
            if (taskId === null) {
                return;
            }

            const requestGeneration = nextRequestGeneration(
                detailRequestGenerationsRef.current,
                runId,
            );
            setIsDetailLoadingRunId(runId);
            setDetailErrorsByRunId((currentErrors) => ({ ...currentErrors, [runId]: undefined }));
            void readCommandRunDetail(taskId, runId)
                .then((detail) => {
                    commitDetailView(runId, requestGeneration, detail);
                })
                .catch((error: unknown) => {
                    if (
                        isAbortError(error) ||
                        detailRequestGenerationsRef.current.get(runId) !== requestGeneration
                    ) {
                        return;
                    }
                    setDetailErrorsByRunId((currentErrors) => ({
                        ...currentErrors,
                        [runId]: toErrorView(error),
                    }));
                })
                .finally(() => {
                    if (detailRequestGenerationsRef.current.get(runId) !== requestGeneration) {
                        return;
                    }
                    setIsDetailLoadingRunId((currentRunId) =>
                        currentRunId === runId ? null : currentRunId,
                    );
                });
        },
        [commitDetailView, taskId],
    );

    const toggleExpandedRun = useCallback(
        (runId: string) => {
            setExpandedRunId((currentRunId) => (currentRunId === runId ? null : runId));
            if (detailViewsByRunId[runId] === undefined) {
                fetchDetail(runId);
            }
        },
        [detailViewsByRunId, fetchDetail],
    );

    const toggleLogs = useCallback(
        (runId: string) => {
            const detail = detailViewsByRunId[runId];
            const logRef = detail?.preferredLogRef ?? null;
            if (taskId === null || logRef === null) {
                return;
            }

            const currentLogState = logStatesByRunId[runId];
            if (currentLogState?.isVisible === true) {
                setLogStatesByRunId((currentStates) => ({
                    ...currentStates,
                    [runId]:
                        currentStates[runId] === undefined
                            ? undefined
                            : { ...currentStates[runId], isVisible: false },
                }));
                return;
            }

            if (currentLogState?.logRef === logRef && currentLogState.content !== null) {
                setLogStatesByRunId((currentStates) => {
                    const latestLogState = currentStates[runId];
                    if (latestLogState?.logRef !== logRef || latestLogState.content === null) {
                        return currentStates;
                    }
                    return {
                        ...currentStates,
                        [runId]: { ...latestLogState, error: null, isVisible: true },
                    };
                });
                return;
            }

            const requestGeneration = nextRequestGeneration(
                logRequestGenerationsRef.current,
                runId,
            );
            setLogStatesByRunId((currentStates) => ({
                ...currentStates,
                [runId]: {
                    content: null,
                    error: null,
                    isLoading: true,
                    isVisible: true,
                    logRef,
                },
            }));
            void readCommandRunLog(taskId, runId)
                .then((logRead) => {
                    setLogStatesByRunId((currentStates) => {
                        const latestLogState = currentStates[runId];
                        if (
                            logRequestGenerationsRef.current.get(runId) !== requestGeneration ||
                            latestLogState?.logRef !== logRef
                        ) {
                            return currentStates;
                        }
                        if (logRead.run_id !== runId || logRead.log_ref !== logRef) {
                            return {
                                ...currentStates,
                                [runId]: {
                                    ...latestLogState,
                                    content: null,
                                    error: commandLogMismatchError,
                                    isLoading: false,
                                },
                            };
                        }
                        return {
                            ...currentStates,
                            [runId]: {
                                ...latestLogState,
                                content: logRead.content,
                                error: null,
                                isLoading: false,
                            },
                        };
                    });
                })
                .catch((error: unknown) => {
                    if (isAbortError(error)) {
                        return;
                    }
                    setLogStatesByRunId((currentStates) => {
                        const latestLogState = currentStates[runId];
                        if (
                            logRequestGenerationsRef.current.get(runId) !== requestGeneration ||
                            latestLogState?.logRef !== logRef
                        ) {
                            return currentStates;
                        }
                        return {
                            ...currentStates,
                            [runId]: {
                                ...latestLogState,
                                content: null,
                                error: toErrorView(error),
                                isLoading: false,
                            },
                        };
                    });
                });
        },
        [detailViewsByRunId, logStatesByRunId, taskId],
    );

    const cancelRun = useCallback(
        (runId: string) => {
            if (taskId === null || isCancellingRunId !== null) {
                return;
            }

            setIsCancellingRunId(runId);
            setCancelErrorsByRunId((currentErrors) => ({ ...currentErrors, [runId]: undefined }));
            void cancelCommandRun(taskId, runId)
                .then((response) => {
                    const nextRow = mapCommandRunRowView(mapCommandRunRow(response.run));
                    setPageState((currentState) => ({
                        ...currentState,
                        rows: currentState.rows.map((row) => (row.runId === runId ? nextRow : row)),
                    }));
                    setDetailViewsByRunId((currentDetails) => ({
                        ...currentDetails,
                        [runId]: undefined,
                    }));
                    setCancelErrorsByRunId((currentErrors) => ({
                        ...currentErrors,
                        [runId]: undefined,
                    }));
                    if (expandedRunId === runId) {
                        fetchDetail(runId);
                    }
                })
                .catch((error: unknown) => {
                    if (isAbortError(error)) {
                        return;
                    }
                    setCancelErrorsByRunId((currentErrors) => ({
                        ...currentErrors,
                        [runId]: toErrorView(error),
                    }));
                    if (isStaleActionError(toErrorView(error).code)) {
                        setRefreshToken((value) => value + 1);
                    }
                })
                .finally(() => {
                    setIsCancellingRunId((currentRunId) =>
                        currentRunId === runId ? null : currentRunId,
                    );
                });
        },
        [expandedRunId, fetchDetail, isCancellingRunId, taskId],
    );

    const loadMore = useCallback(() => {
        if (
            taskId === null ||
            pageState.nextCursor === null ||
            pageState.isLoading ||
            pageState.isLoadingMore ||
            pageState.isRefreshing
        ) {
            return;
        }

        const cursor = pageState.nextCursor;
        const listGeneration = pageState.listGeneration;
        setPageState((currentState) => ({
            ...currentState,
            isLoadingMore: true,
        }));
        void readCommandRunPage({ cursor, signal: undefined, taskId })
            .then((page) => {
                setPageState((currentState) => {
                    if (
                        currentState.listGeneration !== listGeneration ||
                        currentState.settledTaskId !== taskId
                    ) {
                        return currentState;
                    }

                    const loadedRunIds = new Set(currentState.rows.map((row) => row.runId));
                    const nextRows = page.items
                        .map(mapCommandRunRow)
                        .map(mapCommandRunRowView)
                        .filter((row) => !loadedRunIds.has(row.runId));

                    return {
                        ...currentState,
                        error: null,
                        isLoadingMore: false,
                        nextCursor: getNextCursor(page),
                        rows: [...currentState.rows, ...nextRows],
                    };
                });
            })
            .catch((error: unknown) => {
                if (isAbortError(error)) {
                    return;
                }
                setPageState((currentState) => ({
                    ...currentState,
                    error: toErrorView(error),
                    isLoadingMore: false,
                }));
            });
    }, [pageState, taskId]);

    const statusSummary = useMemo(
        () =>
            getStatusSummary({
                error: effectiveError,
                isCancellingRunId,
                isLoading: effectiveIsLoading,
                isLoadingMore: pageState.isLoadingMore,
                isRefreshing: pageState.isRefreshing,
                rows: visibleRows,
            }),
        [
            effectiveError,
            effectiveIsLoading,
            isCancellingRunId,
            pageState.isLoadingMore,
            pageState.isRefreshing,
            visibleRows,
        ],
    );

    return {
        cancelErrorsByRunId,
        cancelRun,
        detailErrorsByRunId,
        detailViewsByRunId,
        error: effectiveError,
        expandedRunId,
        isCancellingRunId,
        isDetailLoadingRunId,
        isLoading: effectiveIsLoading,
        isLoadingMore: pageState.isLoadingMore,
        isRefreshing: pageState.isRefreshing,
        loadMore,
        logStatesByRunId,
        nextCursor: pageState.nextCursor,
        refresh,
        retryDetail: fetchDetail,
        rows: visibleRows,
        statusSummary,
        taskId,
        taskPauseReason:
            pageState.settledTaskId === taskId ? (pageState.task?.pause_reason ?? null) : null,
        taskStatus: pageState.settledTaskId === taskId ? (pageState.task?.status ?? null) : null,
        taskTitle: pageState.settledTaskId === taskId ? (pageState.task?.task_title ?? null) : null,
        taskWaitingCause:
            pageState.settledTaskId === taskId ? (pageState.task?.waiting_cause ?? null) : null,
        toggleExpandedRun,
        toggleLogs,
    };
}

function beginCommandRunListRead(
    setPageState: React.Dispatch<React.SetStateAction<CommandRunsPageState>>,
    taskId: string,
    listGeneration: number,
): void {
    setPageState((currentState) => ({
        ...currentState,
        error: null,
        isLoading: !currentState.hasLoaded || currentState.settledTaskId !== taskId,
        isLoadingMore: false,
        isRefreshing: currentState.hasLoaded && currentState.settledTaskId === taskId,
        listGeneration,
        nextCursor: null,
    }));
}

function applyCommandRunListPage({
    listGeneration,
    page,
    setPageState,
    task,
    taskId,
}: {
    readonly listGeneration: number;
    readonly page: CommandRunListResponse;
    readonly setPageState: React.Dispatch<React.SetStateAction<CommandRunsPageState>>;
    readonly task: components["schemas"]["RuntimeFlowRead"];
    readonly taskId: string;
}): void {
    setPageState((currentState) => {
        if (currentState.listGeneration !== listGeneration) {
            return currentState;
        }

        return {
            ...currentState,
            error: null,
            hasLoaded: true,
            isLoading: false,
            isLoadingMore: false,
            isRefreshing: false,
            nextCursor: getNextCursor(page),
            rows: page.items.map(mapCommandRunRow).map(mapCommandRunRowView),
            settledTaskId: taskId,
            task,
        };
    });
}

function applyCommandRunListError({
    error,
    listGeneration,
    setPageState,
    taskId,
}: {
    readonly error: unknown;
    readonly listGeneration: number;
    readonly setPageState: React.Dispatch<React.SetStateAction<CommandRunsPageState>>;
    readonly taskId: string;
}): void {
    if (isAbortError(error)) {
        return;
    }

    setPageState((currentState) => {
        if (currentState.listGeneration !== listGeneration) {
            return currentState;
        }

        return {
            ...currentState,
            error: toErrorView(error),
            hasLoaded: true,
            isLoading: false,
            isLoadingMore: false,
            isRefreshing: false,
            rows: currentState.hasLoaded ? currentState.rows : EMPTY_ROWS,
            settledTaskId: taskId,
            task: null,
        };
    });
}

function getStatusSummary({
    error,
    isCancellingRunId,
    isLoading,
    isLoadingMore,
    isRefreshing,
    rows,
}: {
    readonly error: ConsoleErrorView | null;
    readonly isCancellingRunId: string | null;
    readonly isLoading: boolean;
    readonly isLoadingMore: boolean;
    readonly isRefreshing: boolean;
    readonly rows: readonly CommandRunRow[];
}): string {
    if (isLoading) {
        return "Loading";
    }
    if (isRefreshing) {
        return "Refreshing";
    }
    if (isLoadingMore) {
        return "Loading more";
    }
    if (isCancellingRunId !== null) {
        return "Cancelling";
    }
    if (error !== null) {
        return isAuthError(error) ? "Access problem" : "Read error";
    }
    if (rows.length === 0) {
        return "Empty";
    }
    return "Ready";
}

export function isAuthError(error: ConsoleErrorView | null): boolean {
    return (
        error?.status === 401 ||
        error?.status === 403 ||
        error?.code === "illegal_caller" ||
        error?.code === "capability_rejected" ||
        error?.code === "auth_required" ||
        error?.code === "permission_denied"
    );
}

export function isStaleActionError(code: string): boolean {
    return (
        code.startsWith("stale_") ||
        code === "illegal_state" ||
        code === "conflict" ||
        code === "conflicting_continuation"
    );
}

function nextRequestGeneration(generations: Map<string, number>, key: string): number {
    const generation = (generations.get(key) ?? 0) + 1;
    generations.set(key, generation);
    return generation;
}
