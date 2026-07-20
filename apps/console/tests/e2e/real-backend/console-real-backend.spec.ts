import { expect, test, type APIRequestContext, type Page, type Request } from "@playwright/test";

import type { components } from "../../../src/api/generated/openapi";

type RuntimeFlowRead = components["schemas"]["RuntimeFlowRead"];
type TaskEventRecord = components["schemas"]["TaskEventRecord"];
type TaskStartResponse = components["schemas"]["TaskStartResponse"];

test("uses the packaged console with real controller, event, and local-admission truth", async ({
    baseURL,
    page,
    request,
}) => {
    expect(baseURL).toBeDefined();
    const observedRequests: Request[] = [];
    page.on("request", (observedRequest) => {
        if (observedRequest.url().startsWith(baseURL ?? "")) {
            observedRequests.push(observedRequest);
        }
    });

    await proveSeededDefinitionRead(page);
    const startedTask = await startTaskThroughConsole(page);
    await page.goto(`/tasks/${encodeURIComponent(startedTask.task_id)}`);
    await expect(
        page.getByRole("heading", { level: 1, name: "Real backend browser smoke" }),
    ).toBeVisible();

    const runningFlow = await waitForCurrentDispatch(request, startedTask.task_id);
    await proveLocalAdmission(request, startedTask, baseURL ?? "");
    await proveCursorResetAndReconnect({ page, request, runningFlow });
    await proveNoBrowserCredentialBootstrap(page, request, observedRequests);

    // Let the cancelled SSE fetch release its request-scoped database session
    // before Playwright stops the application lifespan.
    await page.goto("about:blank");
    await page.waitForTimeout(250);
});

async function proveSeededDefinitionRead(page: Page): Promise<void> {
    const definitionResponsePromise = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === "GET" && url.pathname === "/definitions/roles";
    });

    await page.goto("/definitions");
    const definitionResponse = await definitionResponsePromise;
    const definitionPage = (await definitionResponse.json()) as {
        readonly items: readonly { readonly key: string }[];
    };

    expect(definitionResponse.status()).toBe(200);
    expect(definitionPage.items.length).toBeGreaterThan(0);
    await expect(page.getByRole("list", { name: "Definition rows" })).toBeVisible();
}

async function startTaskThroughConsole(page: Page): Promise<TaskStartResponse> {
    await page.goto("/task-start");
    const workflowSearch = page.getByRole("combobox", { name: "Search workflow" });
    const selectedWorkflow = page.getByRole("group", { name: "Selected workflow" });

    // The controller primes the search from the first stored workflow. Wait for
    // that committed UI state before replacing the query so its initial read
    // cannot overwrite the user's selection.
    await expect(workflowSearch).not.toHaveValue("");
    await expect(selectedWorkflow).toBeVisible();

    await workflowSearch.fill("planning-only");
    const workflowChoices = page.getByRole("list", { name: "Workflow choices" });
    await expect(workflowChoices).toBeVisible();
    await workflowChoices.getByRole("button", { name: /planning-only/ }).click();
    await expect(selectedWorkflow).toContainText("planning-only");

    await page.getByLabel("Task key").fill("real-backend-browser-smoke");
    await page.getByLabel("Title").fill("Real backend browser smoke");
    await page
        .getByLabel("Summary")
        .fill("Prove the packaged console against disposable controller truth.");

    const startResponsePromise = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === "POST" && url.pathname === "/tasks/start";
    });
    await page.getByRole("button", { exact: true, name: "Start Task" }).click();
    const startResponse = await startResponsePromise;

    expect(startResponse.status()).toBe(200);
    await expect(page.getByText("Task launch committed")).toBeVisible();
    return (await startResponse.json()) as TaskStartResponse;
}

async function waitForCurrentDispatch(
    request: APIRequestContext,
    taskId: string,
): Promise<RuntimeFlowRead> {
    await expect
        .poll(
            async () => {
                const response = await request.get(`/control/tasks/${encodeURIComponent(taskId)}`);
                expect(response.status()).toBe(200);
                const currentFlow = (await response.json()) as RuntimeFlowRead;
                return currentFlow.current_dispatch?.status ?? null;
            },
            { timeout: 15_000 },
        )
        .toMatch(/^(open|starting)$/);

    const response = await request.get(`/control/tasks/${encodeURIComponent(taskId)}`);
    expect(response.status()).toBe(200);
    return (await response.json()) as RuntimeFlowRead;
}

async function proveLocalAdmission(
    request: APIRequestContext,
    startedTask: TaskStartResponse,
    baseURL: string,
): Promise<void> {
    const forgedHost = await request.get("/healthz", {
        headers: { Host: "forged.example" },
    });
    const forgedOrigin = await request.post("/tasks/start", {
        data: {},
        headers: { Origin: "http://forged.example" },
    });
    const exactTaskRead = await request.get(
        `/control/tasks/${encodeURIComponent(startedTask.task_id)}`,
        { headers: { Origin: baseURL } },
    );

    expect(forgedHost.status()).toBe(400);
    expect(forgedOrigin.status()).toBe(403);
    expect(exactTaskRead.status()).toBe(200);
}

async function proveCursorResetAndReconnect({
    page,
    request,
    runningFlow,
}: {
    readonly page: Page;
    readonly request: APIRequestContext;
    readonly runningFlow: RuntimeFlowRead;
}): Promise<void> {
    const taskPath = `/control/tasks/${encodeURIComponent(runningFlow.task_id)}`;
    const resetResponse = await request.get(`${taskPath}/events/stream`, {
        params: { cursor: "missing-real-browser-cursor" },
    });
    expect(resetResponse.status()).toBe(410);
    expect(((await resetResponse.json()) as { readonly code: string }).code).toBe(
        "cursor_reset_required",
    );

    const snapshotResponse = await request.get(`${taskPath}/snapshot`);
    expect(snapshotResponse.status()).toBe(200);
    const snapshot =
        (await snapshotResponse.json()) as components["schemas"]["OperatorFlowSnapshotResponse"];
    const streamHeadEventId = snapshot.stream_head_event_id;
    expect(streamHeadEventId).toBeTruthy();
    if (!streamHeadEventId) {
        throw new Error("Task snapshot did not include an event-stream head");
    }

    const pauseEventPromise = readNextTaskEvent(
        page,
        runningFlow.task_id,
        streamHeadEventId,
        "task_paused",
    );
    const pauseResponse = await request.post(`${taskPath}/pause`, {
        data: controlGuard(runningFlow),
        headers: { Origin: page.url().replace(/\/tasks\/.+$/, "") },
    });
    expect(pauseResponse.status()).toBe(200);
    const pauseEvent = await pauseEventPromise;

    const pausedFlowResponse = await request.get(taskPath);
    const pausedFlow = (await pausedFlowResponse.json()) as RuntimeFlowRead;
    const cancelEventPromise = readNextTaskEvent(
        page,
        runningFlow.task_id,
        pauseEvent.event_id,
        "task_cancelled",
    );
    const cancelResponse = await request.post(`${taskPath}/cancel`, {
        data: controlGuard(pausedFlow),
        headers: { Origin: page.url().replace(/\/tasks\/.+$/, "") },
    });
    expect(cancelResponse.status()).toBe(200);
    const cancelEvent = await cancelEventPromise;

    expect(cancelEvent.event_seq).toBeGreaterThan(pauseEvent.event_seq);
}

function controlGuard(flow: RuntimeFlowRead): {
    readonly expected_active_flow_revision_id: string;
    readonly expected_control_revision: number;
} {
    return {
        expected_active_flow_revision_id: flow.active_flow_revision_id,
        expected_control_revision: flow.control_revision,
    };
}

async function readNextTaskEvent(
    page: Page,
    taskId: string,
    cursor: string | null,
    eventType: TaskEventRecord["event_type"],
): Promise<TaskEventRecord> {
    return page.evaluate(
        async ({ cursorValue, expectedEventType, selectedTaskId }) => {
            const url = new URL(
                `/control/tasks/${encodeURIComponent(selectedTaskId)}/events/stream`,
                window.location.origin,
            );
            if (cursorValue !== null) {
                url.searchParams.set("cursor", cursorValue);
            }

            const abortController = new AbortController();
            const timeoutId = window.setTimeout(() => {
                abortController.abort();
            }, 15_000);
            try {
                const response = await fetch(url, {
                    headers: { Accept: "text/event-stream" },
                    signal: abortController.signal,
                });
                if (!response.ok || response.body === null) {
                    throw new Error(`Event stream failed with HTTP ${String(response.status)}`);
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let bufferedText = "";
                while (!abortController.signal.aborted) {
                    const { done, value } = await reader.read();
                    if (done) {
                        throw new Error("Event stream closed before the expected event");
                    }
                    bufferedText += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
                    let frameEnd = bufferedText.indexOf("\n\n");
                    while (frameEnd >= 0) {
                        const frame = bufferedText.slice(0, frameEnd);
                        bufferedText = bufferedText.slice(frameEnd + 2);
                        const data = frame
                            .split("\n")
                            .filter((line) => line.startsWith("data: "))
                            .map((line) => line.slice(6))
                            .join("\n");
                        if (data !== "") {
                            const event = JSON.parse(data) as { readonly event_type?: string };
                            if (event.event_type === expectedEventType) {
                                await reader.cancel();
                                return event;
                            }
                        }
                        frameEnd = bufferedText.indexOf("\n\n");
                    }
                }
                throw new Error("Event stream timed out before the expected event");
            } finally {
                window.clearTimeout(timeoutId);
            }
        },
        {
            cursorValue: cursor,
            expectedEventType: eventType,
            selectedTaskId: taskId,
        },
    ) as Promise<TaskEventRecord>;
}

async function proveNoBrowserCredentialBootstrap(
    page: Page,
    request: APIRequestContext,
    observedRequests: readonly Request[],
): Promise<void> {
    const runtimeConfigResponse = await request.get("/console/config");
    const runtimeConfig = (await runtimeConfigResponse.json()) as Record<string, unknown>;
    const browserState = await page.evaluate(async () => ({
        localStorageKeys: Object.keys(window.localStorage),
        serviceWorkerCount: (await navigator.serviceWorker.getRegistrations()).length,
        sessionStorageKeys: Object.keys(window.sessionStorage),
    }));

    expect(runtimeConfigResponse.status()).toBe(200);
    expect(Object.keys(runtimeConfig)).toEqual(["apiBaseUrl"]);
    expect(browserState).toEqual({
        localStorageKeys: [],
        serviceWorkerCount: 0,
        sessionStorageKeys: [],
    });
    expect(
        observedRequests.some((observedRequest) =>
            Object.keys(observedRequest.headers()).includes("x-autoclaw-api-key"),
        ),
    ).toBe(false);
}
