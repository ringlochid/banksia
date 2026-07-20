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
    type DefinitionListQuery,
} from "../../api/routes";
import type { DefinitionKind, DefinitionListKind, DefinitionListSort } from "./definition-model";

const DEFINITION_PAGE_SIZE = 4;
const VERSION_PAGE_SIZE = 10;

export type DefinitionListResponse = components["schemas"]["DefinitionSummaryListResponse"];
export type DefinitionRevisionDetailResponse =
    components["schemas"]["DefinitionRevisionDetailResponse"];
export type DefinitionRevisionHistoryResponse =
    components["schemas"]["DefinitionRevisionHistoryResponse"];
export type DefinitionHistorySort = components["schemas"]["DefinitionHistorySort"];
export type NodeKind = components["schemas"]["NodeKind"];

export async function readDefinitionPage({
    allowedNodeKind,
    appliesTo,
    cursor,
    kind,
    signal,
    sort,
    trimmedQuery,
}: {
    readonly allowedNodeKind: NodeKind | null;
    readonly appliesTo: NodeKind | null;
    readonly cursor: string | null;
    readonly kind: DefinitionListKind;
    readonly signal: AbortSignal | undefined;
    readonly sort: DefinitionListSort;
    readonly trimmedQuery: string;
}): Promise<DefinitionListResponse> {
    const query: DefinitionListQuery = {
        cursor,
        limit: DEFINITION_PAGE_SIZE,
        q: trimmedQuery.length === 0 ? null : trimmedQuery,
        sort,
    };

    if (kind === "roles" && allowedNodeKind !== null) {
        query.allowed_node_kind = allowedNodeKind;
    }
    if (kind === "policies" && appliesTo !== null) {
        query.applies_to = appliesTo;
    }

    const route = definitionsRoute(kind, query);
    return requestJson<DefinitionListResponse>({
        path: route.path,
        query: route.query,
        signal,
    });
}

export async function readDefinitionDetail({
    key,
    kind,
    signal,
}: {
    readonly key: string;
    readonly kind: DefinitionKind;
    readonly signal: AbortSignal | undefined;
}): Promise<DefinitionRevisionDetailResponse> {
    const route = definitionRoute(kind, key);
    return requestJson<DefinitionRevisionDetailResponse>({
        path: route.path,
        signal,
    });
}

export async function readDefinitionVersions({
    cursor,
    key,
    kind,
    signal,
}: {
    readonly cursor: string | null;
    readonly key: string;
    readonly kind: DefinitionKind;
    readonly signal: AbortSignal | undefined;
}): Promise<DefinitionRevisionHistoryResponse> {
    const route = definitionVersionsRoute(kind, key, {
        cursor,
        limit: VERSION_PAGE_SIZE,
        sort: "revision_no_desc",
    });
    return requestJson<DefinitionRevisionHistoryResponse>({
        path: route.path,
        query: route.query,
        signal,
    });
}

export function toErrorView(error: unknown): ConsoleErrorView {
    return mapUnknownApiError(error);
}

export function isAbortError(error: unknown): boolean {
    return isApiAbortError(error);
}
