import type { ConsoleErrorView } from "../../api/client";
import type { StatusTone } from "../../components/ui";
import type { NewDraftFormState } from "./definition-editor-dialogs";
import type {
    DefinitionDraftKind,
    DefinitionDraftMode,
    DraftDetail,
    DraftIdentity,
    DraftSummary,
} from "./definition-editor-data";

export interface DraftListState {
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
    readonly nextCursor: string | null;
    readonly rows: readonly DraftSummary[];
}

export interface DraftDetailState {
    readonly draft: DraftDetail | null;
    readonly error: ConsoleErrorView | null;
    readonly isLoading: boolean;
}

export const initialListState: DraftListState = {
    error: null,
    isLoading: true,
    nextCursor: null,
    rows: [],
};

export const initialDetailState: DraftDetailState = {
    draft: null,
    error: null,
    isLoading: false,
};

export const initialNewDraftForm: NewDraftFormState = {
    description: "",
    error: null,
    isCreating: false,
    isOpen: false,
    key: "",
    kind: "role",
    mode: "create",
};

export function draftIdentityFromSearch(searchParams: URLSearchParams): DraftIdentity | null {
    const kind = coerceDraftKind(searchParams.get("kind") ?? searchParams.get("materialize_kind"));
    const key = normalizeDraftKey(
        searchParams.get("key") ?? searchParams.get("materialize_key") ?? "",
    );
    return kind === null || key.length === 0 ? null : { key, kind };
}

export function draftIdentityFromSummary(summary: DraftSummary): DraftIdentity {
    return { key: summary.key, kind: summary.kind };
}

export function draftIdentityKey(identity: DraftIdentity): string {
    return `${identity.kind}:${identity.key}`;
}

export function draftIdentityEquals(
    left: DraftIdentity | null,
    right: DraftIdentity | null,
): boolean {
    if (left === null || right === null) {
        return left === right;
    }
    return left.kind === right.kind && left.key === right.key;
}

export function draftSummaryFromDetail(draft: DraftDetail): DraftSummary {
    return {
        based_on: draft.based_on,
        body_format: draft.body_format,
        content_hash: draft.content_hash,
        draft_path: draft.draft_path,
        key: draft.key,
        kind: draft.kind,
        mode: draft.mode,
        normalized_path: draft.normalized_path,
        status: draft.status,
        updated_at: draft.updated_at,
    };
}

export function compareDraftSummaryUpdatedAt(left: DraftSummary, right: DraftSummary): number {
    return right.updated_at.localeCompare(left.updated_at);
}

export function kindLabel(kind: DefinitionDraftKind): string {
    switch (kind) {
        case "policy":
            return "Policy";
        case "role":
            return "Role";
        case "workflow":
            return "Workflow";
    }
}

export function modeLabel(mode: DefinitionDraftMode): string {
    return mode === "create" ? "Create" : "Update";
}

export function statusLabel(status: DraftDetail["status"]): string {
    return status.replace(/_/g, " ");
}

export function statusTone(status: DraftDetail["status"]): StatusTone {
    switch (status) {
        case "clean":
            return "success";
        case "modified":
        case "new":
            return "warning";
        case "stale":
        case "invalid":
            return "danger";
    }
}

export function formError(summary: string): ConsoleErrorView {
    return {
        code: "invalid_form",
        fieldErrors: [],
        isRetryable: false,
        source: "validation",
        status: null,
        suggestedNextStep: null,
        summary,
        title: "Invalid Draft",
    };
}

export function normalizeDraftKey(value: string): string {
    return value.trim();
}

function coerceDraftKind(value: string | null): DefinitionDraftKind | null {
    if (value === "role" || value === "policy" || value === "workflow") {
        return value;
    }
    return null;
}
