import { mapUnknownApiError, requestJson, type ConsoleErrorView } from "../../api/client";
import type { components } from "../../api/generated/openapi";
import {
    definitionDraftPublishRoute,
    definitionDraftRoute,
    definitionDraftReplaceCurrentRoute,
    definitionDraftsRoute,
    definitionDraftValidateRoute,
    type DefinitionDraftsQuery,
} from "../../api/routes";

export type DefinitionDraftKind = components["schemas"]["DefinitionKind"];
export type DefinitionDraftMode = components["schemas"]["DefinitionDraftMode"];
export type DefinitionDraftStatus = components["schemas"]["DefinitionDraftStatus"];
export type DraftListResponse = components["schemas"]["DefinitionDraftListResponse"];
export type DraftDetail = components["schemas"]["DefinitionDraftDetail"];
export type DraftDetailResponse = components["schemas"]["DefinitionDraftDetailResponse"];
export type DraftSummary = components["schemas"]["DefinitionDraftSummary"];
export type DraftValidationResponse = components["schemas"]["DefinitionDraftValidationResponse"];
export type DraftPublishResponse = components["schemas"]["DefinitionDraftPublishResponse"];

export interface DraftIdentity {
    readonly key: string;
    readonly kind: DefinitionDraftKind;
}

export async function readDrafts({
    cursor = null,
    limit = 50,
    signal,
}: {
    readonly cursor?: string | null;
    readonly limit?: number;
    readonly signal?: AbortSignal;
} = {}): Promise<DraftListResponse> {
    const query: DefinitionDraftsQuery = { cursor, limit };
    const route = definitionDraftsRoute(query);
    return requestJson<DraftListResponse>({
        path: route.path,
        query: route.query,
        signal,
    });
}

export async function createDraft({
    body,
    key,
    kind,
    mode,
}: {
    readonly body?: string;
    readonly key: string;
    readonly kind: DefinitionDraftKind;
    readonly mode: DefinitionDraftMode;
}): Promise<DraftDetailResponse> {
    const route = definitionDraftsRoute();
    return requestJson<DraftDetailResponse>({
        body: {
            body: body ?? null,
            body_format: "yaml",
            key,
            kind,
            mode,
        } satisfies components["schemas"]["DefinitionDraftCreateRequest"],
        method: "POST",
        path: route.path,
    });
}

export async function readDraft({
    key,
    kind,
    signal,
}: DraftIdentity & { readonly signal?: AbortSignal }): Promise<DraftDetailResponse> {
    const route = definitionDraftRoute(kind, key);
    return requestJson<DraftDetailResponse>({
        path: route.path,
        signal,
    });
}

export async function saveDraft({
    body,
    key,
    kind,
}: DraftIdentity & { readonly body: string }): Promise<DraftDetailResponse> {
    const route = definitionDraftRoute(kind, key);
    return requestJson<DraftDetailResponse>({
        body: {
            body,
            body_format: "yaml",
        } satisfies components["schemas"]["DefinitionDraftWriteRequest"],
        method: "PUT",
        path: route.path,
    });
}

export async function deleteDraft({ key, kind }: DraftIdentity): Promise<void> {
    const route = definitionDraftRoute(kind, key);
    await requestJson<undefined>({
        method: "DELETE",
        path: route.path,
    });
}

export async function validateDraft({
    key,
    kind,
}: DraftIdentity): Promise<DraftValidationResponse> {
    const route = definitionDraftValidateRoute(kind, key);
    return requestJson<DraftValidationResponse>({
        method: "POST",
        path: route.path,
    });
}

export async function publishDraft({ key, kind }: DraftIdentity): Promise<DraftPublishResponse> {
    const route = definitionDraftPublishRoute(kind, key);
    return requestJson<DraftPublishResponse>({
        method: "POST",
        path: route.path,
    });
}

export async function replaceDraftWithCurrent({
    key,
    kind,
}: DraftIdentity): Promise<DraftDetailResponse> {
    const route = definitionDraftReplaceCurrentRoute(kind, key);
    return requestJson<DraftDetailResponse>({
        method: "POST",
        path: route.path,
    });
}

export function toErrorView(error: unknown): ConsoleErrorView {
    return mapUnknownApiError(error);
}

export function isAuthError(error: ConsoleErrorView): boolean {
    return (
        error.status === 401 ||
        error.status === 403 ||
        error.code === "illegal_caller" ||
        error.code === "capability_rejected" ||
        error.code === "auth_required" ||
        error.code === "permission_denied"
    );
}
