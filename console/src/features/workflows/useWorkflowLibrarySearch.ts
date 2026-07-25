import { useEffect, useRef, useState } from "react";

import type { WorkflowApi } from "../../api/client";
import type { WorkflowSearchItem } from "../../api/types";
import { useDebouncedValue } from "./useDebouncedValue";

export interface WorkflowLibrarySearch {
    readonly error: string | null;
    readonly isLoading: boolean;
    readonly isLoadingMore: boolean;
    readonly items: readonly WorkflowSearchItem[];
    readonly loadMore: () => Promise<void>;
    readonly moreError: string | null;
    readonly nextCursor: string | null;
    readonly query: string;
    readonly search: string;
    readonly updateQuery: (value: string) => void;
}

export function useWorkflowLibrarySearch(
    api: WorkflowApi,
): WorkflowLibrarySearch {
    const [query, setQuery] = useState("");
    const search = useDebouncedValue(query.trim(), 275);
    const [items, setItems] = useState<readonly WorkflowSearchItem[]>([]);
    const [nextCursor, setNextCursor] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [moreError, setMoreError] = useState<string | null>(null);
    const [reloadToken, setReloadToken] = useState(0);
    const requestSequence = useRef(0);
    const activeRequest = useRef<AbortController | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        activeRequest.current = controller;
        const sequence = ++requestSequence.current;
        void api
            .searchWorkflows(search, null, controller.signal)
            .then(({ body }) => {
                if (requestSequence.current === sequence) {
                    setItems(body.items);
                    setNextCursor(body.next_cursor ?? null);
                    setIsLoading(false);
                    setIsLoadingMore(false);
                }
            })
            .catch((caught: unknown) => {
                if (isAbort(caught)) {
                    return;
                }
                if (requestSequence.current === sequence) {
                    setError(
                        caught instanceof Error
                            ? caught.message
                            : "Workflows could not be loaded.",
                    );
                    setIsLoading(false);
                }
            });
        return () => {
            controller.abort();
            if (activeRequest.current === controller) {
                activeRequest.current = null;
            }
        };
    }, [api, reloadToken, search]);

    useEffect(
        () => () => {
            activeRequest.current?.abort();
        },
        [],
    );

    const updateQuery = (value: string) => {
        const nextSearch = value.trim();
        setQuery(value);
        if (nextSearch === search) {
            if (activeRequest.current?.signal.aborted === true) {
                setReloadToken((current) => current + 1);
            }
            return;
        }
        activeRequest.current?.abort();
        requestSequence.current += 1;
        setIsLoading(true);
        setIsLoadingMore(false);
        setNextCursor(null);
        setError(null);
        setMoreError(null);
    };

    const loadMore = async () => {
        if (nextCursor === null || isLoadingMore) {
            return;
        }
        const controller = new AbortController();
        activeRequest.current = controller;
        const sequence = ++requestSequence.current;
        setIsLoadingMore(true);
        setMoreError(null);
        try {
            const { body } = await api.searchWorkflows(
                search,
                nextCursor,
                controller.signal,
            );
            if (requestSequence.current !== sequence) {
                return;
            }
            setItems((current) => mergeWorkflows(current, body.items));
            setNextCursor(body.next_cursor ?? null);
        } catch (caught) {
            if (!isAbort(caught) && requestSequence.current === sequence) {
                setMoreError(
                    caught instanceof Error
                        ? caught.message
                        : "More Workflows could not be loaded.",
                );
            }
        } finally {
            if (requestSequence.current === sequence) {
                setIsLoadingMore(false);
            }
        }
    };

    return {
        error,
        isLoading,
        isLoadingMore,
        items,
        loadMore,
        moreError,
        nextCursor,
        query,
        search,
        updateQuery,
    };
}

function mergeWorkflows(
    current: readonly WorkflowSearchItem[],
    incoming: readonly WorkflowSearchItem[],
): readonly WorkflowSearchItem[] {
    const byId = new Map(
        current.map((workflow) => [workflow.workflow_id, workflow]),
    );
    for (const workflow of incoming) {
        byId.set(workflow.workflow_id, workflow);
    }
    return [...byId.values()];
}

function isAbort(caught: unknown): boolean {
    return caught instanceof DOMException && caught.name === "AbortError";
}
