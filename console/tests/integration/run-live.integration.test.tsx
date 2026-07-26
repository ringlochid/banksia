import { act, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import {
    afterAll,
    afterEach,
    beforeAll,
    describe,
    expect,
    it,
    vi,
} from "vitest";

import { RunApiClient, RunStudioPage } from "../../src/features/runs";
import type { TaskActivity, TaskView } from "../../src/features/runs/run-api";
import type {
    ProductEventSource,
    ProductEventSourceFactory,
} from "../../src/api/client";
import { taskFixture } from "../fixtures/runs";

const API_ROOT = "http://banksia.test/api";
const TASK_ID = "t_7m4k2d9x";
const TASK_PATH = `${API_ROOT}/tasks/${TASK_ID}`;
const ACTIVITY_PATH = `${TASK_PATH}/activities`;
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("Run live controller convergence", () => {
    it("backfills before subscribing, deduplicates Activity, and resets a stale reconnect cursor", async () => {
        const initialActivity = activity("cursor-one", "Run started");
        const missedOne = activity("cursor-two", "Research completed");
        const missedTwo = activity("cursor-three", "Review completed");
        const liveActivity = activity("cursor-four", "New evidence received");
        const resetActivity = activity(
            "cursor-reset",
            "Current controller truth",
        );
        let currentTask = run([initialActivity]);
        const requestedCursors: Array<string | null> = [];
        const sources: FakeEventSource[] = [];
        const sourceFactory = captureSources(sources);

        server.use(
            http.get(TASK_PATH, () => HttpResponse.json(currentTask)),
            http.get(ACTIVITY_PATH, ({ request }) => {
                const cursor = new URL(request.url).searchParams.get("cursor");
                requestedCursors.push(cursor);
                if (cursor === "cursor-one") {
                    return HttpResponse.json({
                        items: [missedOne],
                        next_cursor: "cursor-two",
                    });
                }
                if (cursor === "cursor-two") {
                    return HttpResponse.json({
                        items: [missedTwo],
                        next_cursor: null,
                    });
                }
                if (cursor === "cursor-four") {
                    return HttpResponse.json(
                        {
                            code: "cursor_reset_required",
                            summary: "The Activity cursor is no longer valid.",
                            retryable: true,
                        },
                        { status: 410 },
                    );
                }
                return HttpResponse.json({
                    items: [],
                    next_cursor: null,
                });
            }),
        );
        const view = renderRun(new RunApiClient(API_ROOT, sourceFactory));

        await waitFor(() => expect(sources).toHaveLength(1));
        expect(requestedCursors.slice(0, 2)).toEqual([
            "cursor-one",
            "cursor-two",
        ]);
        expect(streamCursor(sources[0])).toBe("cursor-three");
        expect(screen.getByText("Research completed")).toBeVisible();
        expect(screen.getByText("Review completed")).toBeVisible();

        act(() => {
            sources[0]?.emitActivity(liveActivity);
            sources[0]?.emitActivity(liveActivity);
        });
        expect(screen.getAllByText("New evidence received")).toHaveLength(1);

        currentTask = run([resetActivity], {
            status_message: "The latest controller state is visible.",
        });
        act(() => sources[0]?.emit("error"));

        await waitFor(() => expect(sources).toHaveLength(2));
        expect(sources[0]?.close).toHaveBeenCalledOnce();
        expect(requestedCursors).toContain("cursor-four");
        expect(requestedCursors).toContain("cursor-reset");
        expect(streamCursor(sources[1])).toBe("cursor-reset");
        expect(screen.getByText("Current controller truth")).toBeVisible();
        expect(
            screen.getByText("The latest controller state is visible."),
        ).toBeVisible();

        view.unmount();
        expect(sources[1]?.close).toHaveBeenCalledOnce();
    });

    it("coalesces Task-changed hints and uses Task readback instead of event payload", async () => {
        const sourceFactorySources: FakeEventSource[] = [];
        const firstTask = run([activity("cursor-one", "Run started")]);
        const pendingTask = run([activity("cursor-one", "Run started")], {
            status_message: "First readback.",
        });
        const finalTask = run([activity("cursor-one", "Run started")], {
            status: "completed",
            status_message: "Current after coalescing.",
        });
        let reads = 0;
        let releaseRead: (() => void) | undefined;
        const readGate = new Promise<void>((resolve) => {
            releaseRead = resolve;
        });

        server.use(
            http.get(TASK_PATH, async () => {
                reads += 1;
                if (reads === 1) {
                    return HttpResponse.json(firstTask);
                }
                if (reads === 2) {
                    await readGate;
                    return HttpResponse.json(pendingTask);
                }
                return HttpResponse.json(finalTask);
            }),
            http.get(ACTIVITY_PATH, () =>
                HttpResponse.json({ items: [], next_cursor: null }),
            ),
        );
        const view = renderRun(
            new RunApiClient(API_ROOT, captureSources(sourceFactorySources)),
        );
        await waitFor(() => expect(sourceFactorySources).toHaveLength(1));

        act(() => {
            sourceFactorySources[0]?.emitTaskChanged(
                "cursor-two",
                '{"status":"blocked"}',
            );
            sourceFactorySources[0]?.emitTaskChanged("cursor-three");
            sourceFactorySources[0]?.emitTaskChanged("cursor-four");
        });
        await waitFor(() => expect(reads).toBe(2));
        releaseRead?.();

        await waitFor(() => expect(reads).toBe(3));
        expect(
            await screen.findByText("Current after coalescing."),
        ).toBeVisible();
        expect(document.querySelector(".run-status")).toHaveTextContent(
            "Completed",
        );
        expect(screen.queryByText("Blocked")).toBeNull();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(reads).toBe(3);

        view.unmount();
        expect(sourceFactorySources[0]?.close).toHaveBeenCalledOnce();
    });
});

function renderRun(api: RunApiClient) {
    return render(
        <MemoryRouter initialEntries={[`/runs/${TASK_ID}`]}>
            <Routes>
                <Route
                    element={<RunStudioPage api={api} />}
                    path="/runs/:taskId"
                />
            </Routes>
        </MemoryRouter>,
    );
}

function run(
    activities: readonly TaskActivity[],
    overrides: Partial<TaskView> = {},
): TaskView {
    return taskFixture({
        activities: [...activities],
        activities_truncated: false,
        ...overrides,
    });
}

function activity(id: string, title: string): TaskActivity {
    return {
        id,
        kind: "work_completed",
        occurred_at: "2026-07-26T01:05:00Z",
        title,
        summary: null,
        member: null,
        outcome: "completed",
        files: [],
        action: null,
    };
}

function captureSources(sources: FakeEventSource[]): ProductEventSourceFactory {
    return (url) => {
        const source = new FakeEventSource(url);
        sources.push(source);
        return source;
    };
}

function streamCursor(source: FakeEventSource | undefined): string | null {
    return source === undefined
        ? null
        : new URL(source.url).searchParams.get("cursor");
}

class FakeEventSource implements ProductEventSource {
    private readonly listeners = new Map<
        string,
        Set<EventListenerOrEventListenerObject>
    >();

    public readonly close = vi.fn();

    public constructor(public readonly url: string) {}

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

    public emitActivity(activity: TaskActivity): void {
        this.emit(
            "activity",
            new MessageEvent("activity", {
                data: JSON.stringify(activity),
                lastEventId: activity.id,
            }),
        );
    }

    public emitTaskChanged(cursor: string, data = "{}"): void {
        this.emit(
            "task_changed",
            new MessageEvent("task_changed", {
                data,
                lastEventId: cursor,
            }),
        );
    }
}
