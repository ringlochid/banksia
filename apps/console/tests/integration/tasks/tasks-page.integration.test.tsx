import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../src/api/generated/openapi";
import { TasksPage } from "../../../src/features/tasks/TasksPage";
import { createConsoleApiHandlers } from "../../../src/mocks/handlers";
import {
    TEST_API_BASE_URL,
    createConsoleMockScenario,
    createLongRuntimeTaskRow,
    createRuntimeFlowSummary,
    createRuntimeFlowSummaryList,
} from "../../fixtures/console-api";
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

describe("TasksPage", () => {
    it("renders mixed rows, sends query controls, and loads cursor pages", async () => {
        const user = userEvent.setup();
        const seenRequests: URL[] = [];
        const firstPage = createRuntimeFlowSummaryList(
            [
                ...createV2RuntimeTaskRows(),
                createLongRuntimeTaskRow(),
                createRuntimeFlowSummary({
                    status: "completed",
                    task_id: "task-blocked-terminal",
                    task_summary: "Terminal task whose release ended blocked.",
                    task_title: "Blocked terminal research",
                    terminal_outcome: "blocked",
                    updated_at: "2026-06-29T06:00:00Z",
                }),
            ],
            "cursor-page-2",
        );
        const secondPage = createRuntimeFlowSummaryList([
            createRuntimeFlowSummary({
                status: "completed",
                task_id: "task-second-page",
                task_summary: "Second cursor page.",
                task_title: "Review accepted page",
                updated_at: "2026-06-29T07:00:00Z",
            }),
        ]);
        server.use(
            http.get("*/runtime/tasks", ({ request }) => {
                seenRequests.push(new URL(request.url));
                const cursor = new URL(request.url).searchParams.get("cursor");
                return HttpResponse.json(cursor === "cursor-page-2" ? secondPage : firstPage);
            }),
        );

        renderTasksPage();

        expect(screen.getByRole("status", { name: "Loading task rows" })).toBeVisible();
        expect(screen.getByText("Loading tasks...")).toBeVisible();
        expect(await screen.findByText("Refresh runtime route copy")).toBeVisible();
        expect(
            screen.getByText(
                "Validate long task title wrapping inside the scan-first Tasks route implementation",
            ),
        ).toBeVisible();
        expect(screen.getAllByText("Paused").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Cancelled").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Blocked").length).toBeGreaterThanOrEqual(2);
        expect(screen.queryByText(/Assignment assignment-001/)).not.toBeInTheDocument();
        expect(screen.queryByText(/Attempt attempt-001/)).not.toBeInTheDocument();
        expect(seenRequests[0]?.searchParams.get("limit")).toBe("25");
        expect(seenRequests[0]?.searchParams.get("status")).toBe("any");
        expect(seenRequests[0]?.searchParams.get("sort")).toBe("updated_at_desc");

        await user.selectOptions(screen.getByLabelText("Status"), "paused");
        await waitFor(() => {
            expect(seenRequests.at(-1)?.searchParams.get("status")).toBe("paused");
        });

        await user.clear(screen.getByLabelText("Search"));
        await user.type(screen.getByLabelText("Search"), "route copy");
        await waitFor(() => {
            expect(seenRequests.at(-1)?.searchParams.get("q")).toBe("route copy");
        });

        await user.selectOptions(screen.getByLabelText("Sort"), "task_title_asc");
        await waitFor(() => {
            expect(seenRequests.at(-1)?.searchParams.get("sort")).toBe("task_title_asc");
        });

        await user.click(screen.getByRole("button", { name: "Load more" }));
        expect(await screen.findByText("Review accepted page")).toBeVisible();
        expect(seenRequests.at(-1)?.searchParams.get("cursor")).toBe("cursor-page-2");
    });

    it("renders empty and no-results states without fake totals", async () => {
        const user = userEvent.setup();
        server.use(
            http.get("*/runtime/tasks", () =>
                HttpResponse.json(createRuntimeFlowSummaryList([], null)),
            ),
        );

        renderTasksPage();

        const emptyState = await screen.findByRole("status", { name: "No tasks available" });
        expect(within(emptyState).getByText("The runtime task list is empty.")).toBeVisible();

        await user.type(screen.getByLabelText("Search"), "missing task");

        const noResultsState = await screen.findByRole("status", { name: "No matching tasks" });
        const clearFiltersButton = within(noResultsState).getByRole("button", {
            name: "Clear filters",
        });
        clearFiltersButton.focus();
        expect(clearFiltersButton).toHaveFocus();
        await user.keyboard("{Enter}");
        await waitFor(() => {
            expect(screen.getByLabelText("Search")).toHaveValue("");
        });
        expect(await screen.findByRole("status", { name: "No tasks available" })).toBeVisible();
        expect(screen.queryByText(/total/i)).not.toBeInTheDocument();
    });

    it("does not reuse a stale load-more cursor while changed criteria are pending", async () => {
        const user = userEvent.setup();
        const seenRequests: URL[] = [];
        const changedCriteriaPageRead = createDeferred();
        const firstPage = createRuntimeFlowSummaryList(createV2RuntimeTaskRows(), "cursor-page-2");
        const changedCriteriaPage = createRuntimeFlowSummaryList([
            createRuntimeFlowSummary({
                status: "running",
                task_id: "task-filtered-route-copy",
                task_summary: "Filtered first page for the new search criteria.",
                task_title: "Filtered route copy task",
                updated_at: "2026-06-29T15:00:00Z",
            }),
        ]);
        const staleCursorPage = createRuntimeFlowSummaryList([
            createRuntimeFlowSummary({
                status: "paused",
                task_id: "task-stale-cursor-row",
                task_summary: "This row belongs to the previous cursor scope.",
                task_title: "Stale cursor row",
                updated_at: "2026-06-29T06:00:00Z",
            }),
        ]);

        server.use(
            http.get("*/runtime/tasks", async ({ request }) => {
                const requestUrl = new URL(request.url);
                seenRequests.push(requestUrl);

                if (requestUrl.searchParams.get("cursor") === "cursor-page-2") {
                    return HttpResponse.json(staleCursorPage);
                }

                if (requestUrl.searchParams.get("q") === "route copy") {
                    await changedCriteriaPageRead.promise;
                    return HttpResponse.json(changedCriteriaPage);
                }

                return HttpResponse.json(firstPage);
            }),
        );

        renderTasksPage();

        expect(await screen.findByText("Refresh runtime route copy")).toBeVisible();

        await user.type(screen.getByLabelText("Search"), "route copy");
        await waitFor(() => {
            expect(
                seenRequests.some(
                    (requestUrl) =>
                        requestUrl.searchParams.get("q") === "route copy" &&
                        requestUrl.searchParams.get("cursor") === null,
                ),
            ).toBe(true);
        });

        const loadMoreButton = screen.getByRole("button", { name: "Load more" });
        expect(loadMoreButton).toBeDisabled();
        await user.click(loadMoreButton);

        expect(hasStaleCursorRequest(seenRequests)).toBe(false);

        changedCriteriaPageRead.resolve();

        expect(await screen.findByText("Filtered route copy task")).toBeVisible();
        expect(screen.queryByText("Stale cursor row")).not.toBeInTheDocument();
        expect(hasStaleCursorRequest(seenRequests)).toBe(false);
    });

    it("renders read errors as task-list states", async () => {
        server.use(
            http.get("*/runtime/tasks", () =>
                HttpResponse.text("Runtime task read failed.", { status: 500 }),
            ),
        );

        renderTasksPage();
        const readErrorState = await screen.findByRole("alert", { name: "Tasks could not load" });
        expect(
            within(readErrorState).getByText(
                "The AutoClaw API returned an unexpected error response.",
            ),
        ).toBeVisible();
        const readErrorRetryButton = within(readErrorState).getByRole("button", {
            name: "Retry",
        });
        readErrorRetryButton.focus();
        expect(readErrorRetryButton).toHaveFocus();
    });

    it("opens a task row through the task-detail route", async () => {
        const rows = createV2RuntimeTaskRows();
        server.use(
            ...createConsoleApiHandlers(
                createConsoleMockScenario({
                    taskList: createRuntimeFlowSummaryList(rows, null),
                }),
            ),
        );

        renderTasksPage();

        const taskRows = within(await screen.findByRole("list", { name: "Task rows" }));
        await userEvent.click(
            taskRows.getByRole("link", { name: "Open Refresh runtime route copy in Task Detail" }),
        );

        expect(await screen.findByTestId("task-detail-target")).toHaveTextContent(
            "task-runtime-copy-refresh",
        );
    });
});

function renderTasksPage() {
    return render(
        <MemoryRouter initialEntries={["/tasks"]}>
            <Routes>
                <Route element={<TasksPage />} path="/tasks" />
                <Route element={<TaskDetailTarget />} path="/tasks/:taskId" />
            </Routes>
        </MemoryRouter>,
    );
}

function TaskDetailTarget() {
    const { taskId } = useParams();

    return <div data-testid="task-detail-target">{taskId}</div>;
}

function hasStaleCursorRequest(requests: readonly URL[]): boolean {
    return requests.some(
        (requestUrl) =>
            requestUrl.searchParams.get("cursor") === "cursor-page-2" &&
            requestUrl.searchParams.get("q") === "route copy",
    );
}

function createV2RuntimeTaskRows(): readonly components["schemas"]["RuntimeFlowSummary"][] {
    return [
        createRuntimeFlowSummary({
            status: "running",
            task_id: "task-runtime-copy-refresh",
            task_summary: "Replace retired runtime labels without widening the task hub.",
            task_title: "Refresh runtime route copy",
        }),
        createRuntimeFlowSummary({
            status: "paused",
            task_id: "task-command-run-overflow",
            task_summary: "Check long rows on narrow widths.",
            task_title: "Verify command-run overflow",
        }),
        createRuntimeFlowSummary({
            status: "completed",
            task_id: "task-release-note",
            task_summary: "Archive accepted evidence.",
            task_title: "Close frontend planning note",
        }),
        createRuntimeFlowSummary({
            status: "cancelled",
            task_id: "task-old-compose-refresh",
            task_summary: "Cancelled stale draft refresh after continuation superseded it.",
            task_title: "Retire old compose refresh",
        }),
    ];
}

function createDeferred(): { readonly promise: Promise<void>; readonly resolve: () => void } {
    let resolvePromise!: () => void;
    const promise = new Promise<void>((resolve) => {
        resolvePromise = resolve;
    });

    return { promise, resolve: resolvePromise };
}
