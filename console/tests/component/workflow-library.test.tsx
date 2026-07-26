import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowLibraryPage } from "../../src/features/workflows/WorkflowLibraryPage";
import {
    draftFixture,
    response,
    searchItemFixture,
    workflowApiStub,
} from "../fixtures/workflows";

afterEach(() => {
    vi.useRealTimers();
});

describe("Workflow library", () => {
    it("shows loading, then controller-owned state and quiet Starter provenance", async () => {
        let release: (() => void) | undefined;
        const gate = new Promise<void>((resolve) => {
            release = resolve;
        });
        const api = workflowApiStub({
            searchWorkflows: async () => {
                await gate;
                return response({
                    items: [searchItemFixture()],
                    next_cursor: null,
                });
            },
        });

        renderLibrary(api);

        expect(screen.getByRole("status")).toHaveTextContent(
            "Loading Workflows",
        );
        release?.();
        expect(
            await screen.findByRole("heading", { name: "evidence-synthesis" }),
        ).toBeVisible();
        expect(screen.getByText("Starter")).toBeVisible();
        expect(screen.getByText("Published")).toBeVisible();
        expect(
            screen.getByRole("link", { name: "Open evidence-synthesis" }),
        ).toHaveAttribute("href", "/workflows/evidence-synthesis");
        expect(screen.queryByText("start_run")).not.toBeInTheDocument();
    });

    it("keeps read-only detail navigation separate from returned mutation actions", async () => {
        const api = workflowApiStub({
            searchWorkflows: () =>
                Promise.resolve(
                    response({
                        items: [
                            searchItemFixture({
                                available_actions: ["start_run"],
                            }),
                        ],
                        next_cursor: null,
                    }),
                ),
        });

        renderLibrary(api);

        expect(
            await screen.findByRole("link", {
                name: "Open evidence-synthesis",
            }),
        ).toHaveAttribute("href", "/workflows/evidence-synthesis");
        expect(screen.queryByText("Start run")).not.toBeInTheDocument();
    });

    it("distinguishes an empty library from a searched no-results state", async () => {
        const searches: string[] = [];
        const api = workflowApiStub({
            searchWorkflows: (query) => {
                searches.push(query);
                return Promise.resolve(
                    response({ items: [], next_cursor: null }),
                );
            },
        });
        const user = userEvent.setup();

        renderLibrary(api);

        expect(
            await screen.findByRole("heading", { name: "No Workflows yet" }),
        ).toBeVisible();
        await user.type(
            screen.getByRole("searchbox", { name: "Search Workflows" }),
            "legal",
        );
        expect(
            await screen.findByRole("heading", { name: "No matches" }),
        ).toBeVisible();
        expect(searches.at(-1)).toBe("legal");
    });

    it("keeps opaque pagination in the client and shows the next Workflow page on request", async () => {
        const cursors: (string | null | undefined)[] = [];
        const api = workflowApiStub({
            searchWorkflows: (_query, cursor) => {
                cursors.push(cursor);
                return Promise.resolve(
                    response(
                        cursor === null
                            ? {
                                  items: [searchItemFixture()],
                                  next_cursor: "opaque-next-page",
                              }
                            : {
                                  items: [
                                      searchItemFixture({
                                          workflow_id: "reviewed-code-change",
                                      }),
                                  ],
                                  next_cursor: null,
                              },
                    ),
                );
            },
        });
        const user = userEvent.setup();

        renderLibrary(api);
        await screen.findByRole("heading", { name: "evidence-synthesis" });
        await user.click(
            screen.getByRole("button", { name: "Show more Workflows" }),
        );

        expect(
            await screen.findByRole("heading", {
                name: "reviewed-code-change",
            }),
        ).toBeVisible();
        expect(cursors).toEqual([null, "opaque-next-page"]);
        expect(
            screen.queryByRole("button", { name: "Show more Workflows" }),
        ).toBeNull();
    });

    it("aborts a superseded read immediately but waits to send the debounced search", async () => {
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        const signals: AbortSignal[] = [];
        const searchWorkflows = vi.fn(
            (_query: string, _cursor, signal?: AbortSignal) => {
                if (signal !== undefined) {
                    signals.push(signal);
                }
                return new Promise<never>(() => undefined);
            },
        );
        renderLibrary(workflowApiStub({ searchWorkflows }));
        expect(searchWorkflows).toHaveBeenCalledTimes(1);

        fireEvent.change(
            screen.getByRole("searchbox", { name: "Search Workflows" }),
            { target: { value: "review" } },
        );
        expect(signals[0]?.aborted).toBe(true);
        expect(searchWorkflows).toHaveBeenCalledTimes(1);

        await act(() => vi.advanceTimersByTimeAsync(274));
        expect(searchWorkflows).toHaveBeenCalledTimes(1);
        await act(() => vi.advanceTimersByTimeAsync(1));
        expect(searchWorkflows).toHaveBeenCalledTimes(2);
        expect(searchWorkflows).toHaveBeenLastCalledWith(
            "review",
            null,
            expect.any(AbortSignal),
        );
    });

    it("renders an actionable error without replacing it with an empty state", async () => {
        const api = workflowApiStub({
            searchWorkflows: vi
                .fn()
                .mockRejectedValue(new Error("The controller is unavailable.")),
        });

        renderLibrary(api);

        expect(await screen.findByRole("alert")).toHaveTextContent(
            "The controller is unavailable.",
        );
        expect(screen.queryByText("No Workflows yet")).not.toBeInTheDocument();
    });

    it("creates from explicit identity and purpose fields, then opens the draft", async () => {
        let releaseCreate: (() => void) | undefined;
        const createGate = new Promise<void>((resolve) => {
            releaseCreate = resolve;
        });
        const createWorkflow = vi.fn(async () => {
            await createGate;
            return response(
                {
                    draft: draftFixture(),
                    is_created: true,
                },
                201,
            );
        });
        const api = workflowApiStub({
            searchWorkflows: () =>
                Promise.resolve(
                    response({
                        items: [searchItemFixture()],
                        next_cursor: null,
                    }),
                ),
            createWorkflow,
        });
        const user = userEvent.setup();

        renderLibrary(api);
        await screen.findByRole("heading", { name: "evidence-synthesis" });
        await user.click(
            screen.getByRole("button", { name: "Create Workflow" }),
        );
        const dialog = screen.getByRole("dialog", {
            name: "Create a Workflow",
        });
        await user.type(
            within(dialog).getByLabelText("Workflow ID"),
            "review-team",
        );
        await user.type(
            within(dialog).getByLabelText("Use this team when…"),
            "Review a consequential change.",
        );
        await user.click(
            within(dialog).getByRole("button", { name: "Create Workflow" }),
        );

        await waitFor(() => {
            expect(createWorkflow).toHaveBeenCalledWith({
                kind: "create",
                workflow_id: "review-team",
                description: "Review a consequential change.",
            });
        });
        expect(
            within(dialog).getByRole("button", {
                name: "Close Create a Workflow",
            }),
        ).toBeDisabled();
        expect(
            within(dialog).getByRole("button", { name: "Cancel" }),
        ).toBeDisabled();
        releaseCreate?.();
        expect(await screen.findByText("Studio route opened")).toBeVisible();
    });
});

function renderLibrary(api: Parameters<typeof WorkflowLibraryPage>[0]["api"]) {
    return render(
        <MemoryRouter initialEntries={["/workflows"]}>
            <Routes>
                <Route
                    element={<WorkflowLibraryPage api={api} />}
                    path="/workflows"
                />
                <Route
                    element={<p>Studio route opened</p>}
                    path="/workflows/:workflowId"
                />
            </Routes>
        </MemoryRouter>,
    );
}
