import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
    type Dispatch,
    type SetStateAction,
} from "react";

import { useSearchParams } from "react-router-dom";

import { getNextCursor, type ConsoleErrorView } from "../../api/client";
import {
    isAbortError,
    readDefinitionDetail,
    readDefinitionPage,
    readDefinitionVersions,
    toErrorView,
} from "./definition-data";
import {
    listLabelForKind,
    mapDefinitionDetail,
    mapDefinitionRow,
    mapDefinitionVersionRow,
    singularKindForListKind,
    type DefinitionDetailView,
    type DefinitionKind,
    type DefinitionListKind,
    type DefinitionListSort,
    type DefinitionRow,
    type DefinitionVersionRow,
    type NodeKind,
} from "./definition-model";

interface DefinitionListState {
    readonly criteriaKey: string;
    readonly error: ConsoleErrorView | null;
    readonly hasLoaded: boolean;
    readonly isLoading: boolean;
    readonly isLoadingMore: boolean;
    readonly isRefreshing: boolean;
    readonly listGeneration: number;
    readonly nextCursor: string | null;
    readonly rows: readonly DefinitionRow[];
    readonly settledKind: DefinitionListKind;
}

interface DefinitionDetailState {
    readonly detail: DefinitionDetailView | null;
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
    readonly selectedKey: string | null;
}

interface DefinitionVersionsState {
    readonly currentRevisionNo: number | null;
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
    readonly isLoadingMore: boolean;
    readonly nextCursor: string | null;
    readonly rows: readonly DefinitionVersionRow[];
    readonly selectedKey: string | null;
}

interface DefinitionRouteSelection {
    readonly kind: DefinitionListKind;
    readonly query: string;
    readonly selectedKey: string | null;
}

export interface DefinitionsController {
    readonly activeFilterSummary: string;
    readonly appliesToFilter: NodeKind | "any";
    readonly clearFilters: () => void;
    readonly detailState: DefinitionDetailState;
    readonly hasActiveNarrowing: boolean;
    readonly isSelectedKeyInRows: boolean;
    readonly kind: DefinitionListKind;
    readonly listState: DefinitionListState;
    readonly loadMore: () => void;
    readonly loadMoreVersions: () => void;
    readonly query: string;
    readonly refresh: () => void;
    readonly roleNodeKindFilter: NodeKind | "any";
    readonly selectedKey: string | null;
    readonly selectDefinition: (key: string) => void;
    readonly setAppliesToFilter: (value: NodeKind | "any") => void;
    readonly setKind: (value: DefinitionListKind) => void;
    readonly setQuery: (value: string) => void;
    readonly setRoleNodeKindFilter: (value: NodeKind | "any") => void;
    readonly setSort: (value: DefinitionListSort) => void;
    readonly singularKind: DefinitionKind;
    readonly sort: DefinitionListSort;
    readonly statusSummary: string;
    readonly versionsState: DefinitionVersionsState;
}

const initialKind: DefinitionListKind = "roles";
const initialSort: DefinitionListSort = "updated_at_desc";
const initialListCriteriaKey = buildDefinitionListCriteriaKey({
    appliesToFilter: "any",
    kind: initialKind,
    roleNodeKindFilter: "any",
    sort: initialSort,
    trimmedQuery: "",
});

const initialListState: DefinitionListState = {
    criteriaKey: initialListCriteriaKey,
    error: null,
    hasLoaded: false,
    isLoading: true,
    isLoadingMore: false,
    isRefreshing: false,
    listGeneration: 0,
    nextCursor: null,
    rows: [],
    settledKind: initialKind,
};

const initialDetailState: DefinitionDetailState = {
    detail: null,
    error: null,
    isLoading: false,
    selectedKey: null,
};

const initialVersionsState: DefinitionVersionsState = {
    currentRevisionNo: null,
    error: null,
    isLoading: false,
    isLoadingMore: false,
    nextCursor: null,
    rows: [],
    selectedKey: null,
};

export function useDefinitionsController(): DefinitionsController {
    const [searchParams] = useSearchParams();
    const routeSelection = useMemo(
        () => readDefinitionRouteSelection(searchParams),
        [searchParams],
    );
    const [kind, setKindState] = useState<DefinitionListKind>(routeSelection.kind);
    const [query, setQuery] = useState(routeSelection.query);
    const [sort, setSort] = useState<DefinitionListSort>(initialSort);
    const [roleNodeKindFilter, setRoleNodeKindFilter] = useState<NodeKind | "any">("any");
    const [appliesToFilter, setAppliesToFilter] = useState<NodeKind | "any">("any");
    const [selectedKey, setSelectedKey] = useState<string | null>(routeSelection.selectedKey);
    const [refreshToken, setRefreshToken] = useState(0);
    const [detailRefreshToken, setDetailRefreshToken] = useState(0);
    const [listState, setListState] = useState<DefinitionListState>(initialListState);
    const [detailState, setDetailState] = useState<DefinitionDetailState>(initialDetailState);
    const [versionsState, setVersionsState] =
        useState<DefinitionVersionsState>(initialVersionsState);
    const listGenerationRef = useRef(0);
    const appliedRouteSelectionKeyRef = useRef(routeSelectionKey(routeSelection));
    const trimmedQuery = query.trim();
    const singularKind = singularKindForListKind(kind);
    const criteriaKey = buildDefinitionListCriteriaKey({
        appliesToFilter,
        kind,
        roleNodeKindFilter,
        sort,
        trimmedQuery,
    });
    const hasActiveNarrowing =
        trimmedQuery.length > 0 ||
        (kind === "roles" && roleNodeKindFilter !== "any") ||
        (kind === "policies" && appliesToFilter !== "any");
    const isSelectedKeyInRows =
        selectedKey !== null && listState.rows.some((row) => row.key === selectedKey);

    useEffect(() => {
        const nextRouteSelectionKey = routeSelectionKey(routeSelection);
        if (appliedRouteSelectionKeyRef.current === nextRouteSelectionKey) {
            return;
        }

        appliedRouteSelectionKeyRef.current = nextRouteSelectionKey;
        setKindState(routeSelection.kind);
        setQuery(routeSelection.query);
        setRoleNodeKindFilter("any");
        setAppliesToFilter("any");
        setSelectedKey(routeSelection.selectedKey);
    }, [routeSelection]);

    useEffect(() => {
        const abortController = new AbortController();
        const listGeneration = listGenerationRef.current + 1;
        listGenerationRef.current = listGeneration;
        beginDefinitionListRead(setListState, criteriaKey, kind, listGeneration);
        void readDefinitionPage({
            allowedNodeKind: kind === "roles" ? filterValue(roleNodeKindFilter) : null,
            appliesTo: kind === "policies" ? filterValue(appliesToFilter) : null,
            cursor: null,
            kind,
            signal: abortController.signal,
            sort,
            trimmedQuery,
        })
            .then((page) => {
                const rows = page.items.map((item) => mapDefinitionRow(item, page.kind));
                applyDefinitionListPage({
                    criteriaKey,
                    kind,
                    listGeneration,
                    nextCursor: getNextCursor(page),
                    rows,
                    setListState,
                });
                setSelectedKey(
                    (currentSelectedKey) =>
                        currentSelectedKey ?? (rows.length > 0 ? rows[0].key : null),
                );
            })
            .catch((error: unknown) => {
                applyDefinitionListError({
                    criteriaKey,
                    error,
                    kind,
                    listGeneration,
                    setListState,
                });
            });

        return () => {
            abortController.abort();
        };
    }, [appliesToFilter, criteriaKey, kind, refreshToken, roleNodeKindFilter, sort, trimmedQuery]);

    useEffect(() => {
        if (selectedKey === null) {
            return;
        }

        const abortController = new AbortController();
        startSelectedDefinitionRead({
            abortController,
            selectedKey,
            setDetailState,
            setVersionsState,
            singularKind,
        });

        return () => {
            abortController.abort();
        };
    }, [detailRefreshToken, selectedKey, singularKind]);

    const setKind = useCallback((nextKind: DefinitionListKind) => {
        setKindState(nextKind);
        setQuery("");
        setRoleNodeKindFilter("any");
        setAppliesToFilter("any");
        setSelectedKey(null);
    }, []);

    const clearFilters = useCallback(() => {
        setQuery("");
        setRoleNodeKindFilter("any");
        setAppliesToFilter("any");
    }, []);

    const refresh = useCallback(() => {
        setRefreshToken((value) => value + 1);
        setDetailRefreshToken((value) => value + 1);
    }, []);

    const loadMore = useCallback(() => {
        if (
            listState.nextCursor === null ||
            listState.isLoading ||
            listState.isLoadingMore ||
            listState.isRefreshing ||
            listState.criteriaKey !== criteriaKey ||
            listState.settledKind !== kind
        ) {
            return;
        }

        const cursor = listState.nextCursor;
        const listGeneration = listState.listGeneration;
        setListState((currentState) => ({ ...currentState, isLoadingMore: true }));
        void readDefinitionPage({
            allowedNodeKind: kind === "roles" ? filterValue(roleNodeKindFilter) : null,
            appliesTo: kind === "policies" ? filterValue(appliesToFilter) : null,
            cursor,
            kind,
            signal: undefined,
            sort,
            trimmedQuery,
        })
            .then((page) => {
                const rows = page.items.map((item) => mapDefinitionRow(item, page.kind));
                setListState((currentState) => {
                    if (
                        currentState.criteriaKey !== criteriaKey ||
                        currentState.listGeneration !== listGeneration ||
                        currentState.settledKind !== kind
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
                        currentState.listGeneration !== listGeneration ||
                        currentState.settledKind !== kind
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
    }, [appliesToFilter, criteriaKey, kind, listState, roleNodeKindFilter, sort, trimmedQuery]);

    const loadMoreVersions = useCallback(() => {
        if (
            selectedKey === null ||
            versionsState.nextCursor === null ||
            versionsState.isLoading ||
            versionsState.isLoadingMore
        ) {
            return;
        }

        const cursor = versionsState.nextCursor;
        const expectedSelectedKey = selectedKey;
        setVersionsState((currentState) => ({ ...currentState, isLoadingMore: true }));
        void readDefinitionVersions({
            cursor,
            key: expectedSelectedKey,
            kind: singularKind,
            signal: undefined,
        })
            .then((history) => {
                setVersionsState((currentState) => {
                    if (currentState.selectedKey !== expectedSelectedKey) {
                        return currentState;
                    }
                    return {
                        ...currentState,
                        currentRevisionNo: history.current_revision_no,
                        error: null,
                        isLoadingMore: false,
                        nextCursor: getNextCursor(history),
                        rows: [...currentState.rows, ...history.items.map(mapDefinitionVersionRow)],
                    };
                });
            })
            .catch((error: unknown) => {
                if (isAbortError(error)) {
                    return;
                }
                setVersionsState((currentState) => {
                    if (currentState.selectedKey !== expectedSelectedKey) {
                        return currentState;
                    }
                    return {
                        ...currentState,
                        error: toErrorView(error),
                        isLoadingMore: false,
                    };
                });
            });
    }, [selectedKey, singularKind, versionsState]);

    return {
        activeFilterSummary: getActiveFilterSummary({ appliesToFilter, kind, roleNodeKindFilter }),
        appliesToFilter,
        clearFilters,
        detailState,
        hasActiveNarrowing,
        isSelectedKeyInRows,
        kind,
        listState,
        loadMore,
        loadMoreVersions,
        query,
        refresh,
        roleNodeKindFilter,
        selectedKey,
        selectDefinition: setSelectedKey,
        setAppliesToFilter,
        setKind,
        setQuery,
        setRoleNodeKindFilter,
        setSort,
        singularKind,
        sort,
        statusSummary: getStatusSummary(listState, hasActiveNarrowing),
        versionsState,
    };
}

function readDefinitionRouteSelection(searchParams: URLSearchParams): DefinitionRouteSelection {
    const selectedKey = trimmedSearchParam(searchParams, "key");
    return {
        kind: definitionListKindFromParam(searchParams.get("kind")) ?? initialKind,
        query: selectedKey ?? "",
        selectedKey,
    };
}

function routeSelectionKey(selection: DefinitionRouteSelection): string {
    return `${selection.kind}:${selection.selectedKey ?? ""}`;
}

function trimmedSearchParam(searchParams: URLSearchParams, name: string): string | null {
    const value = searchParams.get(name)?.trim() ?? "";
    return value.length === 0 ? null : value;
}

function definitionListKindFromParam(value: string | null): DefinitionListKind | null {
    switch (value) {
        case "policy":
        case "policies":
            return "policies";
        case "role":
        case "roles":
            return "roles";
        case "workflow":
        case "workflows":
            return "workflows";
        default:
            return null;
    }
}

interface SelectedDefinitionReadOptions {
    readonly abortController: AbortController;
    readonly selectedKey: string;
    readonly setDetailState: Dispatch<SetStateAction<DefinitionDetailState>>;
    readonly setVersionsState: Dispatch<SetStateAction<DefinitionVersionsState>>;
    readonly singularKind: DefinitionKind;
}

function startSelectedDefinitionRead({
    abortController,
    selectedKey,
    setDetailState,
    setVersionsState,
    singularKind,
}: SelectedDefinitionReadOptions): void {
    setDetailState({
        detail: null,
        error: null,
        isLoading: true,
        selectedKey,
    });
    setVersionsState({
        currentRevisionNo: null,
        error: null,
        isLoading: true,
        isLoadingMore: false,
        nextCursor: null,
        rows: [],
        selectedKey,
    });

    void readDefinitionDetail({
        key: selectedKey,
        kind: singularKind,
        signal: abortController.signal,
    })
        .then((detail) => {
            setDetailState((currentState) => {
                if (currentState.selectedKey !== selectedKey) {
                    return currentState;
                }
                return {
                    detail: mapDefinitionDetail(singularKind, detail),
                    error: null,
                    isLoading: false,
                    selectedKey,
                };
            });
        })
        .catch((error: unknown) => {
            if (isAbortError(error)) {
                return;
            }
            setDetailState((currentState) => {
                if (currentState.selectedKey !== selectedKey) {
                    return currentState;
                }
                return {
                    detail: null,
                    error: toErrorView(error),
                    isLoading: false,
                    selectedKey,
                };
            });
        });

    void readDefinitionVersions({
        cursor: null,
        key: selectedKey,
        kind: singularKind,
        signal: abortController.signal,
    })
        .then((history) => {
            setVersionsState((currentState) => {
                if (currentState.selectedKey !== selectedKey) {
                    return currentState;
                }
                return {
                    currentRevisionNo: history.current_revision_no,
                    error: null,
                    isLoading: false,
                    isLoadingMore: false,
                    nextCursor: getNextCursor(history),
                    rows: history.items.map(mapDefinitionVersionRow),
                    selectedKey,
                };
            });
        })
        .catch((error: unknown) => {
            if (isAbortError(error)) {
                return;
            }
            setVersionsState((currentState) => {
                if (currentState.selectedKey !== selectedKey) {
                    return currentState;
                }
                return {
                    ...currentState,
                    error: toErrorView(error),
                    isLoading: false,
                    isLoadingMore: false,
                };
            });
        });
}

function beginDefinitionListRead(
    setListState: Dispatch<SetStateAction<DefinitionListState>>,
    criteriaKey: string,
    kind: DefinitionListKind,
    listGeneration: number,
): void {
    setListState((currentState) => {
        const isSameKind = currentState.settledKind === kind;
        return {
            ...currentState,
            criteriaKey,
            error: null,
            isLoading: !currentState.hasLoaded || !isSameKind,
            isLoadingMore: false,
            isRefreshing: currentState.hasLoaded && isSameKind,
            listGeneration,
            nextCursor: null,
            rows: isSameKind ? currentState.rows : [],
            settledKind: kind,
        };
    });
}

function applyDefinitionListPage({
    criteriaKey,
    kind,
    listGeneration,
    nextCursor,
    rows,
    setListState,
}: {
    readonly criteriaKey: string;
    readonly kind: DefinitionListKind;
    readonly listGeneration: number;
    readonly nextCursor: string | null;
    readonly rows: readonly DefinitionRow[];
    readonly setListState: Dispatch<SetStateAction<DefinitionListState>>;
}): void {
    setListState((currentState) => {
        if (!isCurrentDefinitionListRead(currentState, criteriaKey, kind, listGeneration)) {
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

function applyDefinitionListError({
    criteriaKey,
    error,
    kind,
    listGeneration,
    setListState,
}: {
    readonly criteriaKey: string;
    readonly error: unknown;
    readonly kind: DefinitionListKind;
    readonly listGeneration: number;
    readonly setListState: Dispatch<SetStateAction<DefinitionListState>>;
}): void {
    if (isAbortError(error)) {
        return;
    }

    setListState((currentState) => {
        if (!isCurrentDefinitionListRead(currentState, criteriaKey, kind, listGeneration)) {
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

function isCurrentDefinitionListRead(
    state: DefinitionListState,
    criteriaKey: string,
    kind: DefinitionListKind,
    listGeneration: number,
): boolean {
    return (
        state.criteriaKey === criteriaKey &&
        state.listGeneration === listGeneration &&
        state.settledKind === kind
    );
}

function buildDefinitionListCriteriaKey({
    appliesToFilter,
    kind,
    roleNodeKindFilter,
    sort,
    trimmedQuery,
}: {
    readonly appliesToFilter: NodeKind | "any";
    readonly kind: DefinitionListKind;
    readonly roleNodeKindFilter: NodeKind | "any";
    readonly sort: DefinitionListSort;
    readonly trimmedQuery: string;
}): string {
    const roleFilter = kind === "roles" ? roleNodeKindFilter : "any";
    const policyFilter = kind === "policies" ? appliesToFilter : "any";
    return [kind, trimmedQuery, sort, roleFilter, policyFilter].join("::");
}

function filterValue(value: NodeKind | "any"): NodeKind | null {
    return value === "any" ? null : value;
}

function getActiveFilterSummary({
    appliesToFilter,
    kind,
    roleNodeKindFilter,
}: {
    readonly appliesToFilter: NodeKind | "any";
    readonly kind: DefinitionListKind;
    readonly roleNodeKindFilter: NodeKind | "any";
}): string {
    if (kind === "roles" && roleNodeKindFilter !== "any") {
        return `Allowed node kind: ${roleNodeKindFilter}`;
    }
    if (kind === "policies" && appliesToFilter !== "any") {
        return `Applies to: ${appliesToFilter}`;
    }
    return "No kind filter";
}

function getStatusSummary(listState: DefinitionListState, hasActiveNarrowing: boolean): string {
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
        return hasActiveNarrowing
            ? "No results"
            : `No stored ${listLabelForKind(listState.settledKind)}`;
    }
    return "Stored registry";
}

export function isAuthError(error: ConsoleErrorView): boolean {
    return error.status === 401 || error.status === 403 || error.code === "illegal_caller";
}
