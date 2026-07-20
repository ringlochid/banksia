import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
    createMemoryRouter,
    MemoryRouter,
    Route,
    RouterProvider,
    Routes,
    useLocation,
} from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../src/api/generated/openapi";
import { TaskDetailPage } from "../../../src/features/task-detail/TaskDetailPage";
import { createConsoleApiHandlers } from "../../../src/mocks/handlers";
import { TEST_API_BASE_URL, createOperationFailureBody } from "../../fixtures/console-api";
import {
    TASK_DETAIL_STREAM_HEAD,
    TASK_DETAIL_TASK_ID,
    createTaskDetailEventRecords,
    createTaskDetailMockScenario,
} from "../../fixtures/task-detail";
import { installTestConsoleConfig } from "../../fixtures/console-config";

const server = setupServer();

beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
    vi.stubEnv("VITE_AUTOCLAW_API_BASE_URL", TEST_API_BASE_URL);
    installTestConsoleConfig();
});

afterEach(() => {
    cleanup();
    server.resetHandlers();
    installTestConsoleConfig();
    vi.unstubAllEnvs();
});

afterAll(() => {
    server.close();
});

describe("TaskDetailPage", () => {
    it("bootstraps REST state, backfills through the stream head, merges live SSE, and opens selected detail", async () => {
        const user = userEvent.setup();
        const scenario = createTaskDetailMockScenario();
        const backfillFirstPage = scenario.taskEvents.items.slice(0, 4);
        const backfillSecondPage = [
            scenario.taskEvents.items[3],
            ...scenario.taskEvents.items.slice(4),
        ];
        const seenEventBackfills: URL[] = [];
        const seenStreamUrls: URL[] = [];
        server.use(...createConsoleApiHandlers(scenario));
        server.use(
            http.get("*/control/tasks/:taskId/events", ({ request }) => {
                const requestUrl = new URL(request.url);
                seenEventBackfills.push(requestUrl);
                const cursor = requestUrl.searchParams.get("cursor");
                return HttpResponse.json({
                    ...scenario.taskEvents,
                    items: cursor === "events-page-2" ? backfillSecondPage : backfillFirstPage,
                    next_cursor: cursor === "events-page-2" ? null : "events-page-2",
                } satisfies components["schemas"]["TaskEventListResponse"]);
            }),
            http.get("*/control/tasks/:taskId/events/stream", ({ request }) => {
                seenStreamUrls.push(new URL(request.url));
                return new HttpResponse(
                    scenario.taskEventStream.chunksByCursor[TASK_DETAIL_STREAM_HEAD].join(""),
                    { headers: { "Content-Type": "text/event-stream" } },
                );
            }),
        );

        renderTaskDetailPage();

        expect(screen.getByRole("status", { name: "Loading Task Detail" })).toBeVisible();
        expect(screen.getByTestId("task-detail-loading-graph-canvas")).toBeEmptyDOMElement();
        expect(
            await screen.findByRole("heading", { name: "Refresh runtime route copy" }),
        ).toBeVisible();
        expect(screen.getByText("Execution graph")).toBeVisible();
        const runtimeSummary = screen.getByRole("region", {
            name: "Current controller runtime",
        });
        expect(within(runtimeSummary).getByText("Open dispatch")).toBeVisible();
        expect(
            within(runtimeSummary).getAllByText("dispatch-task-detail-build-current").length,
        ).toBeGreaterThan(0);
        expect(within(runtimeSummary).getByText("Experimental")).toBeVisible();
        expect(within(runtimeSummary).getByText("Provider-native access")).toBeVisible();
        expect(within(runtimeSummary).getByText("Network access")).toBeVisible();
        expect(within(runtimeSummary).getByText("Revision 2")).toBeVisible();
        expect(
            screen.getByLabelText("Execution graph").querySelectorAll('path[stroke="#c4a4f7"]'),
        ).toHaveLength(0);
        expect(screen.getByText("Events")).toBeVisible();
        expect(screen.queryByText("Approve the last copy trim")).not.toBeInTheDocument();
        expect(screen.queryByText("Verify command-run runner behavior.")).not.toBeInTheDocument();
        expect(seenEventBackfills[0]?.searchParams.get("through_event_id")).toBe(
            TASK_DETAIL_STREAM_HEAD,
        );
        expect(seenEventBackfills[1]?.searchParams.get("through_event_id")).toBe(
            TASK_DETAIL_STREAM_HEAD,
        );
        expect(seenEventBackfills.slice(0, 2).map((url) => url.searchParams.get("cursor"))).toEqual(
            [null, "events-page-2"],
        );
        expect(seenStreamUrls[0]?.searchParams.get("cursor")).toBe(TASK_DETAIL_STREAM_HEAD);

        await waitFor(() => {
            expect(seenStreamUrls.length).toBeGreaterThanOrEqual(2);
        });
        expect(seenStreamUrls[1]?.searchParams.get("cursor")).toBe(
            lastStreamEventId(scenario.taskEventStream.chunks),
        );

        expect(await screen.findByText("Task cancelled")).toBeVisible();
        expect(screen.queryByText("Provider event normalized")).not.toBeInTheDocument();
        expect(screen.queryByText("Provider resolution recorded")).not.toBeInTheDocument();
        expect(screen.getByText("Dispatch opened")).toBeVisible();
        expect(screen.getAllByText("Checkpoint recorded").length).toBeGreaterThan(0);
        expect(screen.getByRole("button", { name: /Task cancelled/i })).toHaveAttribute(
            "aria-pressed",
            "true",
        );

        await user.click(screen.getByRole("button", { name: /Checkpoint recorded/i }));
        const openDetailButton = screen.getByRole("button", { name: /Open detail/i });
        await user.click(openDetailButton);

        const dialog = await screen.findByRole("dialog");
        await waitFor(() => {
            expect(within(dialog).getByRole("button", { name: "Close node detail" })).toHaveFocus();
        });
        await user.tab({ shift: true });
        expect(within(dialog).getByRole("link", { name: "Open Command Runs" })).toHaveFocus();
        await user.tab();
        expect(within(dialog).getByRole("button", { name: "Close node detail" })).toHaveFocus();
        expect(
            within(dialog).getByRole("heading", { level: 2, name: "Runtime page contract" }),
        ).toBeVisible();
        expect(
            within(dialog).getByText("Approval is needed for the last copy trim."),
        ).toBeVisible();
        expect(within(dialog).getByText("Verify command-run runner behavior.")).toBeVisible();
        expect(within(dialog).getByRole("tab", { name: "Overview" })).toHaveAttribute(
            "aria-selected",
            "true",
        );
        await user.click(within(dialog).getByRole("tab", { name: "Checkpoint" }));
        expect(within(dialog).getByText("Kind")).toBeVisible();
        expect(within(dialog).getByText("progress")).toBeVisible();
        expect(within(dialog).getByText("Checkpoint recorded.")).toBeVisible();
        await user.click(within(dialog).getByRole("tab", { name: "Artifacts" }));
        expect(within(dialog).getByText("frontend_scope_patch")).toBeVisible();
        await user.click(within(dialog).getByRole("tab", { name: "Trace" }));
        expect(within(dialog).getByRole("tabpanel", { name: "Trace" })).toHaveTextContent(
            "checkpoint_recorded",
        );
        await user.keyboard("{Escape}");
        await waitFor(() => {
            expect(openDetailButton).toHaveFocus();
        });
        expect(await screen.findByText("Event stream disconnected")).toBeVisible();
    });

    it("resets REST state and reconnects when the stream cursor is stale", async () => {
        const scenario = createTaskDetailMockScenario();
        const refreshedStreamHead = "evt-refreshed-stream-head";
        const streamCursors: (string | null)[] = [];
        const allowCursorReset = createDeferred();
        const refreshedBackfill = scenario.taskEvents.items.filter(
            (event) => event.event_type === "checkpoint_recorded",
        );
        let snapshotReads = 0;
        server.use(...createConsoleApiHandlers(scenario));
        server.use(
            http.get("*/control/tasks/:taskId/snapshot", () => {
                snapshotReads += 1;
                return HttpResponse.json({
                    ...scenario.snapshot,
                    stream_head_event_id:
                        snapshotReads === 1 ? TASK_DETAIL_STREAM_HEAD : refreshedStreamHead,
                });
            }),
            http.get("*/control/tasks/:taskId/events", ({ request }) => {
                const throughEventId = new URL(request.url).searchParams.get("through_event_id");
                return HttpResponse.json({
                    ...scenario.taskEvents,
                    items:
                        throughEventId === refreshedStreamHead
                            ? refreshedBackfill
                            : scenario.taskEvents.items,
                    next_cursor: null,
                    through_event_id: throughEventId,
                } satisfies components["schemas"]["TaskEventListResponse"]);
            }),
            http.get("*/control/tasks/:taskId/events/stream", async ({ request }) => {
                const cursor = new URL(request.url).searchParams.get("cursor");
                streamCursors.push(cursor);
                if (cursor === TASK_DETAIL_STREAM_HEAD) {
                    await allowCursorReset.promise;
                    return HttpResponse.json(
                        createOperationFailureBody({
                            code: "cursor_reset_required",
                            retryable: false,
                            summary: "The task-event cursor is stale.",
                            suggested_next_step: "Reread current task truth.",
                        }),
                        { status: 410 },
                    );
                }

                return new HttpResponse(scenario.taskEventStream.chunks.join(""), {
                    headers: { "Content-Type": "text/event-stream" },
                });
            }),
        );

        renderTaskDetailPage();

        expect(await screen.findByText("Task started")).toBeVisible();
        allowCursorReset.resolve();
        expect(await screen.findByText("Stream cursor reset")).toBeVisible();
        expect(await screen.findByText(/current task truth was reread/i)).toBeVisible();
        expect(await screen.findByText("Task cancelled")).toBeVisible();
        expect(screen.queryByText("Task started")).not.toBeInTheDocument();
        expect(snapshotReads).toBeGreaterThanOrEqual(2);
        expect(streamCursors.slice(0, 2)).toEqual([TASK_DETAIL_STREAM_HEAD, refreshedStreamHead]);
    });

    it("resets route-owned state and ignores late reads when navigating between tasks", async () => {
        const user = userEvent.setup();
        const taskBId = "task-runtime-route-copy-second";
        const scenarioA = createTaskDetailMockScenario();
        const scenarioBBase = createTaskDetailMockScenario({
            events: createTaskDetailEventRecords({ taskId: taskBId }),
        });
        const taskB: components["schemas"]["RuntimeFlowRead"] = {
            ...scenarioBBase.taskRead,
            task_id: taskBId,
            task_summary: "Prove task-route identity is isolated.",
            task_title: "Second runtime route task",
        };
        const scenarioB = {
            ...scenarioBBase,
            commandRunList: { ...scenarioBBase.commandRunList, task_id: taskBId },
            humanRequestList: { ...scenarioBBase.humanRequestList, task_id: taskBId },
            snapshot: { ...scenarioBBase.snapshot, flow: taskB },
            taskEvents: { ...scenarioBBase.taskEvents, task_id: taskBId },
            taskRead: taskB,
            trace: { ...scenarioBBase.trace, task_id: taskBId },
        };
        const delayedTaskARefresh = createDeferred();
        let taskASnapshotReads = 0;

        server.use(...createConsoleApiHandlers(scenarioA));
        server.use(
            http.get("*/control/tasks/:taskId/snapshot", async ({ params }) => {
                if (String(params.taskId) !== TASK_DETAIL_TASK_ID) {
                    return HttpResponse.json(scenarioB.snapshot);
                }

                taskASnapshotReads += 1;
                if (taskASnapshotReads > 1) {
                    await delayedTaskARefresh.promise;
                }
                return HttpResponse.json(scenarioA.snapshot);
            }),
        );

        const router = createMemoryRouter(
            [{ element: <TaskDetailPage />, path: "/tasks/:taskId" }],
            { initialEntries: [`/tasks/${TASK_DETAIL_TASK_ID}`] },
        );
        render(<RouterProvider router={router} />);

        expect(
            await screen.findByRole("heading", { name: "Refresh runtime route copy" }),
        ).toBeVisible();
        await user.click(screen.getByRole("button", { name: /Open detail/i }));
        expect(await screen.findByRole("dialog")).toBeVisible();
        await waitFor(() => {
            expect(taskASnapshotReads).toBeGreaterThanOrEqual(2);
        });

        server.use(...createConsoleApiHandlers(scenarioB));
        await act(async () => {
            await router.navigate(`/tasks/${taskBId}`);
        });

        expect(
            await screen.findByRole("heading", { name: "Second runtime route task" }),
        ).toBeVisible();
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        expect(screen.queryByText("Refresh runtime route copy")).not.toBeInTheDocument();

        delayedTaskARefresh.resolve();
        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Second runtime route task" }),
            ).toBeVisible();
        });
    });

    it("renders a starting dispatch with its bounded provider-start retry readback", async () => {
        const scenario = createTaskDetailMockScenario();
        const currentDispatch = scenario.taskRead.current_dispatch;
        if (currentDispatch === null || currentDispatch === undefined) {
            throw new Error("Task Detail fixture must expose a current dispatch");
        }
        const startingTask: components["schemas"]["RuntimeFlowRead"] = {
            ...scenario.taskRead,
            current_dispatch: {
                ...currentDispatch,
                adapter_started_at: null,
                last_node_activity_at: null,
                provider_start: {
                    attempt_count: 3,
                    last_error_code: "provider_unavailable",
                    next_attempt_at: "2026-06-29T14:05:00Z",
                    retry_kind: "definite_failure",
                    revision: 3,
                },
                status: "starting",
                watchdog_due_at: null,
            },
        };
        server.use(
            ...createConsoleApiHandlers({
                ...scenario,
                snapshot: { ...scenario.snapshot, flow: startingTask },
                taskRead: startingTask,
            }),
        );

        renderTaskDetailPage();

        expect(await screen.findByText("Provider start pending")).toBeVisible();
        expect(screen.getByText("Attempt 3 · definite_failure")).toBeVisible();
        expect(screen.getByText("provider_unavailable")).toBeVisible();
        expect(screen.getByText("Next attempt")).toBeVisible();
    });

    it("omits unavailable detail fields instead of rendering placeholders", async () => {
        const user = userEvent.setup();
        const scenario = createTaskDetailMockScenario();
        const trace: components["schemas"]["OperatorFlowTraceResponse"] = {
            ...scenario.trace,
            boundary_history: scenario.trace.boundary_history.map((boundary, index) =>
                index === 0
                    ? {
                          ...boundary,
                          successor_dispatch_id: null,
                      }
                    : boundary,
            ),
        };
        server.use(...createConsoleApiHandlers({ ...scenario, trace }));

        renderTaskDetailPage();

        await screen.findByRole("heading", { name: "Refresh runtime route copy" });
        await screen.findByText("Task cancelled");
        expect(screen.queryByText("not exposed")).not.toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: /Open detail/i }));
        let dialog = await screen.findByRole("dialog");
        await user.click(within(dialog).getByRole("tab", { name: "Checkpoint" }));
        expect(within(dialog).getByText("No selected detail")).toBeVisible();
        expect(within(dialog).queryByText("Task control state changed.")).not.toBeInTheDocument();
        await user.click(within(dialog).getByRole("button", { name: "Close node detail" }));
        await waitFor(() => {
            expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        });

        await user.click(screen.getByRole("button", { name: /Checkpoint recorded/i }));
        await user.click(screen.getByRole("button", { name: /Open detail/i }));
        dialog = await screen.findByRole("dialog");
        await user.click(within(dialog).getByRole("tab", { name: "Checkpoint" }));
        expect(within(dialog).getByText("Checkpoint recorded.")).toBeVisible();
        expect(within(dialog).queryByText("not exposed")).not.toBeInTheDocument();
        expect(within(dialog).queryByText("not exposed")).not.toBeInTheDocument();

        await user.click(within(dialog).getByRole("button", { name: "Close node detail" }));
        await waitFor(() => {
            expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        });

        await user.click(screen.getByRole("button", { name: /Boundary accepted/i }));
        await user.click(screen.getByRole("button", { name: /Open detail/i }));
        dialog = await screen.findByRole("dialog");
        await user.click(within(dialog).getByRole("tab", { name: "Boundary" }));
        expect(within(dialog).getByText("Source dispatch")).toBeVisible();
        expect(within(dialog).queryByText("Successor dispatch")).not.toBeInTheDocument();
        expect(within(dialog).queryByText("not exposed")).not.toBeInTheDocument();
    });

    it("submits guarded task actions and keeps stale action errors near the controls", async () => {
        const user = userEvent.setup();
        const scenario = createTaskDetailMockScenario();
        const actionBodies: components["schemas"]["RuntimeFlowControlRequest"][] = [];
        server.use(...createConsoleApiHandlers(scenario));
        server.use(
            http.post("*/control/tasks/:taskId/pause", async ({ request }) => {
                actionBodies.push(
                    (await request.json()) as components["schemas"]["RuntimeFlowControlRequest"],
                );
                return HttpResponse.json({
                    flow: {
                        ...scenario.taskRead,
                        active_flow_revision_id: "flow-revision-task-detail-2",
                        control_revision: 2,
                        status: "paused",
                    },
                } satisfies components["schemas"]["RuntimeFlowPauseResponse"]);
            }),
            http.post("*/control/tasks/:taskId/continue", async ({ request }) => {
                actionBodies.push(
                    (await request.json()) as components["schemas"]["RuntimeFlowControlRequest"],
                );
                if (actionBodies.length === 2) {
                    return HttpResponse.json(
                        createOperationFailureBody({
                            code: "illegal_state",
                            field_path: null,
                            retryable: false,
                            summary: "The retained continuation cannot be prepared.",
                        }),
                        { status: 409 },
                    );
                }
                return HttpResponse.json(
                    createOperationFailureBody({
                        field_path: "expected_active_flow_revision_id",
                        summary: "The active flow revision is stale.",
                    }),
                    { status: 409 },
                );
            }),
        );

        renderTaskDetailPage();

        await screen.findByRole("heading", { name: "Refresh runtime route copy" });
        expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
        await user.click(screen.getByRole("button", { name: "Pause" }));
        expect(await screen.findByText("paused")).toBeVisible();
        expect(screen.getByRole("button", { name: "Pause" })).toBeDisabled();
        expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
        expect(actionBodies[0]).toEqual({
            expected_active_flow_revision_id: "flow-revision-task-detail-1",
            expected_control_revision: 1,
        });

        await user.click(screen.getByRole("button", { name: "Continue" }));
        expect(await screen.findByText("Action failed")).toBeVisible();
        expect(screen.getByText("The retained continuation cannot be prepared.")).toBeVisible();

        await user.click(screen.getByRole("button", { name: "Continue" }));
        expect(await screen.findByText("Stale action")).toBeVisible();
        expect(screen.getByText("The active flow revision is stale.")).toBeVisible();
        expect(actionBodies[2]).toEqual({
            expected_active_flow_revision_id: "flow-revision-task-detail-2",
            expected_control_revision: 2,
        });
    });

    it("keeps sibling handoffs as task-scoped navigation instead of embedded pages", async () => {
        const user = userEvent.setup();
        const scenario = createTaskDetailMockScenario();
        server.use(...createConsoleApiHandlers(scenario));

        renderTaskDetailPage();

        await screen.findByRole("heading", { name: "Refresh runtime route copy" });
        expect(
            screen.queryByRole("link", { name: /Open Human Requests/i }),
        ).not.toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: /Open detail/i }));
        const dialog = await screen.findByRole("dialog");
        await user.click(within(dialog).getByRole("link", { name: /Open Human Requests/i }));
        expect(await screen.findByTestId("location")).toHaveTextContent(
            `/tasks/${TASK_DETAIL_TASK_ID}/human-requests`,
        );
    });

    it("does not infer a graph when controller graph rows are absent", async () => {
        const scenario = createTaskDetailMockScenario();
        server.use(
            ...createConsoleApiHandlers({
                ...scenario,
                trace: {
                    ...scenario.trace,
                    dependency_edges: [],
                    graph_nodes: [],
                },
            }),
        );

        renderTaskDetailPage();

        expect(await screen.findByText("Execution graph unavailable")).toBeVisible();
        expect(
            screen.getByText(/will not reconstruct them from events or dispatch history/i),
        ).toBeVisible();
    });

    it("keeps continue disabled while a paused task still has an unresolved source", async () => {
        const scenario = createTaskDetailMockScenario({ status: "paused" });
        const taskRead: components["schemas"]["RuntimeFlowRead"] = {
            ...scenario.taskRead,
            current_dispatch: null,
            current_human_request: {
                due_at: "2026-06-29T14:30:00Z",
                kind: "approval",
                opened_at: "2026-06-29T14:00:00Z",
                request_id: "hr-task-detail-approval",
                source_dispatch_id: "dispatch-task-detail-build-current",
                status: "open",
                summary: "Approval is still required.",
            },
            pause_reason: "paused_by_operator",
            waiting_cause: "human_request",
        };
        server.use(
            ...createConsoleApiHandlers({
                ...scenario,
                snapshot: { ...scenario.snapshot, flow: taskRead },
                taskRead,
            }),
        );

        renderTaskDetailPage();

        expect(await screen.findByText("Approval is still required.")).toBeVisible();
        expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    });

    it("renders no-history and read-error states", async () => {
        const noHistoryScenario = createTaskDetailMockScenario({
            events: [],
            streamEvents: [],
            streamHeadEventId: null,
        });
        server.use(...createConsoleApiHandlers(noHistoryScenario));

        const noHistoryView = renderTaskDetailPage();
        expect(await screen.findByText("No event history")).toBeVisible();

        noHistoryView.unmount();
        cleanup();
        server.resetHandlers();
        server.use(
            http.get("*/control/tasks/:taskId", () =>
                HttpResponse.text("Task read failed.", { status: 500 }),
            ),
            http.get("*/control/tasks/:taskId/snapshot", () =>
                HttpResponse.json(noHistoryScenario.snapshot),
            ),
            http.get("*/control/tasks/:taskId/trace", () =>
                HttpResponse.json(noHistoryScenario.trace),
            ),
            http.get("*/control/tasks/:taskId/human-requests", () =>
                HttpResponse.json(noHistoryScenario.humanRequestList),
            ),
            http.get("*/control/tasks/:taskId/command-runs", () =>
                HttpResponse.json(noHistoryScenario.commandRunList),
            ),
        );

        const readErrorView = renderTaskDetailPage();
        expect(await screen.findByText("Task Detail could not load")).toBeVisible();
        expect(
            screen.getByText("The AutoClaw API returned an unexpected error response."),
        ).toBeVisible();

        readErrorView.unmount();
    });
});

function renderTaskDetailPage() {
    return render(
        <MemoryRouter initialEntries={[`/tasks/${TASK_DETAIL_TASK_ID}`]}>
            <Routes>
                <Route element={<TaskDetailPage />} path="/tasks/:taskId" />
                <Route element={<LocationTarget />} path="/tasks/:taskId/human-requests" />
                <Route element={<LocationTarget />} path="/tasks/:taskId/command-runs" />
            </Routes>
        </MemoryRouter>,
    );
}

function LocationTarget() {
    const location = useLocation();

    return <div data-testid="location">{location.pathname}</div>;
}

function lastStreamEventId(chunks: readonly string[]): string | null {
    const matches = [...chunks.join("").matchAll(/^id: (.+)$/gm)];
    return matches.at(-1)?.[1] ?? null;
}

function createDeferred(): { readonly promise: Promise<void>; readonly resolve: () => void } {
    let resolvePromise!: () => void;
    const promise = new Promise<void>((resolve) => {
        resolvePromise = resolve;
    });
    return { promise, resolve: resolvePromise };
}
