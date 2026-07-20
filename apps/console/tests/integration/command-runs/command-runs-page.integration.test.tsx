import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../src/api/generated/openapi";
import { CommandRunsPage } from "../../../src/features/command-runs/CommandRunsPage";
import {
    createOperationFailureBody,
    TEST_API_BASE_URL,
    createRuntimeFlowRead,
    createTaskEventRecord,
    createTaskEventStreamFrame,
} from "../../fixtures/console-api";
import { installTestConsoleConfig } from "../../fixtures/console-config";
import {
    COMMAND_RUN_TASK_ID,
    createCommandRunDetail,
    createCommandRunDetailMap,
    createCommandRunLogRead,
    createCommandRunPageList,
    createCommandRunSecondPage,
} from "../../fixtures/command-runs";

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

describe("CommandRunsPage", () => {
    it("renders every state and keeps logs hidden until requested", async () => {
        mockCommandRuns();
        const user = userEvent.setup();

        renderCommandRunsPage();

        expect(
            await screen.findByRole("heading", { name: "Refresh runtime route copy" }),
        ).toBeVisible();
        expect(screen.getByText("Command Runs")).toBeVisible();
        expect(screen.getByText("Pending start")).toBeVisible();
        expect(screen.getByText("Running")).toBeVisible();
        expect(screen.getByText("Cancel requested")).toBeVisible();
        expect(screen.getByText("Succeeded")).toBeVisible();
        expect(screen.getByText("Failed")).toBeVisible();
        expect(screen.getByText("Timed out")).toBeVisible();
        expect(screen.getByText("Cancelled")).toBeVisible();
        expect(screen.getByText("Abandoned")).toBeVisible();
        expect(screen.queryByText(/continuation context missing terminal/)).not.toBeInTheDocument();

        await user.click(screen.getByText("Check prompt continuation rendering."));

        expect(await screen.findByText("Result")).toBeVisible();
        expect(screen.getByText("Command")).toBeVisible();
        expect(screen.getByText("Timing")).toBeVisible();
        expect(screen.getByText("Provenance")).toBeVisible();
        expect(screen.getByText("Log access")).toBeVisible();
        expect(screen.getByText("Failed")).toBeVisible();
        expect(screen.getAllByText("1").length).toBeGreaterThan(0);
        expect(screen.getByText("Expected outputs")).toBeVisible();
        expect(screen.getByText("tmp/pytest-command-run.txt")).toBeVisible();
        expect(screen.getByText("Source dispatch")).toBeVisible();
        expect(screen.getByText("Ownership revision")).toBeVisible();
        expect(screen.queryByText(/continuation context missing terminal/)).not.toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: "View logs" }));

        expect(await screen.findByText(/continuation context missing terminal/)).toBeVisible();
        await user.click(screen.getByRole("button", { name: "Hide logs" }));
        expect(screen.queryByText(/continuation context missing terminal/)).not.toBeInTheDocument();

        await user.click(screen.getByText("Inspect a command whose process ownership was lost."));
        expect(await screen.findByText("command_ownership_lost")).toBeVisible();
        expect(
            screen.getByText(/does not prove the operating-system process exited/),
        ).toBeVisible();
    });

    it("loads more rows and keeps cancel only on cancellable states", async () => {
        mockCommandRuns();
        const user = userEvent.setup();

        renderCommandRunsPage();

        await screen.findByText("Run focused runtime route tests.");
        expect(screen.getAllByRole("button", { name: "Cancel" })).toHaveLength(2);
        expect(screen.getByText("Cancel request accepted.")).toBeVisible();

        await user.click(screen.getByRole("button", { name: "Load more" }));
        expect(await screen.findByText("Check generated OpenAPI drift.")).toBeVisible();
    });

    it("surfaces stale cancel errors near the cancel action", async () => {
        mockCommandRuns({
            cancelStatus: 409,
            cancelBody: createOperationFailureBody({
                code: "conflict",
                retryable: true,
                summary: "The command run was already updated by the controller.",
                suggested_next_step: "Reread command-run truth before retrying cancel.",
            }),
        });
        const user = userEvent.setup();

        renderCommandRunsPage();

        await user.click((await screen.findAllByRole("button", { name: "Cancel" }))[0]);

        expect(await screen.findByText("Cancel state changed")).toBeVisible();
        expect(
            screen.getByText("The command run was already updated by the controller."),
        ).toBeVisible();
        expect(screen.getByText("Reread command-run truth before retrying cancel.")).toBeVisible();
    });

    it("anchors source reads to the snapshot head before supervising stream refresh hints", async () => {
        const readOrder: string[] = [];
        const streamRequests: URL[] = [];
        const task = createRuntimeFlowRead({
            task_id: COMMAND_RUN_TASK_ID,
            task_title: "Refresh runtime route copy",
        });
        server.use(
            http.get("*/control/tasks/:taskId/snapshot", () => {
                readOrder.push("snapshot");
                return HttpResponse.json({
                    current_paths: [],
                    flow: task,
                    stream_head_event_id: "evt-command-run-anchor",
                    top_actionable_items: [],
                } satisfies components["schemas"]["OperatorFlowSnapshotResponse"]);
            }),
            http.get("*/control/tasks/:taskId/command-runs", () => {
                readOrder.push("command-runs");
                return HttpResponse.json(createCommandRunPageList());
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

        renderCommandRunsPage();

        expect(
            await screen.findByRole("heading", { name: "Refresh runtime route copy" }),
        ).toBeVisible();
        expect(readOrder[0]).toBe("snapshot");
        expect(readOrder).toEqual(expect.arrayContaining(["command-runs", "task"]));
        await waitFor(() => {
            expect(streamRequests.length).toBeGreaterThanOrEqual(2);
        });
        expect(streamRequests[0]?.searchParams.get("cursor")).toBe("evt-command-run-anchor");
        expect(streamRequests[1]?.searchParams.get("cursor")).toBe("evt-command-run-anchor");
    });

    it("rereads expanded command detail after a command source event", async () => {
        const user = userEvent.setup();
        const allowSourceEvent = createDeferred();
        const detailByRunId = createCommandRunDetailMap();
        const terminalDetail = createCommandRunDetail("run-running", {
            ended_at: "2026-06-29T14:28:00Z",
            state: "succeeded",
            successor_dispatch_id: "dispatch-run-running-successor",
            terminal_result: {
                ended_at: "2026-06-29T14:28:00Z",
                exit_code: 0,
                failure_code: null,
                started_at: "2026-06-29T14:20:00Z",
                state: "succeeded",
                stderr_log_ref: "outputs/command-runs/run-running.stderr.log",
                stdout_log_ref: "outputs/command-runs/run-running.stdout.log",
                summary: "Refreshed selected command detail.",
                terminal_actor_ref: null,
                terminal_event_source: "process_owner",
            },
        });
        const sourceEvent = {
            ...createTaskEventRecord({
                event_id: "evt-command-run-succeeded",
                event_seq: 2,
                task_id: COMMAND_RUN_TASK_ID,
            }),
            event_type: "command_run_succeeded",
            payload: {
                ended_at: "2026-06-29T14:28:00Z",
                exit_code: 0,
                failure_code: null,
                log_refs: ["outputs/command-runs/run-running.log"],
                ownership_revision: 1,
                run_id: "run-running",
                source_dispatch_id: "dispatch-run-running",
                started_at: "2026-06-29T14:20:00Z",
                state: "succeeded",
                summary: "Refreshed selected command detail.",
            },
        } satisfies components["schemas"]["TaskEventRecord"];
        let detailReads = 0;
        let streamReads = 0;
        mockCommandRuns();
        server.use(
            http.get("*/control/tasks/:taskId/command-runs/:runId", ({ params }) => {
                const runId = String(params.runId);
                detailReads += 1;
                if (runId === "run-running" && detailReads > 1) {
                    return HttpResponse.json(terminalDetail);
                }
                return HttpResponse.json(detailByRunId[runId] ?? createCommandRunDetail(runId));
            }),
            http.get("*/control/tasks/:taskId/events/stream", async () => {
                streamReads += 1;
                if (streamReads > 1) {
                    return new HttpResponse("", {
                        headers: { "Content-Type": "text/event-stream" },
                    });
                }
                await allowSourceEvent.promise;
                return new HttpResponse(createTaskEventStreamFrame(sourceEvent), {
                    headers: { "Content-Type": "text/event-stream" },
                });
            }),
        );

        renderCommandRunsPage();

        await user.click(await screen.findByText("Verify command-run runner behavior."));
        expect(await screen.findByText("Command produced output.")).toBeVisible();
        allowSourceEvent.resolve();

        expect(await screen.findByText("Refreshed selected command detail.")).toBeVisible();
        expect(detailReads).toBeGreaterThanOrEqual(2);
    });

    it("keeps a hidden log closed when its exact read finishes", async () => {
        const user = userEvent.setup();
        const allowLogRead = createDeferred();
        mockCommandRuns();
        server.use(
            http.get("*/control/tasks/:taskId/command-runs/:runId/log", async ({ params }) => {
                await allowLogRead.promise;
                return HttpResponse.json(
                    createCommandRunLogRead(String(params.runId ?? "run-failed")),
                );
            }),
        );

        renderCommandRunsPage();

        await user.click(await screen.findByText("Check prompt continuation rendering."));
        await user.click(await screen.findByRole("button", { name: "View logs" }));
        expect(await screen.findByText("Loading logs")).toBeVisible();
        await user.click(screen.getByRole("button", { name: "Hide logs" }));
        allowLogRead.resolve();

        await waitFor(() => {
            expect(screen.getByRole("button", { name: "View logs" })).toBeVisible();
        });
        expect(screen.queryByText(/continuation context missing terminal/)).not.toBeInTheDocument();
    });

    it("rejects a command log readback for a different log ref", async () => {
        const user = userEvent.setup();
        mockCommandRuns();
        server.use(
            http.get("*/control/tasks/:taskId/command-runs/:runId/log", ({ params }) =>
                HttpResponse.json({
                    ...createCommandRunLogRead(String(params.runId ?? "run-failed")),
                    content: "stale log content",
                    log_ref: "outputs/command-runs/stale.log",
                }),
            ),
        );

        renderCommandRunsPage();

        await user.click(await screen.findByText("Check prompt continuation rendering."));
        await user.click(await screen.findByRole("button", { name: "View logs" }));

        expect(await screen.findByText("Logs could not load")).toBeVisible();
        expect(screen.getByText("The command log changed while it was loading.")).toBeVisible();
        expect(screen.queryByText("stale log content")).not.toBeInTheDocument();
    });

    it("renders missing-log, empty, local-admission, and task-detail navigation states", async () => {
        mockCommandRuns();
        const user = userEvent.setup();

        const { unmount } = renderCommandRunsPage();

        await user.click(await screen.findByText("Retire old proof lane."));
        expect(await screen.findByText("This run does not expose a log ref.")).toBeVisible();
        expect(screen.queryByRole("button", { name: "View logs" })).not.toBeInTheDocument();

        await user.click(screen.getByRole("link", { name: "Open task detail" }));
        expect(await screen.findByTestId("task-detail-target")).toHaveTextContent(
            COMMAND_RUN_TASK_ID,
        );

        unmount();
        cleanup();
        server.resetHandlers();
        server.use(
            ...commandRunTaskHandlers(),
            http.get("*/control/tasks/:taskId/command-runs", () =>
                HttpResponse.json({ items: [], next_cursor: null, task_id: COMMAND_RUN_TASK_ID }),
            ),
        );
        renderCommandRunsPage();
        expect(await screen.findByText("No command runs")).toBeVisible();

        cleanup();
        server.resetHandlers();
        server.use(
            ...commandRunTaskHandlers(),
            http.get("*/control/tasks/:taskId/command-runs", () =>
                HttpResponse.json(
                    createOperationFailureBody({
                        code: "local_admission_denied",
                        retryable: false,
                        summary: "The browser Origin is not allowed by the loopback control plane.",
                        suggested_next_step: "Use the configured loopback console origin.",
                    }),
                    { status: 403 },
                ),
            ),
        );

        renderCommandRunsPage();
        expect(await screen.findByText("Access to Command Runs failed")).toBeVisible();
        expect(
            screen.getByText("The browser Origin is not allowed by the loopback control plane."),
        ).toBeVisible();
    });
});

function renderCommandRunsPage() {
    return render(
        <MemoryRouter initialEntries={[`/tasks/${COMMAND_RUN_TASK_ID}/command-runs`]}>
            <Routes>
                <Route element={<CommandRunsPage />} path="/tasks/:taskId/command-runs" />
                <Route element={<TaskDetailTarget />} path="/tasks/:taskId" />
            </Routes>
        </MemoryRouter>,
    );
}

function mockCommandRuns({
    cancelBody,
    cancelStatus = 200,
}: {
    readonly cancelBody?: unknown;
    readonly cancelStatus?: number;
} = {}) {
    const details = createCommandRunDetailMap();
    server.use(
        ...commandRunTaskHandlers(),
        http.get("*/control/tasks/:taskId/command-runs", ({ request }) => {
            const requestUrl = new URL(request.url);
            const page =
                requestUrl.searchParams.get("cursor") === "cursor-command-runs-page-2"
                    ? createCommandRunSecondPage()
                    : createCommandRunPageList();
            return HttpResponse.json(page);
        }),
        http.get("*/control/tasks/:taskId/command-runs/:runId", ({ params }) =>
            HttpResponse.json(
                details[String(params.runId)] ??
                    createCommandRunDetail(String(params.runId ?? "run-failed")),
            ),
        ),
        http.get("*/control/tasks/:taskId/command-runs/:runId/log", ({ params }) =>
            HttpResponse.json(createCommandRunLogRead(String(params.runId ?? "run-failed"))),
        ),
        http.post("*/control/tasks/:taskId/command-runs/:runId/cancel", ({ params }) => {
            if (cancelBody !== undefined) {
                return HttpResponse.json(cancelBody, { status: cancelStatus });
            }

            return HttpResponse.json({
                run: {
                    ...createCommandRunPageList().items[1],
                    run_id: String(params.runId ?? "run-running"),
                    state: "cancellation_requested",
                    summary: "Cancel request accepted.",
                },
                task_id: COMMAND_RUN_TASK_ID,
            } satisfies components["schemas"]["CommandRunCancelResponse"]);
        }),
    );
}

function commandRunTaskHandlers() {
    return [
        http.get("*/control/tasks/:taskId/snapshot", ({ params }) => {
            const task = createRuntimeFlowRead({
                task_id: String(params.taskId ?? COMMAND_RUN_TASK_ID),
                task_title: "Refresh runtime route copy",
            });
            return HttpResponse.json({
                current_paths: [],
                flow: task,
                stream_head_event_id: "evt-command-run-bootstrap",
                top_actionable_items: [],
            } satisfies components["schemas"]["OperatorFlowSnapshotResponse"]);
        }),
        http.get("*/control/tasks/:taskId", ({ params }) =>
            HttpResponse.json(
                createRuntimeFlowRead({
                    task_id: String(params.taskId ?? COMMAND_RUN_TASK_ID),
                    task_title: "Refresh runtime route copy",
                }),
            ),
        ),
        http.get(
            "*/control/tasks/:taskId/events/stream",
            () => new HttpResponse("", { headers: { "Content-Type": "text/event-stream" } }),
        ),
    ];
}

function TaskDetailTarget() {
    const { taskId } = useParams();

    return <div data-testid="task-detail-target">{taskId}</div>;
}

function createDeferred(): { readonly promise: Promise<void>; readonly resolve: () => void } {
    let resolvePromise!: () => void;
    const promise = new Promise<void>((resolve) => {
        resolvePromise = resolve;
    });
    return { promise, resolve: resolvePromise };
}
