import {
    isApiAbortError,
    mapUnknownApiError,
    requestJson,
    type ConsoleErrorView,
} from "../../api/client";
import type { components } from "../../api/generated/openapi";
import {
    definitionRoute,
    definitionsRoute,
    definitionVersionsRoute,
    taskComposePreviewRoute,
    taskStartRoute,
    type DefinitionListQuery,
} from "../../api/routes";
import type {
    DefinitionRevisionDetailResponse,
    TaskComposePreviewResponse,
    TaskStartRequest,
    TaskStartResponse,
} from "./task-start-model";

const WORKFLOW_SEARCH_LIMIT = 8;
const VERSION_PAGE_SIZE = 6;

export type WorkflowListResponse = components["schemas"]["DefinitionSummaryListResponse"];
export type WorkflowVersionsResponse = components["schemas"]["DefinitionRevisionHistoryResponse"];
export type DefinitionListSort = components["schemas"]["DefinitionListSort"];

export async function readWorkflowChoices({
    cursor,
    signal,
    sort,
    trimmedQuery,
}: {
    readonly cursor: string | null;
    readonly signal: AbortSignal | undefined;
    readonly sort: DefinitionListSort;
    readonly trimmedQuery: string;
}): Promise<WorkflowListResponse> {
    const query: DefinitionListQuery = {
        cursor,
        limit: WORKFLOW_SEARCH_LIMIT,
        q: trimmedQuery.length === 0 ? null : trimmedQuery,
        sort,
    };
    const route = definitionsRoute("workflows", query);
    return requestJson<WorkflowListResponse>({
        path: route.path,
        query: route.query,
        signal,
    });
}

export async function readWorkflowDetail({
    key,
    signal,
}: {
    readonly key: string;
    readonly signal: AbortSignal | undefined;
}): Promise<DefinitionRevisionDetailResponse> {
    const route = definitionRoute("workflow", key);
    return requestJson<DefinitionRevisionDetailResponse>({
        path: route.path,
        signal,
    });
}

export async function readWorkflowVersions({
    key,
    signal,
}: {
    readonly key: string;
    readonly signal: AbortSignal | undefined;
}): Promise<WorkflowVersionsResponse> {
    const route = definitionVersionsRoute("workflow", key, {
        cursor: null,
        limit: VERSION_PAGE_SIZE,
        sort: "revision_no_desc",
    });
    return requestJson<WorkflowVersionsResponse>({
        path: route.path,
        query: route.query,
        signal,
    });
}

export async function startTask(request: TaskStartRequest): Promise<TaskStartResponse> {
    const route = taskStartRoute();
    return requestJson<TaskStartResponse>({
        body: request,
        method: "POST",
        path: route.path,
    });
}

export async function previewTaskStart(
    request: TaskStartRequest,
): Promise<TaskComposePreviewResponse> {
    const route = taskComposePreviewRoute();
    return requestJson<TaskComposePreviewResponse>({
        body: request,
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

export function isAuthError(error: ConsoleErrorView): boolean {
    return error.status === 401 || error.status === 403 || error.code === "illegal_caller";
}
