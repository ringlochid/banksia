import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../src/api/generated/openapi";
import { HumanRequestsPage } from "../../../src/features/human-requests/HumanRequestsPage";
import {
    createOperationFailureBody,
    TEST_API_BASE_URL,
    createRuntimeFlowRead,
} from "../../fixtures/console-api";
import { installTestConsoleConfig } from "../../fixtures/console-config";
import {
    HUMAN_REQUEST_TASK_ID,
    createHumanRequestPageList,
    createHumanRequestResolveResponse,
} from "../../fixtures/human-requests";

const server = setupServer();

beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
    vi.stubEnv("VITE_AUTOCLAW_API_BASE_URL", TEST_API_BASE_URL);
    installTestConsoleConfig();
    server.use(...humanRequestTaskHandlers());
});

function humanRequestTaskHandlers() {
    const task = createRuntimeFlowRead({
        task_id: HUMAN_REQUEST_TASK_ID,
        task_title: "Refresh runtime route copy",
    });
    return [
        http.get("*/control/tasks/:taskId/snapshot", () =>
            HttpResponse.json({
                current_paths: [],
                flow: task,
                stream_head_event_id: "evt-human-request-bootstrap",
                top_actionable_items: [],
            } satisfies components["schemas"]["OperatorFlowSnapshotResponse"]),
        ),
        http.get("*/control/tasks/:taskId", () => HttpResponse.json(task)),
        http.get(
            "*/control/tasks/:taskId/events/stream",
            () => new HttpResponse("", { headers: { "Content-Type": "text/event-stream" } }),
        ),
    ];
}

afterEach(() => {
    cleanup();
    server.resetHandlers();
    installTestConsoleConfig();
    vi.unstubAllEnvs();
});

afterAll(() => {
    server.close();
});

describe("HumanRequestsPage", () => {
    it("resolves a multi-item direction request with mapping-shaped responses", async () => {
        const user = userEvent.setup();
        const requestBodies: components["schemas"]["HumanRequestResolveRequest"][] = [];
        mockHumanRequests({ requestBodies });

        renderHumanRequestsPage();

        expect(
            await screen.findByRole("heading", { name: "Refresh runtime route copy" }),
        ).toBeVisible();
        expect((await screen.findAllByText("Choose due handling")).length).toBeGreaterThan(0);
        expect(screen.getByText("Approve generated file writes")).toBeVisible();
        expect(screen.getByText("Provide handoff fields")).toBeVisible();
        expect(screen.getByText("Review validation result")).toBeVisible();
        expect(screen.getByText("Validation evidence accepted")).toBeVisible();
        expect(
            screen.getByText(
                "Answer the active item, then resolve the request when the controller can continue without guessing.",
            ),
        ).toBeVisible();

        await user.click(screen.getByLabelText(/Use due fallback/));
        await user.click(screen.getByRole("button", { name: "Next" }));
        await user.click(screen.getByLabelText(/Whole task check/));
        await user.click(screen.getByRole("button", { name: "Next" }));
        await user.click(screen.getByLabelText(/Answer only/));
        await user.click(screen.getByRole("button", { name: "Previous" }));
        await user.click(screen.getByRole("button", { name: "Previous" }));

        expect(screen.getByLabelText(/Use due fallback/)).toBeChecked();

        await user.click(getWorkbenchResolveButton());

        expect(await screen.findByText("Resolved request")).toBeVisible();
        await waitFor(() => {
            expect(requestBodies).toHaveLength(1);
        });
        expect(requestBodies[0]).toEqual({
            item_responses: {
                due_handling: "use-fallback",
                next_context: "answer-only",
                next_scope: "whole-task",
            },
        });
    });

    it("validates schema-backed input and submits the item response value", async () => {
        const user = userEvent.setup();
        const requestBodies: components["schemas"]["HumanRequestResolveRequest"][] = [];
        mockHumanRequests({ requestBodies });

        renderHumanRequestsPage();

        await user.click(
            within(await screen.findByLabelText("Human request queue")).getByText(
                "Provide handoff fields",
            ),
        );
        await user.click(getWorkbenchResolveButton());

        expect(await screen.findByText("Target node is required.")).toBeVisible();
        expect(screen.getByText("Expected output is required.")).toBeVisible();

        await user.type(screen.getByLabelText("Target node"), "release_gate");
        await user.type(screen.getByLabelText("Expected output"), "validated artifact list");
        await user.type(
            screen.getByLabelText("Constraint"),
            "Use controller-owned request data only.",
        );
        await user.click(getWorkbenchResolveButton());

        await waitFor(() => {
            expect(requestBodies).toHaveLength(1);
        });
        expect(requestBodies[0]?.item_responses.handoff_payload).toEqual({
            constraint: "Use controller-owned request data only.",
            expected_output: "validated artifact list",
            target_node: "release_gate",
        });
        expect(await screen.findByText("Resolved request")).toBeVisible();
        expect(await screen.findByText(/"target_node": "release_gate"/)).toBeVisible();
        expect(screen.getByText(/"expected_output": "validated artifact list"/)).toBeVisible();
    });

    it("renders terminal readback and keeps approval rejection as an answer option", async () => {
        const user = userEvent.setup();
        mockHumanRequests();

        renderHumanRequestsPage();

        await user.click(await screen.findByText("Validation evidence accepted"));
        expect(screen.getByText("Resolved request")).toBeVisible();
        expect(screen.getByText("Reviewer accepted the validation evidence.")).toBeVisible();

        await user.click(screen.getByText("Write approval withdrawn"));
        expect(screen.getByText("Cancelled request")).toBeVisible();

        await user.click(screen.getByText("Approve generated file writes"));
        expect(screen.getByLabelText(/Reject for now/)).toBeVisible();
        expect(screen.getAllByText("approval").length).toBeGreaterThan(0);
        expect(
            within(screen.getByLabelText("Human request queue")).getByText(
                "Write approval withdrawn",
            ),
        ).toBeVisible();
    });

    it("surfaces stale resolution conflicts while preserving item context", async () => {
        const user = userEvent.setup();
        const readLog: number[] = [];
        mockHumanRequests({
            readLog,
            resolveStatus: 409,
            resolveBody: createOperationFailureBody({
                code: "conflict",
                retryable: true,
                summary: "The request was already resolved by another operator.",
                suggested_next_step: "Reread current human-request truth before retrying.",
            }),
        });

        renderHumanRequestsPage();

        await user.click(await screen.findByText("Approve generated file writes"));
        await user.click(screen.getByLabelText(/Reject for now/));
        await user.click(getWorkbenchResolveButton());

        expect(await screen.findByText("Request resolved elsewhere")).toBeVisible();
        expect(
            screen.getByText("The request was already resolved by another operator."),
        ).toBeVisible();
        expect(
            screen.getByText("Reread current human-request truth before retrying."),
        ).toBeVisible();

        await waitFor(() => {
            expect(readLog).toHaveLength(2);
        });
        expect(screen.getByLabelText(/Reject for now/)).toBeChecked();
    });

    it("anchors source reads to the snapshot head before supervising stream refresh hints", async () => {
        const readOrder: string[] = [];
        const streamRequests: URL[] = [];
        const task = createRuntimeFlowRead({
            task_id: HUMAN_REQUEST_TASK_ID,
            task_title: "Refresh runtime route copy",
        });
        const requestList = createHumanRequestPageList();
        server.use(
            http.get("*/control/tasks/:taskId/snapshot", () => {
                readOrder.push("snapshot");
                return HttpResponse.json({
                    current_paths: [],
                    flow: task,
                    stream_head_event_id: "evt-human-request-anchor",
                    top_actionable_items: [],
                } satisfies components["schemas"]["OperatorFlowSnapshotResponse"]);
            }),
            http.get("*/control/tasks/:taskId/human-requests", () => {
                readOrder.push("human-requests");
                return HttpResponse.json(requestList);
            }),
            http.get("*/control/tasks/:taskId", () => {
                readOrder.push("task");
                return HttpResponse.json(task);
            }),
            http.get("*/control/tasks/:taskId/events/stream", ({ request }) => {
                streamRequests.push(new URL(request.url));
                return new HttpResponse("", { headers: { "Content-Type": "text/event-stream" } });
            }),
        );

        renderHumanRequestsPage();

        expect(
            await screen.findByRole("heading", { name: "Refresh runtime route copy" }),
        ).toBeVisible();
        expect(readOrder[0]).toBe("snapshot");
        expect(readOrder).toEqual(expect.arrayContaining(["human-requests", "task"]));
        await waitFor(() => {
            expect(streamRequests.length).toBeGreaterThanOrEqual(2);
        });
        expect(streamRequests[0]?.searchParams.get("cursor")).toBe("evt-human-request-anchor");
        expect(streamRequests[1]?.searchParams.get("cursor")).toBe("evt-human-request-anchor");
    });

    it("renders empty, auth, and task-detail navigation states", async () => {
        server.use(
            http.get("*/control/tasks/:taskId/human-requests", () =>
                HttpResponse.json({ items: [], task_id: HUMAN_REQUEST_TASK_ID }),
            ),
        );

        const { unmount } = renderHumanRequestsPage();
        expect(await screen.findByText("No human requests")).toBeVisible();
        expect(screen.queryByText("Empty")).not.toBeInTheDocument();
        const taskDetailLinks = screen.getAllByRole("link", { name: "Open task detail" });
        expect(taskDetailLinks).toHaveLength(2);
        await userEvent.click(taskDetailLinks[0]);
        expect(await screen.findByTestId("task-detail-target")).toHaveTextContent(
            HUMAN_REQUEST_TASK_ID,
        );

        unmount();
        cleanup();
        server.resetHandlers();
        server.use(
            ...humanRequestTaskHandlers(),
            http.get("*/control/tasks/:taskId/human-requests", () =>
                HttpResponse.json(
                    createOperationFailureBody({
                        code: "illegal_caller",
                        retryable: false,
                        summary: "The unsafe request Origin is not allowed.",
                        suggested_next_step: "Use the packaged same-origin loopback console.",
                    }),
                    { status: 401 },
                ),
            ),
        );

        renderHumanRequestsPage();
        expect(await screen.findByText("Access to Human Requests failed")).toBeVisible();
        expect(screen.getByText("The unsafe request Origin is not allowed.")).toBeVisible();
    });

    it("renders non-auth read errors as read failures", async () => {
        server.use(
            http.get("*/control/tasks/:taskId/human-requests", () =>
                HttpResponse.json(
                    createOperationFailureBody({
                        code: "internal_error",
                        retryable: true,
                        summary: "The human-request read model is temporarily unavailable.",
                        suggested_next_step: "Retry after the controller read model recovers.",
                    }),
                    { status: 500 },
                ),
            ),
        );

        renderHumanRequestsPage();

        expect(await screen.findByText("Human Requests could not load")).toBeVisible();
        expect(
            screen.getByText("The human-request read model is temporarily unavailable."),
        ).toBeVisible();
    });
});

function renderHumanRequestsPage() {
    return render(
        <MemoryRouter initialEntries={[`/tasks/${HUMAN_REQUEST_TASK_ID}/human-requests`]}>
            <Routes>
                <Route element={<HumanRequestsPage />} path="/tasks/:taskId/human-requests" />
                <Route element={<TaskDetailTarget />} path="/tasks/:taskId" />
            </Routes>
        </MemoryRouter>,
    );
}

function getWorkbenchResolveButton(): HTMLElement {
    const buttons = screen.getAllByRole("button", { name: "Resolve" });
    return buttons[buttons.length - 1];
}

function mockHumanRequests({
    readLog = [],
    requestBodies = [],
    resolveBody,
    resolveStatus = 200,
}: {
    readonly readLog?: number[];
    readonly requestBodies?: components["schemas"]["HumanRequestResolveRequest"][];
    readonly resolveBody?: unknown;
    readonly resolveStatus?: number;
} = {}) {
    const list = createHumanRequestPageList();
    server.use(
        http.get("*/control/tasks/:taskId/human-requests", () => {
            readLog.push(Date.now());
            return HttpResponse.json(list);
        }),
        http.post(
            "*/control/tasks/:taskId/human-requests/:requestId/resolve",
            async ({ params, request }) => {
                const body =
                    (await request.json()) as components["schemas"]["HumanRequestResolveRequest"];
                requestBodies.push(body);
                if (resolveBody !== undefined) {
                    return HttpResponse.json(resolveBody, { status: resolveStatus });
                }

                const requestRead = list.items.find(
                    (item) => item.request.request_id === params.requestId,
                );
                return HttpResponse.json(
                    createHumanRequestResolveResponse(
                        requestRead?.request ?? list.items[0].request,
                        body.item_responses,
                    ),
                );
            },
        ),
    );
}

function TaskDetailTarget() {
    const { taskId } = useParams();

    return <div data-testid="task-detail-target">{taskId}</div>;
}
