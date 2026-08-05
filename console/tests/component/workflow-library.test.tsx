import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
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
            await screen.findByRole("heading", {
                name: "deep-research-and-decision-brief",
            }),
        ).toBeVisible();
        expect(screen.getByText("Starter")).toBeVisible();
        expect(screen.getByText("Published")).toBeVisible();
        expect(
            screen.getByRole("link", {
                name: "Open deep-research-and-decision-brief",
            }),
        ).toHaveAttribute(
            "href",
            "/workflows/deep-research-and-decision-brief",
        );
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
                name: "Open deep-research-and-decision-brief",
            }),
        ).toHaveAttribute(
            "href",
            "/workflows/deep-research-and-decision-brief",
        );
        expect(screen.queryByText("Start run")).not.toBeInTheDocument();
    });

    it("removes a Workflow only after explaining that existing Runs keep history", async () => {
        const removeWorkflow = vi.fn((workflowId: string) =>
            Promise.resolve(
                response({
                    is_removed: true,
                    workflow_id: workflowId,
                }),
            ),
        );
        const api = workflowApiStub({
            searchWorkflows: () =>
                Promise.resolve(
                    response({
                        items: [searchItemFixture()],
                        next_cursor: null,
                    }),
                ),
            removeWorkflow,
        });
        const user = userEvent.setup();

        renderLibrary(api);
        await screen.findByRole("heading", {
            name: "deep-research-and-decision-brief",
        });
        await user.click(
            screen.getByRole("button", {
                name: "More actions for deep-research-and-decision-brief",
            }),
        );
        await user.click(
            screen.getByRole("menuitem", { name: "Remove workflow" }),
        );

        const dialog = screen.getByRole("dialog", {
            name: "Remove deep-research-and-decision-brief?",
        });
        expect(dialog).toHaveTextContent(
            "Existing runs keep their recorded Workflow revision.",
        );
        expect(dialog).toHaveTextContent("The ID can be created again");
        await user.click(
            within(dialog).getByRole("button", { name: "Remove Workflow" }),
        );

        await waitFor(() => {
            expect(removeWorkflow).toHaveBeenCalledWith(
                "deep-research-and-decision-brief",
            );
            expect(
                screen.queryByRole("link", {
                    name: "Open deep-research-and-decision-brief",
                }),
            ).not.toBeInTheDocument();
        });
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
            screen.getByRole("searchbox", { name: /Search workflows/i }),
            "legal",
        );
        expect(
            await screen.findByRole("heading", {
                name: "No Workflows match this search",
            }),
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
                                          workflow_id:
                                              "production-feature-delivery",
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
        await screen.findByRole("heading", {
            name: "deep-research-and-decision-brief",
        });
        await user.click(
            screen.getByRole("button", { name: "Show more Workflows" }),
        );

        expect(
            await screen.findByRole("heading", {
                name: "production-feature-delivery",
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
            screen.getByRole("searchbox", { name: /Search workflows/i }),
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
        await screen.findByRole("heading", {
            name: "deep-research-and-decision-brief",
        });
        await user.click(
            screen.getByRole("button", { name: "Create workflow" }),
        );
        const dialog = screen.getByRole("dialog", {
            name: "Create a Workflow",
        });
        expect(dialog).toHaveTextContent(
            "Reusing a removed ID continues its preserved revision history",
        );
        await user.type(
            within(dialog).getByLabelText("Workflow ID"),
            "review-team",
        );
        await user.type(
            within(dialog).getByLabelText("Purpose"),
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
            within(dialog).getByRole("button", { name: "Cancel" }),
        ).toBeDisabled();
        releaseCreate?.();
        expect(await screen.findByText("Studio route opened")).toBeVisible();
    });

    it("opens the create dialog from the sidebar route request", async () => {
        const user = userEvent.setup();

        renderLibrary(
            workflowApiStub({
                searchWorkflows: () =>
                    Promise.resolve(response({ items: [], next_cursor: null })),
            }),
            "/workflows?create=1",
        );

        expect(
            screen.getByRole("dialog", { name: "Create a Workflow" }),
        ).toBeVisible();
        await user.click(screen.getByRole("button", { name: "Cancel" }));
        expect(
            screen.queryByRole("dialog", { name: "Create a Workflow" }),
        ).not.toBeInTheDocument();
    });
});

function renderLibrary(
    api: Parameters<typeof WorkflowLibraryPage>[0]["api"],
    initialEntry = "/workflows",
) {
    return render(
        <MemoryRouter initialEntries={[initialEntry]}>
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
