import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isApiAbortError, mapUnknownApiError, type ConsoleErrorView } from "../../api/client";
import type { components } from "../../api/generated/openapi";
import {
    readHumanRequestsPageData,
    resolveHumanRequest,
    streamHumanRequestEvents,
    type HumanRequestsPageData,
} from "./human-request-data";
import {
    buildResolveRequest,
    createDraftForRequest,
    type HumanRequestDraft,
    type HumanRequestItemDraft,
    type HumanRequestValidationError,
} from "./human-request-model";

type HumanRequestRead = components["schemas"]["HumanRequestRead"];
type HumanRequestResolveResponse = components["schemas"]["HumanRequestResolveResponse"];

const EMPTY_REQUEST_READS: readonly HumanRequestRead[] = [];

export interface HumanRequestsController {
    readonly actionError: ConsoleErrorView | null;
    readonly drafts: Readonly<Partial<Record<string, HumanRequestDraft>>>;
    readonly error: ConsoleErrorView | null;
    readonly itemIndexByRequest: Readonly<Record<string, number>>;
    readonly isLoading: boolean;
    readonly isRefreshing: boolean;
    readonly isResolving: boolean;
    readonly refresh: () => void;
    readonly requestReads: readonly HumanRequestRead[];
    readonly resolveSelectedRequest: () => void;
    readonly selectedItem: components["schemas"]["HumanRequestItem"] | null;
    readonly selectedItemDraft: HumanRequestItemDraft | null;
    readonly selectedItemIndex: number;
    readonly selectedRead: HumanRequestRead | null;
    readonly selectedRequestId: string | null;
    readonly selectItemIndex: (index: number) => void;
    readonly selectRequest: (requestId: string) => void;
    readonly statusSummary: string;
    readonly taskId: string | null;
    readonly taskPauseReason: components["schemas"]["RuntimeFlowPauseReason"] | null;
    readonly taskStatus: components["schemas"]["RuntimeLifecycleStatus"] | null;
    readonly taskTitle: string | null;
    readonly taskWaitingCause: components["schemas"]["RuntimeFlowWaitingCause"] | null;
    readonly updateSelectedItemDraft: (patch: Partial<HumanRequestItemDraft>) => void;
    readonly validationErrors: readonly HumanRequestValidationError[];
}

const missingTaskIdError: ConsoleErrorView = {
    code: "missing_task_id",
    fieldErrors: [],
    isRetryable: false,
    source: "http",
    status: null,
    suggestedNextStep: "Open Human Requests from a selected task.",
    summary: "The route did not include a task id.",
    title: "Missing Task Id",
};

export function useHumanRequestsController(taskId: string | null): HumanRequestsController {
    const [requestReads, setRequestReads] = useState<readonly HumanRequestRead[]>([]);
    const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
    const [itemIndexByRequest, setItemIndexByRequest] = useState<Readonly<Record<string, number>>>(
        {},
    );
    const [drafts, setDrafts] = useState<Readonly<Partial<Record<string, HumanRequestDraft>>>>({});
    const [error, setError] = useState<ConsoleErrorView | null>(null);
    const [actionError, setActionError] = useState<ConsoleErrorView | null>(null);
    const [validationErrors, setValidationErrors] = useState<
        readonly HumanRequestValidationError[]
    >([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [isResolving, setIsResolving] = useState(false);
    const [refreshToken, setRefreshToken] = useState(0);
    const [settledTaskId, setSettledTaskId] = useState<string | null>(null);
    const [taskTitle, setTaskTitle] = useState<string | null>(null);
    const [taskRead, setTaskRead] = useState<components["schemas"]["RuntimeFlowRead"] | null>(null);
    const readGenerationRef = useRef(0);

    useEffect(() => {
        if (taskId === null) {
            return;
        }

        const abortController = new AbortController();
        let sourceRefreshTimer: ReturnType<typeof setTimeout> | null = null;
        const readGeneration = readGenerationRef.current + 1;
        readGenerationRef.current = readGeneration;

        const applyPageData = (response: HumanRequestsPageData) => {
            if (readGenerationRef.current !== readGeneration) {
                return;
            }

            setRequestReads(response.requestList.items);
            setSelectedRequestId((currentRequestId) =>
                selectCurrentRequestId(response.requestList.items, currentRequestId),
            );
            setDrafts((currentDrafts) => ensureDrafts(response.requestList.items, currentDrafts));
            setItemIndexByRequest((currentIndexes) =>
                ensureItemIndexes(response.requestList.items, currentIndexes),
            );
            setSettledTaskId(taskId);
            setTaskRead(response.task);
            setTaskTitle(response.task.task_title);
            setError(null);
            setValidationErrors([]);
            setIsLoading(false);
            setIsRefreshing(false);
        };

        const refreshCommittedSource = async (): Promise<HumanRequestsPageData | null> => {
            try {
                const response = await readHumanRequestsPageData(taskId, abortController.signal);
                applyPageData(response);
                return response;
            } catch (readError) {
                if (!isAbortError(readError) && readGenerationRef.current === readGeneration) {
                    setError(toErrorView(readError));
                    setIsLoading(false);
                    setIsRefreshing(false);
                }
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

        void readHumanRequestsPageData(taskId, abortController.signal)
            .then((response) => {
                applyPageData(response);
                void streamHumanRequestEvents({
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
            .catch((readError: unknown) => {
                if (isAbortError(readError) || readGenerationRef.current !== readGeneration) {
                    return;
                }

                setSettledTaskId(taskId);
                setTaskRead(null);
                setTaskTitle(null);
                setError(toErrorView(readError));
                setIsLoading(false);
                setIsRefreshing(false);
            });

        return () => {
            if (sourceRefreshTimer !== null) {
                clearTimeout(sourceRefreshTimer);
            }
            abortController.abort();
        };
    }, [refreshToken, taskId]);

    const visibleRequestReads =
        taskId !== null && settledTaskId === taskId ? requestReads : EMPTY_REQUEST_READS;

    const selectedRead = useMemo(
        () =>
            visibleRequestReads.find(
                (requestRead) => requestRead.request.request_id === selectedRequestId,
            ) ?? null,
        [selectedRequestId, visibleRequestReads],
    );
    const selectedItemIndex =
        selectedRead === null
            ? 0
            : clampItemIndex(
                  itemIndexByRequest[selectedRead.request.request_id] ?? 0,
                  selectedRead.request.items.length,
              );
    const selectedItem = selectedRead?.request.items[selectedItemIndex] ?? null;
    const selectedItemDraft =
        selectedRead !== null && selectedItem !== null
            ? (drafts[selectedRead.request.request_id]?.items[selectedItem.id] ?? null)
            : null;

    const selectRequest = useCallback((requestId: string) => {
        setSelectedRequestId(requestId);
        setActionError(null);
        setValidationErrors([]);
    }, []);

    const selectItemIndex = useCallback(
        (index: number) => {
            if (selectedRead === null) {
                return;
            }

            setItemIndexByRequest((currentIndexes) => ({
                ...currentIndexes,
                [selectedRead.request.request_id]: clampItemIndex(
                    index,
                    selectedRead.request.items.length,
                ),
            }));
            setValidationErrors([]);
        },
        [selectedRead],
    );

    const updateSelectedItemDraft = useCallback(
        (patch: Partial<HumanRequestItemDraft>) => {
            if (selectedRead === null || selectedItem === null) {
                return;
            }

            setDrafts((currentDrafts) => {
                const requestId = selectedRead.request.request_id;
                const requestDraft =
                    currentDrafts[requestId] ?? createDraftForRequest(selectedRead.request);
                const itemDraft =
                    requestDraft.items[selectedItem.id] ??
                    createDraftForRequest(selectedRead.request).items[selectedItem.id];

                return {
                    ...currentDrafts,
                    [requestId]: {
                        items: {
                            ...requestDraft.items,
                            [selectedItem.id]: {
                                ...itemDraft,
                                ...patch,
                            },
                        },
                    },
                };
            });
            setValidationErrors([]);
            setActionError(null);
        },
        [selectedItem, selectedRead],
    );

    const resolveSelectedRequest = useCallback(() => {
        if (taskId === null || selectedRead === null) {
            return;
        }

        const requestId = selectedRead.request.request_id;
        const buildResult = buildResolveRequest(selectedRead.request, drafts[requestId]);
        if (buildResult.request === null) {
            setValidationErrors(buildResult.errors);
            setActionError(null);
            return;
        }

        setIsResolving(true);
        setActionError(null);
        setValidationErrors([]);
        void resolveHumanRequest(taskId, requestId, buildResult.request)
            .then((response) => {
                setRequestReads((currentReads) =>
                    currentReads.map((requestRead) =>
                        requestRead.request.request_id === requestId
                            ? applyResolutionReadback(requestRead, response)
                            : requestRead,
                    ),
                );
            })
            .catch((resolveError: unknown) => {
                if (isAbortError(resolveError)) {
                    return;
                }

                const errorView = toErrorView(resolveError);
                setActionError(errorView);
                if (isStaleActionError(errorView.code)) {
                    setIsRefreshing(true);
                    setRefreshToken((value) => value + 1);
                }
            })
            .finally(() => {
                setIsResolving(false);
            });
    }, [drafts, selectedRead, taskId]);

    const effectiveError =
        taskId === null ? missingTaskIdError : settledTaskId === taskId ? error : null;
    const effectiveIsLoading =
        taskId !== null && settledTaskId !== taskId ? true : taskId === null ? false : isLoading;
    const effectiveIsRefreshing = taskId === null ? false : isRefreshing;

    return {
        actionError,
        drafts,
        error: effectiveError,
        itemIndexByRequest,
        isLoading: effectiveIsLoading,
        isRefreshing: effectiveIsRefreshing,
        isResolving,
        refresh: () => {
            setError(null);
            setActionError(null);
            setValidationErrors([]);
            if (visibleRequestReads.length === 0) {
                setIsLoading(true);
            } else {
                setIsRefreshing(true);
            }
            setRefreshToken((value) => value + 1);
        },
        requestReads: visibleRequestReads,
        resolveSelectedRequest,
        selectedItem,
        selectedItemDraft,
        selectedItemIndex,
        selectedRead,
        selectedRequestId,
        selectItemIndex,
        selectRequest,
        statusSummary: getStatusSummary({
            actionError,
            error: effectiveError,
            isLoading: effectiveIsLoading,
            isRefreshing: effectiveIsRefreshing,
            isResolving,
            requestReads: visibleRequestReads,
        }),
        taskId,
        taskPauseReason: taskRead?.pause_reason ?? null,
        taskStatus: taskRead?.status ?? null,
        taskTitle,
        taskWaitingCause: taskRead?.waiting_cause ?? null,
        updateSelectedItemDraft,
        validationErrors,
    };
}

function selectCurrentRequestId(
    reads: readonly HumanRequestRead[],
    currentRequestId: string | null,
): string | null {
    if (
        currentRequestId !== null &&
        reads.some((requestRead) => requestRead.request.request_id === currentRequestId)
    ) {
        return currentRequestId;
    }

    const openRead = reads.find((requestRead) => requestRead.request.status === "open");
    if (openRead !== undefined) {
        return openRead.request.request_id;
    }

    if (reads.length === 0) {
        return null;
    }

    return reads[0].request.request_id;
}

function ensureDrafts(
    reads: readonly HumanRequestRead[],
    currentDrafts: Readonly<Partial<Record<string, HumanRequestDraft>>>,
): Readonly<Partial<Record<string, HumanRequestDraft>>> {
    const nextDrafts: Partial<Record<string, HumanRequestDraft>> = { ...currentDrafts };
    for (const read of reads) {
        nextDrafts[read.request.request_id] ??= createDraftForRequest(read.request);
    }
    return nextDrafts;
}

function ensureItemIndexes(
    reads: readonly HumanRequestRead[],
    currentIndexes: Readonly<Record<string, number>>,
): Readonly<Record<string, number>> {
    const nextIndexes: Record<string, number> = {};
    for (const read of reads) {
        nextIndexes[read.request.request_id] = clampItemIndex(
            currentIndexes[read.request.request_id] ?? 0,
            read.request.items.length,
        );
    }
    return nextIndexes;
}

function clampItemIndex(index: number, itemCount: number): number {
    if (itemCount <= 0) {
        return 0;
    }

    return Math.min(Math.max(index, 0), itemCount - 1);
}

function applyResolutionReadback(
    read: HumanRequestRead,
    response: HumanRequestResolveResponse,
): HumanRequestRead {
    return {
        request: {
            ...read.request,
            status:
                response.resolution.resolution_kind === "answered"
                    ? "resolved"
                    : response.resolution.resolution_kind,
        },
        resolution: response.resolution,
    };
}

function getStatusSummary({
    actionError,
    error,
    isLoading,
    isRefreshing,
    isResolving,
    requestReads,
}: {
    readonly actionError: ConsoleErrorView | null;
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
    readonly isRefreshing: boolean;
    readonly isResolving: boolean;
    readonly requestReads: readonly HumanRequestRead[];
}): string {
    if (isLoading) {
        return "Loading";
    }
    if (isRefreshing) {
        return "Refreshing";
    }
    if (isResolving) {
        return "Resolving";
    }
    if (actionError !== null) {
        return isStaleActionError(actionError.code) ? "Stale action" : "Action error";
    }
    if (error !== null) {
        return isAuthError(error) ? "Access problem" : "Read error";
    }
    if (requestReads.length === 0) {
        return "Empty";
    }

    const openCount = requestReads.filter(
        (requestRead) => requestRead.request.status === "open",
    ).length;
    return `${String(openCount)} open`;
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

function toErrorView(error: unknown): ConsoleErrorView {
    return mapUnknownApiError(error);
}

function isAbortError(error: unknown): boolean {
    return isApiAbortError(error);
}
