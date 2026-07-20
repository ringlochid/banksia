import { getConsoleConfig, type ConsoleConfig } from "../app/config";

export type QueryPrimitive = string | number | boolean;
export type QueryValue = QueryPrimitive | null | undefined | readonly QueryPrimitive[];
export type QueryParams = Readonly<Record<string, QueryValue>>;

export interface ConsoleFieldError {
    readonly code: string;
    readonly message: string;
    readonly path: string;
}

export interface ConsoleErrorView {
    readonly code: string;
    readonly title: string;
    readonly summary: string;
    readonly status: number | null;
    readonly isRetryable: boolean;
    readonly suggestedNextStep: string | null;
    readonly fieldErrors: readonly ConsoleFieldError[];
    readonly source:
        "operation_failure" | "validation" | "http" | "network" | "stream" | "abort" | "unknown";
}

export interface ApiRequestOptions {
    readonly body?: unknown;
    readonly config?: ConsoleConfig;
    readonly fetchImpl?: typeof fetch;
    readonly method?: "DELETE" | "GET" | "POST" | "PUT";
    readonly path: string;
    readonly query?: QueryParams | URLSearchParams;
    readonly signal?: AbortSignal;
}

export class AutoClawApiError extends Error {
    readonly errorView: ConsoleErrorView;
    readonly response: Response | null;

    constructor(errorView: ConsoleErrorView, response: Response | null = null) {
        super(errorView.summary);
        this.name = "AutoClawApiError";
        this.errorView = errorView;
        this.response = response;
    }
}

export function buildQueryParams(
    query: QueryParams | URLSearchParams | undefined,
): URLSearchParams {
    if (query === undefined) {
        return new URLSearchParams();
    }

    if (query instanceof URLSearchParams) {
        return new URLSearchParams(query);
    }

    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
        appendQueryValue(searchParams, key, value);
    }
    return searchParams;
}

export function getNextCursor(page: { readonly next_cursor?: string | null }): string | null {
    return page.next_cursor ?? null;
}

export function resolveApiUrl(
    path: string,
    config: ConsoleConfig,
    query?: QueryParams | URLSearchParams,
): URL {
    const url = new URL(path.replace(/^\/+/, ""), `${config.apiBaseUrl}/`);
    const searchParams = buildQueryParams(query);
    if (searchParams.size > 0) {
        url.search = searchParams.toString();
    }
    return url;
}

export function isCursorResetError(errorView: ConsoleErrorView): boolean {
    return errorView.code === "cursor_reset_required";
}

export function isApiAbortError(error: unknown): boolean {
    if (error instanceof AutoClawApiError) {
        return error.errorView.source === "abort";
    }

    return (error instanceof Error || error instanceof DOMException) && error.name === "AbortError";
}

export function mapUnknownApiError(error: unknown): ConsoleErrorView {
    if (error instanceof AutoClawApiError) {
        return error.errorView;
    }
    if (isApiAbortError(error)) {
        return createApiTransportError(error).errorView;
    }

    return {
        code: "unexpected_client_error",
        title: "Unexpected Error",
        summary: "The console could not complete the requested operation.",
        status: null,
        isRetryable: false,
        suggestedNextStep: null,
        fieldErrors: [],
        source: "unknown",
    };
}

export async function createApiErrorFromResponse(response: Response): Promise<AutoClawApiError> {
    const bodyText = await response.text();
    const parsedBody = parseJsonBody(bodyText);
    return new AutoClawApiError(normalizeResponseError(response, parsedBody), response);
}

export async function requestJson<TResponse>({
    body,
    config = getConsoleConfig(),
    fetchImpl = fetch,
    method = "GET",
    path,
    query,
    signal,
}: ApiRequestOptions): Promise<TResponse> {
    const url = resolveApiUrl(path, config, query);

    const headers = new Headers({ Accept: "application/json" });
    if (body !== undefined) {
        headers.set("Content-Type", "application/json");
    }

    let response: Response;
    try {
        response = await fetchImpl(url, {
            body: body === undefined ? undefined : JSON.stringify(body),
            headers,
            method,
            signal,
        });
    } catch (error) {
        throw createApiTransportError(error);
    }

    if (!response.ok) {
        throw await createApiErrorFromResponse(response);
    }

    const responseText = await response.text();
    if (responseText.trim() === "") {
        return undefined as TResponse;
    }

    try {
        return JSON.parse(responseText) as TResponse;
    } catch {
        throw createInvalidJsonResponseError(response);
    }
}

function appendQueryValue(searchParams: URLSearchParams, key: string, value: QueryValue): void {
    if (value === null || value === undefined) {
        return;
    }

    if (Array.isArray(value)) {
        for (const item of value) {
            searchParams.append(key, String(item));
        }
        return;
    }

    searchParams.set(key, String(value));
}

export function createApiTransportError(error: unknown): AutoClawApiError {
    const isAbort = isApiAbortError(error);
    return new AutoClawApiError({
        code: isAbort ? "request_aborted" : "network_error",
        title: isAbort ? "Request Aborted" : "Network Error",
        summary: isAbort
            ? "The request was aborted before it completed."
            : "The console could not reach the AutoClaw API.",
        status: null,
        isRetryable: !isAbort,
        suggestedNextStep: isAbort ? null : "Check the API service and retry the request.",
        fieldErrors: [],
        source: isAbort ? "abort" : "network",
    });
}

function normalizeResponseError(response: Response, parsedBody: unknown): ConsoleErrorView {
    const operationFailure = readOperationFailure(parsedBody);
    if (operationFailure !== null) {
        const isValidationFailure =
            response.status === 400 && operationFailure.code === "invalid_request_shape";
        return {
            code: operationFailure.code,
            title: isValidationFailure ? "Validation Error" : titleFromCode(operationFailure.code),
            summary: operationFailure.summary,
            status: response.status,
            isRetryable: operationFailure.isRetryable,
            suggestedNextStep: operationFailure.suggestedNextStep,
            fieldErrors:
                operationFailure.fieldPath === null
                    ? []
                    : [
                          {
                              code: operationFailure.code,
                              message: operationFailure.summary,
                              path: operationFailure.fieldPath,
                          },
                      ],
            source: isValidationFailure ? "validation" : "operation_failure",
        };
    }

    return {
        code: codeFromHttpStatus(response.status),
        title: titleFromHttpStatus(response.status),
        summary: fallbackHttpSummary(),
        status: response.status,
        isRetryable: response.status >= 500,
        suggestedNextStep: response.status >= 500 ? "Retry after the API service recovers." : null,
        fieldErrors: [],
        source: "http",
    };
}

function parseJsonBody(bodyText: string): unknown {
    if (bodyText.trim() === "") {
        return null;
    }

    try {
        return JSON.parse(bodyText) as unknown;
    } catch {
        return null;
    }
}

function readOperationFailure(parsedBody: unknown): {
    readonly code: string;
    readonly fieldPath: string | null;
    readonly isRetryable: boolean;
    readonly suggestedNextStep: string | null;
    readonly summary: string;
} | null {
    if (!isRecord(parsedBody)) {
        return null;
    }

    const code = parsedBody.code;
    const fieldPath = parsedBody.field_path;
    const ok = parsedBody.ok;
    const retryable = parsedBody.retryable;
    const suggestedNextStep = parsedBody.suggested_next_step;
    const summary = parsedBody.summary;

    if (
        ok !== false ||
        typeof code !== "string" ||
        typeof retryable !== "boolean" ||
        typeof summary !== "string"
    ) {
        return null;
    }

    return {
        code,
        summary,
        fieldPath: typeof fieldPath === "string" ? fieldPath : null,
        isRetryable: retryable,
        suggestedNextStep: typeof suggestedNextStep === "string" ? suggestedNextStep : null,
    };
}

function codeFromHttpStatus(status: number): string {
    if (status === 401) {
        return "auth_required";
    }
    if (status === 403) {
        return "permission_denied";
    }
    if (status === 404) {
        return "missing_resource";
    }
    return `http_${String(status)}`;
}

function fallbackHttpSummary(): string {
    return "The AutoClaw API returned an unexpected error response.";
}

function createInvalidJsonResponseError(response: Response): AutoClawApiError {
    return new AutoClawApiError(
        {
            code: "invalid_json_response",
            title: "Invalid API Response",
            summary: "The AutoClaw API returned a response that the console could not read.",
            status: response.status,
            isRetryable: true,
            suggestedNextStep: "Retry after the API service recovers.",
            fieldErrors: [],
            source: "http",
        },
        response,
    );
}

function titleFromCode(code: string): string {
    return code
        .split("_")
        .filter((part) => part.length > 0)
        .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
        .join(" ");
}

function titleFromHttpStatus(status: number): string {
    if (status === 401) {
        return "Authentication Required";
    }
    if (status === 403) {
        return "Permission Denied";
    }
    if (status === 404) {
        return "Missing Resource";
    }
    if (status >= 500) {
        return "API Error";
    }
    return "Request Failed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type OperationFailureCode = string;
