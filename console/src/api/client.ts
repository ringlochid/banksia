import type {
    CreateWorkflowDraftRequest,
    DraftOperation,
    WorkflowAuthoringOptions,
    WorkflowDraftDiscardResult,
    WorkflowDraftMutationResult,
    WorkflowDraftOpenResult,
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowGetResponse,
    WorkflowPublishedReadback,
    WorkflowRemovalResult,
    WorkflowSearchResponse,
    WorkflowStaleDraftResponse,
} from "./types";

export interface ControllerResponse<T> {
    readonly body: T;
    readonly etag: string | null;
    readonly status: number;
}

export interface ProductEventSource {
    addEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject,
    ): void;
    removeEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject,
    ): void;
    close(): void;
}

export type ProductEventSourceFactory = (url: string) => ProductEventSource;

export const browserEventSourceFactory: ProductEventSourceFactory = (url) =>
    new EventSource(url);

export class ApiResponseError extends Error {
    public constructor(
        public readonly status: number,
        public readonly body: unknown,
    ) {
        super(responseMessage(body, status));
        this.name = "ApiResponseError";
    }

    public staleDraft(): WorkflowStaleDraftResponse | null {
        if (this.status !== 412 || !isObject(this.body)) {
            return null;
        }
        const detail = this.body.detail;
        return isObject(detail) && isObject(detail.current)
            ? (this.body as WorkflowStaleDraftResponse)
            : null;
    }
}

export class ApiNetworkError extends Error {
    public constructor(public readonly cause: unknown) {
        super(
            "Banksia could not connect. Check that it is running, then try again.",
        );
        this.name = "ApiNetworkError";
    }
}

export async function requestProductApi<T>(
    apiRoot: string,
    path: string,
    init: RequestInit = {},
): Promise<ControllerResponse<T>> {
    let response: Response;
    try {
        response = await fetch(resolveProductApiUrl(apiRoot, path), {
            ...init,
            headers: {
                Accept: "application/json",
                ...init.headers,
            },
        });
    } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
            throw error;
        }
        throw new ApiNetworkError(error);
    }
    const body = await responseBody(response);
    if (!response.ok) {
        throw new ApiResponseError(response.status, unwrapHttpDetail(body));
    }
    return {
        body: body as T,
        etag: response.headers.get("ETag"),
        status: response.status,
    };
}

export interface WorkflowApi {
    searchWorkflows(
        query: string,
        cursor?: string | null,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowSearchResponse>>;
    getWorkflow(
        workflowId: string,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowGetResponse>>;
    removeWorkflow(
        workflowId: string,
    ): Promise<ControllerResponse<WorkflowRemovalResult>>;
    getAuthoringOptions(
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowAuthoringOptions>>;
    createWorkflow(
        request: CreateWorkflowDraftRequest,
    ): Promise<ControllerResponse<WorkflowDraftOpenResult>>;
    openWorkflow(
        workflowId: string,
    ): Promise<ControllerResponse<WorkflowDraftOpenResult>>;
    mutateDraft(
        draftId: string,
        etag: string,
        operation: DraftOperation,
    ): Promise<ControllerResponse<WorkflowDraftMutationResult>>;
    validateDraft(
        draftId: string,
    ): Promise<ControllerResponse<WorkflowDraftValidationResult>>;
    publishDraft(
        draftId: string,
        etag: string,
    ): Promise<ControllerResponse<WorkflowPublishedReadback>>;
    discardDraft(
        draftId: string,
        etag: string,
    ): Promise<ControllerResponse<WorkflowDraftDiscardResult>>;
    undoDraft(
        draftId: string,
        etag: string,
        receiptId: string,
    ): Promise<ControllerResponse<WorkflowDraftReadback>>;
}

export class WorkflowApiClient implements WorkflowApi {
    public constructor(private readonly apiRoot = "/api") {}

    public searchWorkflows(
        query: string,
        cursor: string | null = null,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowSearchResponse>> {
        const parameters = new URLSearchParams();
        if (query !== "") {
            parameters.set("q", query);
        }
        if (cursor !== null) {
            parameters.set("cursor", cursor);
        }
        const suffix = parameters.size === 0 ? "" : `?${parameters.toString()}`;
        return requestProductApi(
            this.apiRoot,
            `/workflows${suffix}`,
            signal === undefined ? {} : { signal },
        );
    }

    public getWorkflow(
        workflowId: string,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowGetResponse>> {
        return requestProductApi(
            this.apiRoot,
            `/workflows/${encodeURIComponent(workflowId)}`,
            signal === undefined ? {} : { signal },
        );
    }

    public removeWorkflow(
        workflowId: string,
    ): Promise<ControllerResponse<WorkflowRemovalResult>> {
        return requestProductApi(
            this.apiRoot,
            `/workflows/${encodeURIComponent(workflowId)}`,
            { method: "DELETE" },
        );
    }

    public getAuthoringOptions(
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowAuthoringOptions>> {
        return requestProductApi(
            this.apiRoot,
            "/workflows/authoring-options",
            signal === undefined ? {} : { signal },
        );
    }

    public createWorkflow(
        request: CreateWorkflowDraftRequest,
    ): Promise<ControllerResponse<WorkflowDraftOpenResult>> {
        return requestProductApi(
            this.apiRoot,
            "/workflow-drafts",
            jsonRequest("POST", request),
        );
    }

    public openWorkflow(
        workflowId: string,
    ): Promise<ControllerResponse<WorkflowDraftOpenResult>> {
        return requestProductApi(
            this.apiRoot,
            "/workflow-drafts",
            jsonRequest("POST", { kind: "open", workflow_id: workflowId }),
        );
    }

    public mutateDraft(
        draftId: string,
        etag: string,
        operation: DraftOperation,
    ): Promise<ControllerResponse<WorkflowDraftMutationResult>> {
        return requestProductApi(
            this.apiRoot,
            `/workflow-drafts/${encodeURIComponent(draftId)}`,
            jsonRequest("PATCH", operation, etag),
        );
    }

    public validateDraft(
        draftId: string,
    ): Promise<ControllerResponse<WorkflowDraftValidationResult>> {
        return requestProductApi(
            this.apiRoot,
            `/workflow-drafts/${encodeURIComponent(draftId)}/validate`,
            { method: "POST" },
        );
    }

    public publishDraft(
        draftId: string,
        etag: string,
    ): Promise<ControllerResponse<WorkflowPublishedReadback>> {
        return requestProductApi(
            this.apiRoot,
            `/workflow-drafts/${encodeURIComponent(draftId)}/publish`,
            { method: "POST", headers: { "If-Match": etag } },
        );
    }

    public discardDraft(
        draftId: string,
        etag: string,
    ): Promise<ControllerResponse<WorkflowDraftDiscardResult>> {
        return requestProductApi(
            this.apiRoot,
            `/workflow-drafts/${encodeURIComponent(draftId)}`,
            {
                method: "DELETE",
                headers: { "If-Match": etag },
            },
        );
    }

    public undoDraft(
        draftId: string,
        etag: string,
        receiptId: string,
    ): Promise<ControllerResponse<WorkflowDraftReadback>> {
        return requestProductApi(
            this.apiRoot,
            `/workflow-drafts/${encodeURIComponent(draftId)}/undo`,
            jsonRequest("POST", { receipt_id: receiptId }, etag),
        );
    }
}

function jsonRequest(
    method: string,
    body: unknown,
    etag?: string,
): RequestInit {
    return {
        method,
        headers: {
            "Content-Type": "application/json",
            ...(etag === undefined ? {} : { "If-Match": etag }),
        },
        body: JSON.stringify(body),
    };
}

async function responseBody(response: Response): Promise<unknown> {
    if (response.status === 204) {
        return null;
    }
    const text = await response.text();
    if (text === "") {
        return null;
    }
    try {
        return JSON.parse(text) as unknown;
    } catch {
        return text;
    }
}

function unwrapHttpDetail(body: unknown): unknown {
    if (!isObject(body) || !("detail" in body)) {
        return body;
    }
    const detail = body.detail;
    if (isObject(detail) && ("current" in detail || "message" in detail)) {
        return { detail };
    }
    return detail;
}

function responseMessage(body: unknown, status: number): string {
    const candidate = isObject(body)
        ? (body.summary ??
          (isObject(body.detail) ? body.detail.message : undefined))
        : undefined;
    return typeof candidate === "string"
        ? candidate
        : `Banksia returned an unexpected response (${status}).`;
}

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null;
}

export function resolveProductApiUrl(apiRoot: string, path: string): string {
    const normalizedRoot = apiRoot.endsWith("/")
        ? apiRoot.slice(0, -1)
        : apiRoot;
    if (path === "/api" || path.startsWith("/api/")) {
        return normalizedRoot.endsWith("/api")
            ? `${normalizedRoot.slice(0, -4)}${path}`
            : `${normalizedRoot}${path}`;
    }
    return `${normalizedRoot}${path.startsWith("/") ? path : `/${path}`}`;
}
