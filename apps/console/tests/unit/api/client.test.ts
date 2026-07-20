import { describe, expect, it } from "vitest";

import {
    AutoClawApiError,
    isApiAbortError,
    mapUnknownApiError,
    requestJson,
    type ConsoleErrorView,
} from "../../../src/api/client";

const config = { apiBaseUrl: "http://127.0.0.1:18125" };

describe("shared API error mapping", () => {
    it("preserves normalized AutoClaw errors", () => {
        const errorView: ConsoleErrorView = {
            code: "stale_flow_revision",
            fieldErrors: [],
            isRetryable: true,
            source: "operation_failure",
            status: 409,
            suggestedNextStep: "Reread current task state.",
            summary: "The active flow revision is stale.",
            title: "Stale Flow Revision",
        };
        const error = new AutoClawApiError(errorView);

        expect(mapUnknownApiError(error)).toBe(errorView);
        expect(isApiAbortError(error)).toBe(false);
    });

    it("recognizes native and requestJson abort errors", async () => {
        const nativeAbort = new DOMException("private abort detail", "AbortError");
        const requestError = await captureRequestError(async () =>
            requestJson<unknown>({
                config,
                fetchImpl: async () => Promise.reject(nativeAbort),
                path: "/runtime/tasks",
            }),
        );

        expect(isApiAbortError(nativeAbort)).toBe(true);
        expect(isApiAbortError(requestError)).toBe(true);
        expect(mapUnknownApiError(requestError)).toBe(requestError.errorView);
        expect(requestError.errorView.source).toBe("abort");
        expect(requestError.errorView.summary).not.toContain("private");
    });

    it("maps arbitrary failures without exposing messages, bodies, or stacks", () => {
        const secretError = new Error("secret-token from raw response body");
        secretError.stack = "private stack trace";

        const errorView = mapUnknownApiError(secretError);

        expect(errorView).toEqual({
            code: "unexpected_client_error",
            fieldErrors: [],
            isRetryable: false,
            source: "unknown",
            status: null,
            suggestedNextStep: null,
            summary: "The console could not complete the requested operation.",
            title: "Unexpected Error",
        });
        expect(JSON.stringify(errorView)).not.toMatch(/secret|private stack/i);
    });
});

async function captureRequestError(request: () => Promise<unknown>): Promise<AutoClawApiError> {
    try {
        await request();
    } catch (error) {
        if (error instanceof AutoClawApiError) {
            return error;
        }
        throw error;
    }

    throw new Error("Expected the API request to fail");
}
