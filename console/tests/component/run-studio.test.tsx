import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type {
    ControllerResponse,
    ProductEventSource,
} from "../../src/api/client";
import { RunListPage } from "../../src/features/runs/RunListPage";
import { RunStudioPage } from "../../src/features/runs/RunStudioPage";
import { StartRunPage } from "../../src/features/runs/StartRunPage";
import type { TaskControlReceipt } from "../../src/features/runs/run-api";
import {
    commandOutputFixture,
    humanResponseReceiptFixture,
    response,
    runApiStub,
    taskFixture,
    taskSearchFixture,
    taskStartReceiptFixture,
    workflowSearchFixture,
} from "../fixtures/runs";

describe("temporary Run Studio", () => {
    it("renders a scan-friendly semantic Run list without runtime language", async () => {
        const api = runApiStub({
            searchRuns: () => Promise.resolve(response(taskSearchFixture())),
        });

        render(
            <MemoryRouter>
                <RunListPage api={api} />
            </MemoryRouter>,
        );

        expect(screen.getByRole("status")).toHaveTextContent("Loading Runs");
        expect(
            await screen.findByRole("heading", {
                name: "Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        expect(screen.getByText("Needs your attention")).toBeVisible();
        expect(
            screen.getByRole("link", {
                name: "Open Run: Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        expect(
            screen.queryByText(/dispatch|attempt|boundary|wave/i),
        ).toBeNull();
    });

    it("starts from one exact prompt with optional workspace file references", async () => {
        const startRun = vi.fn(() =>
            Promise.resolve(response(taskStartReceiptFixture(), 202)),
        );
        const api = runApiStub({
            searchWorkflows: () =>
                Promise.resolve(response(workflowSearchFixture())),
            startRun,
        });
        const user = userEvent.setup();

        render(
            <MemoryRouter initialEntries={["/runs/new"]}>
                <Routes>
                    <Route
                        element={<StartRunPage api={api} />}
                        path="/runs/new"
                    />
                    <Route
                        element={<p>Accepted Run opened</p>}
                        path="/runs/:taskId"
                    />
                </Routes>
            </MemoryRouter>,
        );

        await screen.findByLabelText("Workflow");
        await user.type(
            screen.getByLabelText("What should the team accomplish?"),
            "Review the release and recommend one.",
        );
        await user.click(screen.getByText("Advanced"));
        await user.type(
            screen.getByLabelText(/^Workspace/),
            "/workspace/project",
        );
        await user.click(screen.getByRole("button", { name: "Add file" }));
        await user.type(
            screen.getByLabelText("File 1 path"),
            "docs/release-brief.md",
        );
        await user.type(
            screen.getByLabelText(/^Why should the team open it/),
            "Release constraints.",
        );
        await user.click(screen.getByRole("button", { name: "Start run" }));

        expect(await screen.findByText("Accepted Run opened")).toBeVisible();
        expect(startRun).toHaveBeenCalledWith({
            workflow: "production-feature-delivery",
            prompt: "Review the release and recommend one.",
            workspace: "/workspace/project",
            files: [
                {
                    path: "docs/release-brief.md",
                    description: "Release constraints.",
                },
            ],
        });
    });

    it("selects a teammate to inspect their update, files, and current plan", async () => {
        const api = runApiStub({
            getRun: () => Promise.resolve(response(taskFixture())),
        });
        const user = userEvent.setup();

        renderRun(api);

        const lead = await screen.findByRole("button", {
            name: /Delivery lead.*Waiting/,
        });
        expect(lead).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByText("Compare candidates")).toBeVisible();
        expect(
            screen.queryByText("Inspect the supporting evidence"),
        ).toBeNull();

        const reviewer = screen.getByRole("button", {
            name: /Independent reviewer.*Done/,
        });
        await user.click(reviewer);

        expect(reviewer).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByText("Challenge the evidence.")).toBeVisible();
        expect(
            screen.getByText("Independent review is complete."),
        ).toBeVisible();
        expect(
            screen.getByText(".banksia/t_7m4k2d9x/artifacts/review.md"),
        ).toBeVisible();
        expect(
            screen.getByText("Inspect the supporting evidence"),
        ).toBeVisible();
        expect(screen.queryByText("Compare candidates")).toBeNull();
    });

    it("answers a Human Request and opens bounded Action output from controller truth", async () => {
        const initialTask = taskFixture();
        const getRun = vi
            .fn()
            .mockResolvedValueOnce(response(initialTask))
            .mockResolvedValue(
                response(
                    taskFixture({
                        activities: [
                            ...initialTask.activities,
                            {
                                id: "activity-two",
                                kind: "input_received",
                                occurred_at: "2026-07-26T01:11:00Z",
                                title: "Response received",
                                summary: "The team can continue.",
                                member: null,
                                outcome: null,
                                files: [],
                                action: null,
                            },
                        ],
                    }),
                ),
            );
        const respondToHumanRequest = vi.fn(() =>
            Promise.resolve(response(humanResponseReceiptFixture())),
        );
        const api = runApiStub({
            getRun,
            respondToHumanRequest,
            getCommandOutput: () =>
                Promise.resolve(response(commandOutputFixture())),
        });
        const user = userEvent.setup();

        renderRun(api);

        expect(
            await screen.findByRole("heading", {
                name: "Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        expect(
            screen.getByRole("heading", { name: "Action required" }),
        ).toBeVisible();
        await user.click(screen.getByRole("radio", { name: /Reliability/ }));
        await user.click(
            screen.getByRole("button", { name: "Submit response" }),
        );

        expect(await screen.findAllByText("Response received")).toHaveLength(1);
        expect(respondToHumanRequest).toHaveBeenCalledWith(
            "t_7m4k2d9x",
            "request-one",
            "answer-request",
            {
                kind: "answer",
                item_responses: {
                    priority: {
                        kind: "option",
                        option_id: "reliability",
                    },
                },
            },
        );
        await waitFor(() => expect(getRun).toHaveBeenCalledTimes(2));

        await user.click(
            screen.getByRole("tab", {
                name: "Commands (1)",
            }),
        );
        await user.click(screen.getByRole("button", { name: "View output" }));
        const dialog = await screen.findByRole("dialog", {
            name: "Output: Run the release verification suite",
        });
        expect(
            within(dialog).getByLabelText("Command output"),
        ).toHaveTextContent("all focused checks passed");
        expect(
            within(dialog).getByText(
                "The output is incomplete. Only observed content is shown.",
            ),
        ).toBeVisible();
        expect(document.body).not.toHaveTextContent("c_q3m8y1ka");
    });

    it("keeps current content through a delayed live reconnect and clears the notice on recovery", async () => {
        const sources: FakeEventSource[] = [];
        const api = runApiStub({
            getRun: () => Promise.resolve(response(taskFixture())),
            openRunActivityStream: () => {
                const source = new FakeEventSource();
                sources.push(source);
                return source;
            },
        });

        renderRun(api);

        expect(
            await screen.findByRole("heading", {
                name: "Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        expect(sources).toHaveLength(1);

        vi.useFakeTimers();
        try {
            act(() => sources[0]?.emit("error"));
            expect(
                screen.queryByText("Live updates are delayed.", {
                    exact: false,
                }),
            ).toBeNull();

            await act(() => vi.advanceTimersByTimeAsync(5_000));

            expect(
                screen.getByText("Live updates are delayed.", {
                    exact: false,
                }),
            ).toBeVisible();
            expect(
                screen.getByRole("heading", {
                    name: "Compare the release candidates and recommend one.",
                }),
            ).toBeVisible();
            expect(sources[0]?.close).toHaveBeenCalledOnce();

            fireEvent.click(screen.getByRole("button", { name: "Retry" }));
            await act(() => vi.advanceTimersByTimeAsync(0));
            const recovered = sources.at(-1);
            expect(recovered).toBeDefined();
            act(() => recovered?.emit("open"));

            expect(
                screen.queryByText("Live updates are delayed.", {
                    exact: false,
                }),
            ).toBeNull();
        } finally {
            vi.useRealTimers();
        }
    });

    it("starts live recovery after an initial read succeeds on retry", async () => {
        const sources: FakeEventSource[] = [];
        const getRun = vi
            .fn()
            .mockRejectedValueOnce(new Error("Controller is unavailable."))
            .mockResolvedValue(response(taskFixture()));
        const api = runApiStub({
            getRun,
            openRunActivityStream: () => {
                const source = new FakeEventSource();
                sources.push(source);
                return source;
            },
        });
        const user = userEvent.setup();

        renderRun(api);

        expect(
            await screen.findByText("Controller is unavailable.", {
                exact: false,
            }),
        ).toBeVisible();
        await user.click(screen.getByRole("button", { name: "Try again" }));

        expect(
            await screen.findByRole("heading", {
                name: "Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        await waitFor(() => expect(sources).toHaveLength(1));
        expect(screen.getByText("Run started")).toBeVisible();
    });

    it("does not repeat a generic terminal message above the accepted Result", async () => {
        const api = runApiStub({
            getRun: () =>
                Promise.resolve(
                    response(
                        taskFixture({
                            status: "completed",
                            status_message:
                                "The run completed with an accepted result.",
                            result: {
                                status: "completed",
                                summary: "The verified report is ready.",
                                details: "See the **Result** below.",
                                files: [],
                                completed_at: "2026-07-26T01:10:00Z",
                            },
                        }),
                    ),
                ),
        });

        renderRun(api);

        expect(
            await screen.findByText("The verified report is ready."),
        ).toBeVisible();
        expect(
            screen.queryByText("The run completed with an accepted result."),
        ).not.toBeInTheDocument();
    });

    it("does not narrate a non-terminal status already shown by the status label", async () => {
        const api = runApiStub({
            getRun: () =>
                Promise.resolve(
                    response(
                        taskFixture({
                            status: "working",
                            status_message: "The team is working.",
                            result: null,
                        }),
                    ),
                ),
        });

        renderRun(api);

        expect(
            await screen.findByRole("heading", {
                name: "Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        expect(screen.getByText("Working")).toBeVisible();
        expect(screen.queryByText("The team is working.")).toBeNull();
    });

    it("does not apply a stale control response after switching Runs", async () => {
        let resolveControl:
            | ((receipt: ControllerResponse<TaskControlReceipt>) => void)
            | undefined;
        const controlRun = vi.fn(
            () =>
                new Promise<ControllerResponse<TaskControlReceipt>>(
                    (resolve) => {
                        resolveControl = resolve;
                    },
                ),
        );
        const getRun = vi.fn((taskId: string) =>
            Promise.resolve(
                response(
                    taskFixture({
                        id: taskId,
                        prompt_excerpt:
                            taskId === "task-a" ? "Task A" : "Task B",
                    }),
                ),
            ),
        );
        const api = runApiStub({ controlRun, getRun });
        const user = userEvent.setup();

        render(
            <MemoryRouter initialEntries={["/runs/task-a"]}>
                <Routes>
                    <Route
                        element={
                            <>
                                <Link to="/runs/task-b">Switch Run</Link>
                                <RunStudioPage api={api} />
                            </>
                        }
                        path="/runs/:taskId"
                    />
                </Routes>
            </MemoryRouter>,
        );

        expect(
            await screen.findByRole("heading", { name: "Task A" }),
        ).toBeVisible();
        await user.click(screen.getByRole("button", { name: "Pause Run" }));
        await user.click(screen.getByRole("link", { name: "Switch Run" }));
        expect(
            await screen.findByRole("heading", { name: "Task B" }),
        ).toBeVisible();

        act(() =>
            resolveControl?.(
                response({
                    receipt_id: "receipt-task-a",
                    action: "pause",
                    status_message: "Task A was paused.",
                    task: taskFixture({
                        id: "task-a",
                        prompt_excerpt: "Task A",
                        status: "paused",
                    }),
                }),
            ),
        );

        await waitFor(() => expect(controlRun).toHaveBeenCalledOnce());
        expect(screen.getByRole("heading", { name: "Task B" })).toBeVisible();
        expect(screen.queryByText("Task A was paused.")).toBeNull();
        expect(document.querySelector(".run-status")).not.toHaveTextContent(
            "Paused",
        );
    });
});

function renderRun(api: Parameters<typeof RunStudioPage>[0]["api"]) {
    return render(
        <MemoryRouter initialEntries={["/runs/t_7m4k2d9x"]}>
            <Routes>
                <Route
                    element={<RunStudioPage api={api} />}
                    path="/runs/:taskId"
                />
            </Routes>
        </MemoryRouter>,
    );
}

class FakeEventSource implements ProductEventSource {
    private readonly listeners = new Map<
        string,
        Set<EventListenerOrEventListenerObject>
    >();

    public readonly close = vi.fn();

    public addEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject,
    ): void {
        const listeners = this.listeners.get(type) ?? new Set();
        listeners.add(listener);
        this.listeners.set(type, listeners);
    }

    public removeEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject,
    ): void {
        this.listeners.get(type)?.delete(listener);
    }

    public emit(type: string, event: Event = new Event(type)): void {
        for (const listener of this.listeners.get(type) ?? []) {
            if (typeof listener === "function") {
                listener(event);
            } else {
                listener.handleEvent(event);
            }
        }
    }
}
