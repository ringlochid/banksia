import {
    useCallback,
    useEffect,
    useRef,
    useState,
    type Dispatch,
    type SetStateAction,
} from "react";

import { getNextCursor, type ConsoleErrorView } from "../../api/client";
import {
    isAbortError,
    isAuthError,
    previewTaskStart,
    readWorkflowChoices,
    readWorkflowDetail,
    startTask,
    toErrorView,
    type DefinitionListSort,
} from "./task-start-data";
import {
    TASK_START_INITIAL_FORM,
    buildTaskStartPreview,
    buildTaskStartRequest,
    hasTaskStartFormErrors,
    mapTaskStartResult,
    mapTaskStartWorkflowChoice,
    mapTaskStartWorkflowDetail,
    shouldShowHostPath,
    validateTaskStartForm,
    type TaskRootMode,
    type TaskStartFormErrors,
    type TaskStartFormState,
    type TaskStartPreview,
    type TaskStartResultView,
    type TaskStartWorkflowChoice,
    type TaskStartWorkflowDetail,
} from "./task-start-model";

interface WorkflowListState {
    readonly criteriaKey: string;
    readonly error: ConsoleErrorView | null;
    readonly hasLoaded: boolean;
    readonly isLoading: boolean;
    readonly isLoadingMore: boolean;
    readonly isRefreshing: boolean;
    readonly listGeneration: number;
    readonly nextCursor: string | null;
    readonly rows: readonly TaskStartWorkflowChoice[];
}

interface WorkflowDetailState {
    readonly detail: TaskStartWorkflowDetail | null;
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
    readonly selectedKey: string | null;
}

interface TaskStartSubmitState {
    readonly error: ConsoleErrorView | null;
    readonly isSubmitting: boolean;
    readonly result: TaskStartResultView | null;
}

interface TaskStartPreviewState {
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
    readonly preview: TaskStartPreview | null;
}

export interface TaskStartController {
    readonly clearWorkflow: () => void;
    readonly detailState: WorkflowDetailState;
    readonly form: TaskStartFormState;
    readonly formErrors: TaskStartFormErrors;
    readonly isSelectedWorkflowInRows: boolean;
    readonly listState: WorkflowListState;
    readonly loadMoreWorkflows: () => void;
    readonly previewOpen: boolean;
    readonly previewState: TaskStartPreviewState;
    readonly resultOpen: boolean;
    readonly refresh: () => void;
    readonly selectWorkflow: (key: string) => void;
    readonly selectedWorkflow: TaskStartWorkflowChoice | null;
    readonly selectedWorkflowKey: string | null;
    readonly setField: (field: keyof TaskStartFormState, value: string) => void;
    readonly setPreviewOpen: (value: boolean) => void;
    readonly setResultOpen: (value: boolean) => void;
    readonly setWorkspaceMode: (mode: TaskRootMode) => void;
    readonly showPreview: () => void;
    readonly sort: DefinitionListSort;
    readonly start: () => void;
    readonly statusSummary: string;
    readonly submitState: TaskStartSubmitState;
    readonly updateWorkflowQuery: (value: string) => void;
    readonly workflowQuery: string;
}

const initialSort: DefinitionListSort = "updated_at_desc";
const initialCriteriaKey = buildWorkflowCriteriaKey("", initialSort);

const initialListState: WorkflowListState = {
    criteriaKey: initialCriteriaKey,
    error: null,
    hasLoaded: false,
    isLoading: true,
    isLoadingMore: false,
    isRefreshing: false,
    listGeneration: 0,
    nextCursor: null,
    rows: [],
};

const initialDetailState: WorkflowDetailState = {
    detail: null,
    error: null,
    isLoading: false,
    selectedKey: null,
};

const initialSubmitState: TaskStartSubmitState = {
    error: null,
    isSubmitting: false,
    result: null,
};

const initialPreviewState: TaskStartPreviewState = {
    error: null,
    isLoading: false,
    preview: null,
};

export function useTaskStartController(): TaskStartController {
    const [workflowQuery, setWorkflowQuery] = useState("");
    const [sort] = useState<DefinitionListSort>(initialSort);
    const [selectedWorkflowKey, setSelectedWorkflowKey] = useState<string | null>(null);
    const [form, setForm] = useState<TaskStartFormState>(TASK_START_INITIAL_FORM);
    const [formErrors, setFormErrors] = useState<TaskStartFormErrors>({});
    const [refreshToken, setRefreshToken] = useState(0);
    const [listState, setListState] = useState<WorkflowListState>(initialListState);
    const [detailState, setDetailState] = useState<WorkflowDetailState>(initialDetailState);
    const [submitState, setSubmitState] = useState<TaskStartSubmitState>(initialSubmitState);
    const [previewState, setPreviewState] = useState<TaskStartPreviewState>(initialPreviewState);
    const [previewOpen, setPreviewOpen] = useState(false);
    const [resultOpen, setResultOpen] = useState(false);
    const hasPrimedWorkflowQueryRef = useRef(false);
    const listGenerationRef = useRef(0);
    const previewGenerationRef = useRef(0);
    const trimmedWorkflowQuery = workflowQuery.trim();
    const criteriaKey = buildWorkflowCriteriaKey(trimmedWorkflowQuery, sort);
    const selectedWorkflow =
        selectedWorkflowKey === null
            ? null
            : (listState.rows.find((row) => row.key === selectedWorkflowKey) ?? null);
    const isSelectedWorkflowInRows =
        selectedWorkflowKey !== null &&
        listState.rows.some((row) => row.key === selectedWorkflowKey);

    const invalidatePreview = useCallback(() => {
        previewGenerationRef.current += 1;
        setPreviewOpen(false);
        setPreviewState(initialPreviewState);
    }, []);

    useEffect(() => {
        const abortController = new AbortController();
        const listGeneration = listGenerationRef.current + 1;
        listGenerationRef.current = listGeneration;
        beginWorkflowListRead(setListState, criteriaKey, listGeneration);
        void readWorkflowChoices({
            cursor: null,
            signal: abortController.signal,
            sort,
            trimmedQuery: trimmedWorkflowQuery,
        })
            .then((page) => {
                const rows = page.items.map(mapTaskStartWorkflowChoice);
                applyWorkflowListPage({
                    criteriaKey,
                    listGeneration,
                    nextCursor: getNextCursor(page),
                    rows,
                    setListState,
                });
                const firstWorkflowKey = rows.length > 0 ? rows[0].key : null;
                setSelectedWorkflowKey((currentKey) => currentKey ?? firstWorkflowKey);
                if (
                    firstWorkflowKey !== null &&
                    trimmedWorkflowQuery.length === 0 &&
                    !hasPrimedWorkflowQueryRef.current
                ) {
                    hasPrimedWorkflowQueryRef.current = true;
                    setWorkflowQuery(firstWorkflowKey);
                }
            })
            .catch((error: unknown) => {
                applyWorkflowListError({ criteriaKey, error, listGeneration, setListState });
            });

        return () => {
            abortController.abort();
        };
    }, [criteriaKey, refreshToken, sort, trimmedWorkflowQuery]);

    useEffect(() => {
        if (selectedWorkflowKey === null) {
            return;
        }

        const abortController = new AbortController();
        beginWorkflowDetailRead(setDetailState, selectedWorkflowKey);
        void readWorkflowDetail({ key: selectedWorkflowKey, signal: abortController.signal })
            .then((detail) => {
                setDetailState((currentState) => {
                    if (currentState.selectedKey !== selectedWorkflowKey) {
                        return currentState;
                    }
                    return {
                        detail: mapTaskStartWorkflowDetail(detail),
                        error: null,
                        isLoading: false,
                        selectedKey: selectedWorkflowKey,
                    };
                });
            })
            .catch((error: unknown) => {
                if (isAbortError(error)) {
                    return;
                }
                setDetailState((currentState) => {
                    if (currentState.selectedKey !== selectedWorkflowKey) {
                        return currentState;
                    }
                    return {
                        detail: null,
                        error: toErrorView(error),
                        isLoading: false,
                        selectedKey: selectedWorkflowKey,
                    };
                });
            });

        return () => {
            abortController.abort();
        };
    }, [selectedWorkflowKey]);

    const setField = useCallback(
        (field: keyof TaskStartFormState, value: string) => {
            setForm((currentForm) => ({ ...currentForm, [field]: value }));
            setFormErrors((currentErrors) => ({ ...currentErrors, [field]: undefined }));
            invalidatePreview();
        },
        [invalidatePreview],
    );

    const setWorkspaceMode = useCallback(
        (mode: TaskRootMode) => {
            setForm((currentForm) => {
                return {
                    ...currentForm,
                    workspaceHostPath: shouldShowHostPath(mode)
                        ? currentForm.workspaceHostPath
                        : "",
                    workspaceMode: mode,
                };
            });
            setFormErrors((currentErrors) => ({
                ...currentErrors,
                workspaceHostPath: undefined,
            }));
            invalidatePreview();
        },
        [invalidatePreview],
    );

    const validateCurrentForm = useCallback((): TaskStartFormErrors => {
        const errors = validateTaskStartForm(form, selectedWorkflowKey);
        const workflowError =
            errors.workflow ??
            (detailState.error === null
                ? undefined
                : "Selected workflow could not be confirmed from stored registry truth.");
        const nextErrors = { ...errors, workflow: workflowError };
        setFormErrors(nextErrors);
        return nextErrors;
    }, [detailState.error, form, selectedWorkflowKey]);

    const showPreview = useCallback(() => {
        const errors = validateCurrentForm();
        if (
            hasTaskStartFormErrors(errors) ||
            selectedWorkflowKey === null ||
            selectedWorkflow === null
        ) {
            setPreviewOpen(false);
            return;
        }

        const generation = previewGenerationRef.current + 1;
        previewGenerationRef.current = generation;
        const request = buildTaskStartRequest(form, selectedWorkflowKey);
        setPreviewState({ error: null, isLoading: true, preview: null });
        setPreviewOpen(true);
        void previewTaskStart(request)
            .then((response) => {
                if (previewGenerationRef.current !== generation) {
                    return;
                }
                setPreviewState({
                    error: null,
                    isLoading: false,
                    preview: buildTaskStartPreview({
                        detail: detailState.detail,
                        form,
                        response,
                        workflow: selectedWorkflow,
                    }),
                });
            })
            .catch((error: unknown) => {
                if (isAbortError(error) || previewGenerationRef.current !== generation) {
                    return;
                }
                setPreviewState({
                    error: toErrorView(error),
                    isLoading: false,
                    preview: null,
                });
            });
    }, [detailState.detail, form, selectedWorkflow, selectedWorkflowKey, validateCurrentForm]);

    const start = useCallback(() => {
        const errors = validateCurrentForm();
        if (hasTaskStartFormErrors(errors) || selectedWorkflowKey === null) {
            return;
        }

        setSubmitState({ error: null, isSubmitting: true, result: submitState.result });
        setPreviewOpen(false);
        void startTask(buildTaskStartRequest(form, selectedWorkflowKey))
            .then((response) => {
                setSubmitState({
                    error: null,
                    isSubmitting: false,
                    result: mapTaskStartResult(response),
                });
                setResultOpen(true);
            })
            .catch((error: unknown) => {
                if (isAbortError(error)) {
                    return;
                }
                setSubmitState({
                    error: toErrorView(error),
                    isSubmitting: false,
                    result: null,
                });
                setResultOpen(true);
            });
    }, [form, selectedWorkflowKey, submitState.result, validateCurrentForm]);

    return {
        clearWorkflow: () => {
            setSelectedWorkflowKey(null);
            setWorkflowQuery("");
            hasPrimedWorkflowQueryRef.current = false;
            setDetailState(initialDetailState);
            setFormErrors((currentErrors) => ({
                ...currentErrors,
                workflow: "Workflow selection is required.",
            }));
            invalidatePreview();
        },
        detailState,
        form,
        formErrors,
        isSelectedWorkflowInRows,
        listState,
        loadMoreWorkflows: () => {
            void loadMoreWorkflows({
                criteriaKey,
                listState,
                setListState,
                sort,
                trimmedWorkflowQuery,
            });
        },
        previewOpen,
        previewState,
        resultOpen,
        refresh: () => {
            setSubmitState(initialSubmitState);
            invalidatePreview();
            setResultOpen(false);
            setRefreshToken((value) => value + 1);
        },
        selectWorkflow: (key: string) => {
            setSelectedWorkflowKey(key);
            hasPrimedWorkflowQueryRef.current = true;
            setWorkflowQuery(key);
            setFormErrors((currentErrors) => ({ ...currentErrors, workflow: undefined }));
            invalidatePreview();
        },
        selectedWorkflow,
        selectedWorkflowKey,
        setField,
        setPreviewOpen,
        setResultOpen,
        setWorkspaceMode,
        showPreview,
        sort,
        start,
        statusSummary: getStatusSummary(listState),
        submitState,
        updateWorkflowQuery: setWorkflowQuery,
        workflowQuery,
    };
}

function loadMoreWorkflows({
    criteriaKey,
    listState,
    setListState,
    sort,
    trimmedWorkflowQuery,
}: {
    readonly criteriaKey: string;
    readonly listState: WorkflowListState;
    readonly setListState: Dispatch<SetStateAction<WorkflowListState>>;
    readonly sort: DefinitionListSort;
    readonly trimmedWorkflowQuery: string;
}): Promise<void> | void {
    if (
        listState.nextCursor === null ||
        listState.isLoading ||
        listState.isLoadingMore ||
        listState.isRefreshing ||
        listState.criteriaKey !== criteriaKey
    ) {
        return;
    }

    const cursor = listState.nextCursor;
    const listGeneration = listState.listGeneration;
    setListState((currentState) => ({ ...currentState, isLoadingMore: true }));
    return readWorkflowChoices({
        cursor,
        signal: undefined,
        sort,
        trimmedQuery: trimmedWorkflowQuery,
    })
        .then((page) => {
            const rows = page.items.map(mapTaskStartWorkflowChoice);
            setListState((currentState) => {
                if (
                    currentState.criteriaKey !== criteriaKey ||
                    currentState.listGeneration !== listGeneration
                ) {
                    return currentState;
                }
                return {
                    ...currentState,
                    error: null,
                    isLoadingMore: false,
                    nextCursor: getNextCursor(page),
                    rows: [...currentState.rows, ...rows],
                };
            });
        })
        .catch((error: unknown) => {
            if (isAbortError(error)) {
                return;
            }
            setListState((currentState) => {
                if (
                    currentState.criteriaKey !== criteriaKey ||
                    currentState.listGeneration !== listGeneration
                ) {
                    return currentState;
                }
                return {
                    ...currentState,
                    error: toErrorView(error),
                    isLoadingMore: false,
                };
            });
        });
}

function beginWorkflowListRead(
    setListState: Dispatch<SetStateAction<WorkflowListState>>,
    criteriaKey: string,
    listGeneration: number,
): void {
    setListState((currentState) => ({
        ...currentState,
        criteriaKey,
        error: null,
        isLoading: !currentState.hasLoaded,
        isLoadingMore: false,
        isRefreshing: currentState.hasLoaded,
        listGeneration,
        nextCursor: null,
    }));
}

function applyWorkflowListPage({
    criteriaKey,
    listGeneration,
    nextCursor,
    rows,
    setListState,
}: {
    readonly criteriaKey: string;
    readonly listGeneration: number;
    readonly nextCursor: string | null;
    readonly rows: readonly TaskStartWorkflowChoice[];
    readonly setListState: Dispatch<SetStateAction<WorkflowListState>>;
}): void {
    setListState((currentState) => {
        if (!isCurrentWorkflowListRead(currentState, criteriaKey, listGeneration)) {
            return currentState;
        }
        return {
            ...currentState,
            error: null,
            hasLoaded: true,
            isLoading: false,
            isLoadingMore: false,
            isRefreshing: false,
            nextCursor,
            rows,
        };
    });
}

function applyWorkflowListError({
    criteriaKey,
    error,
    listGeneration,
    setListState,
}: {
    readonly criteriaKey: string;
    readonly error: unknown;
    readonly listGeneration: number;
    readonly setListState: Dispatch<SetStateAction<WorkflowListState>>;
}): void {
    if (isAbortError(error)) {
        return;
    }

    setListState((currentState) => {
        if (!isCurrentWorkflowListRead(currentState, criteriaKey, listGeneration)) {
            return currentState;
        }
        return {
            ...currentState,
            error: toErrorView(error),
            hasLoaded: true,
            isLoading: false,
            isLoadingMore: false,
            isRefreshing: false,
            rows: currentState.hasLoaded ? currentState.rows : [],
        };
    });
}

function beginWorkflowDetailRead(
    setDetailState: Dispatch<SetStateAction<WorkflowDetailState>>,
    selectedKey: string,
): void {
    setDetailState({
        detail: null,
        error: null,
        isLoading: true,
        selectedKey,
    });
}

function isCurrentWorkflowListRead(
    state: WorkflowListState,
    criteriaKey: string,
    listGeneration: number,
): boolean {
    return state.criteriaKey === criteriaKey && state.listGeneration === listGeneration;
}

function buildWorkflowCriteriaKey(trimmedQuery: string, sort: DefinitionListSort): string {
    return [trimmedQuery, sort].join("::");
}

function getStatusSummary(listState: WorkflowListState): string {
    if (listState.isLoading) {
        return "Loading";
    }
    if (listState.isRefreshing) {
        return "Refreshing";
    }
    if (listState.error !== null) {
        return isAuthError(listState.error) ? "Access problem" : "Read error";
    }
    if (listState.rows.length === 0) {
        return "No workflows";
    }
    return "Stored workflows";
}
