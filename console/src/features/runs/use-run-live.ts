import { useEffect, useRef, useState } from "react";

import { ApiResponseError } from "../../api/client";
import type {
    RunApi,
    TaskActivity,
    TaskActivityPage,
    TaskView,
} from "./run-api";

const LIVE_DELAY_NOTICE_MS = 5_000;
const RECONNECT_BASE_MS = 250;
const RECONNECT_MAX_MS = 4_000;

interface RunLiveView {
    readonly activities: readonly TaskActivity[];
    readonly error: string | null;
    readonly liveDelayed: boolean;
    readonly loading: boolean;
    readonly refreshing: boolean;
    readonly task: TaskView | null;
}

interface RunLiveResult extends RunLiveView {
    readonly refresh: () => void;
    readonly replaceTask: (task: TaskView) => void;
    readonly retryLive: () => void;
}

type UpdateView = (patch: Partial<RunLiveView>) => void;

interface StoredRunLiveView extends RunLiveView {
    readonly taskId: string | undefined;
}

const INITIAL_VIEW: RunLiveView = {
    activities: [],
    error: null,
    liveDelayed: false,
    loading: true,
    refreshing: false,
    task: null,
};

export function useRunLive(
    api: RunApi,
    taskId: string | undefined,
): RunLiveResult {
    const [storedView, setStoredView] = useState<StoredRunLiveView>({
        ...INITIAL_VIEW,
        taskId: undefined,
    });
    const sessionRef = useRef<RunLiveSession | null>(null);

    useEffect(() => {
        if (taskId === undefined) {
            return;
        }
        const session = new RunLiveSession(api, taskId, (patch) => {
            setStoredView((current) => ({ ...current, ...patch, taskId }));
        });
        sessionRef.current = session;
        void session.start();
        return () => {
            session.dispose();
            if (sessionRef.current === session) {
                sessionRef.current = null;
            }
        };
    }, [api, taskId]);

    const view = storedView.taskId === taskId ? storedView : INITIAL_VIEW;
    const currentSession = (): RunLiveSession | null => {
        const session = sessionRef.current;
        return session?.isForTask(taskId) ? session : null;
    };
    return {
        ...view,
        refresh: () => currentSession()?.refresh(),
        replaceTask: (task) => currentSession()?.replaceTask(task),
        retryLive: () => currentSession()?.retryLive(),
    };
}

class RunLiveSession {
    private active = true;
    private activities: TaskActivity[] = [];
    private activityIds = new Set<string>();
    private readonly abortControllers = new Set<AbortController>();
    private cursor: string | null = null;
    private delayedNoticeTimer: ReturnType<typeof setTimeout> | null = null;
    private isLiveInitialized = false;
    private reconnectAttempt = 0;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private sourceCleanup: (() => void) | null = null;
    private taskReadInFlight: Promise<TaskView | null> | null = null;
    private taskReadPending = false;
    private taskReadReportsError = false;

    public constructor(
        private readonly api: RunApi,
        private readonly taskId: string,
        private readonly updateView: UpdateView,
    ) {}

    public async start(): Promise<void> {
        const task = await this.readTask(true);
        if (!this.active) {
            return;
        }
        this.updateView({ loading: false });
        if (task === null) {
            return;
        }
        await this.initializeLive(task);
    }

    public isForTask(taskId: string | undefined): boolean {
        return this.active && taskId === this.taskId;
    }

    public refresh(): void {
        this.updateView({ error: null, refreshing: true });
        void this.readTask(true)
            .then((task) =>
                task === null ? undefined : this.initializeLive(task),
            )
            .finally(() => {
                if (this.active) {
                    this.updateView({ refreshing: false });
                }
            });
    }

    public replaceTask(task: TaskView): void {
        if (!this.active || task.id !== this.taskId) {
            return;
        }
        this.updateView({ task });
        this.mergeActivities(task.activities);
    }

    public retryLive(): void {
        this.clearReconnectTimer();
        this.reconnectAttempt = 0;
        this.scheduleRecovery(true);
    }

    public dispose(): void {
        this.active = false;
        this.closeStream();
        this.clearReconnectTimer();
        this.clearDelayedNoticeTimer();
        for (const controller of this.abortControllers) {
            controller.abort();
        }
        this.abortControllers.clear();
    }

    private async initializeLive(task: TaskView): Promise<void> {
        if (!this.active || this.isLiveInitialized) {
            return;
        }
        this.isLiveInitialized = true;
        this.seedActivities(task);
        try {
            if (
                (await this.backfill(true)) &&
                (await this.readTask(false)) === null
            ) {
                throw new Error("Could not refresh current Run state.");
            }
            this.openStream();
        } catch (error) {
            if (!isAbortError(error)) {
                this.scheduleRecovery();
            }
        }
    }

    private readTask(reportError: boolean): Promise<TaskView | null> {
        this.taskReadPending = true;
        this.taskReadReportsError ||= reportError;
        if (this.taskReadInFlight !== null) {
            return this.taskReadInFlight;
        }
        const read = this.drainTaskReads().finally(() => {
            if (this.taskReadInFlight === read) {
                this.taskReadInFlight = null;
            }
        });
        this.taskReadInFlight = read;
        return read;
    }

    private async drainTaskReads(): Promise<TaskView | null> {
        let result: TaskView | null = null;
        while (this.active && this.taskReadPending) {
            this.taskReadPending = false;
            const reportError = this.taskReadReportsError;
            this.taskReadReportsError = false;
            const controller = this.createAbortController();
            try {
                const response = await this.api.getRun(
                    this.taskId,
                    controller.signal,
                );
                result = response.body;
                if (this.active) {
                    this.updateView({ error: null, task: result });
                    this.mergeActivities(result.activities);
                }
            } catch (error) {
                result = null;
                if (this.active && !isAbortError(error) && reportError) {
                    this.updateView({ error: readErrorMessage(error) });
                }
            } finally {
                this.abortControllers.delete(controller);
            }
        }
        return result;
    }

    private async backfill(allowReset: boolean): Promise<boolean> {
        let pageCursor = this.cursor;
        let changed = false;
        while (this.active) {
            let page: TaskActivityPage;
            try {
                const controller = this.createAbortController();
                try {
                    page = (
                        await this.api.getRunActivities(
                            this.taskId,
                            pageCursor,
                            controller.signal,
                        )
                    ).body;
                } finally {
                    this.abortControllers.delete(controller);
                }
            } catch (error) {
                if (allowReset && isCursorReset(error)) {
                    await this.resetCursor();
                    return this.backfill(false);
                }
                throw error;
            }
            changed = this.mergeActivities(page.items) || changed;
            const finalItem = page.items.at(-1);
            if (finalItem !== undefined) {
                this.cursor = finalItem.id;
            }
            if (page.next_cursor === null || page.next_cursor === undefined) {
                return changed;
            }
            pageCursor = page.next_cursor;
            this.cursor = pageCursor;
        }
        return changed;
    }

    private async resetCursor(): Promise<void> {
        const task = await this.readTask(false);
        if (task === null) {
            throw new Error("Could not reset the Run Activity cursor.");
        }
        this.seedActivities(task);
    }

    private seedActivities(task: TaskView): void {
        this.activities = [...task.activities];
        this.activityIds = new Set(
            this.activities.map((activity) => activity.id),
        );
        this.cursor = this.activities.at(-1)?.id ?? null;
        this.updateView({ activities: this.activities });
    }

    private mergeActivities(items: readonly TaskActivity[]): boolean {
        let changed = false;
        for (const activity of items) {
            if (!this.activityIds.has(activity.id)) {
                this.activityIds.add(activity.id);
                this.activities.push(activity);
                changed = true;
            }
        }
        if (changed && this.active) {
            this.updateView({ activities: [...this.activities] });
        }
        return changed;
    }

    private openStream(): void {
        if (!this.active) {
            return;
        }
        this.closeStream();
        const source = this.api.openRunActivityStream(this.taskId, this.cursor);
        const onOpen: EventListener = () => this.markLive();
        const onActivity: EventListener = (event) => this.handleActivity(event);
        const onTaskChanged: EventListener = (event) =>
            this.handleTaskChanged(event);
        const onError: EventListener = () => this.scheduleRecovery();
        source.addEventListener("open", onOpen);
        source.addEventListener("activity", onActivity);
        source.addEventListener("task_changed", onTaskChanged);
        source.addEventListener("error", onError);
        this.sourceCleanup = () => {
            source.removeEventListener("open", onOpen);
            source.removeEventListener("activity", onActivity);
            source.removeEventListener("task_changed", onTaskChanged);
            source.removeEventListener("error", onError);
            source.close();
        };
    }

    private handleActivity(event: Event): void {
        const activity = parseActivity(event);
        if (activity === null) {
            this.scheduleRecovery();
            return;
        }
        this.advanceCursor(event, activity.id);
        this.mergeActivities([activity]);
        this.refetchControllerTruth();
    }

    private handleTaskChanged(event: Event): void {
        this.advanceCursor(event);
        this.refetchControllerTruth();
    }

    private advanceCursor(event: Event, fallback: string | null = null): void {
        const eventCursor =
            event instanceof MessageEvent && event.lastEventId !== ""
                ? event.lastEventId
                : fallback;
        if (eventCursor !== null) {
            this.cursor = eventCursor;
        }
    }

    private refetchControllerTruth(): void {
        void this.readTask(false).then((task) => {
            if (this.active && task === null) {
                this.scheduleRecovery();
            }
        });
    }

    private markLive(): void {
        this.reconnectAttempt = 0;
        this.clearDelayedNoticeTimer();
        this.updateView({ liveDelayed: false });
    }

    private scheduleRecovery(immediate = false): void {
        if (!this.active) {
            return;
        }
        this.closeStream();
        this.scheduleDelayedNotice();
        if (this.reconnectTimer !== null) {
            return;
        }
        const delay = immediate ? 0 : this.nextReconnectDelay();
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            void this.recover();
        }, delay);
    }

    private async recover(): Promise<void> {
        try {
            if (
                (await this.backfill(true)) &&
                (await this.readTask(false)) === null
            ) {
                throw new Error("Could not refresh current Run state.");
            }
            this.openStream();
        } catch (error) {
            if (this.active && !isAbortError(error)) {
                this.scheduleRecovery();
            }
        }
    }

    private nextReconnectDelay(): number {
        const delay = Math.min(
            RECONNECT_BASE_MS * 2 ** this.reconnectAttempt,
            RECONNECT_MAX_MS,
        );
        this.reconnectAttempt += 1;
        return delay;
    }

    private scheduleDelayedNotice(): void {
        if (this.delayedNoticeTimer !== null) {
            return;
        }
        this.delayedNoticeTimer = setTimeout(() => {
            this.delayedNoticeTimer = null;
            if (this.active) {
                this.updateView({ liveDelayed: true });
            }
        }, LIVE_DELAY_NOTICE_MS);
    }

    private closeStream(): void {
        this.sourceCleanup?.();
        this.sourceCleanup = null;
    }

    private clearReconnectTimer(): void {
        if (this.reconnectTimer !== null) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }

    private clearDelayedNoticeTimer(): void {
        if (this.delayedNoticeTimer !== null) {
            clearTimeout(this.delayedNoticeTimer);
            this.delayedNoticeTimer = null;
        }
    }

    private createAbortController(): AbortController {
        const controller = new AbortController();
        this.abortControllers.add(controller);
        return controller;
    }
}

function parseActivity(event: Event): TaskActivity | null {
    if (!(event instanceof MessageEvent) || typeof event.data !== "string") {
        return null;
    }
    try {
        const value = JSON.parse(event.data) as unknown;
        return isActivity(value) ? value : null;
    } catch {
        return null;
    }
}

function isActivity(value: unknown): value is TaskActivity {
    return (
        typeof value === "object" &&
        value !== null &&
        "id" in value &&
        typeof value.id === "string" &&
        "kind" in value &&
        typeof value.kind === "string" &&
        "title" in value &&
        typeof value.title === "string"
    );
}

function isCursorReset(error: unknown): boolean {
    return error instanceof ApiResponseError && error.status === 410;
}

function isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError";
}

function readErrorMessage(error: unknown): string {
    return error instanceof Error
        ? error.message
        : "Banksia could not load this Run.";
}
