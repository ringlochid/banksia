import type { TaskView } from "./run-api";

type RunStatus = TaskView["status"];

export function runStatusLabel(status: RunStatus): string {
    switch (status) {
        case "starting":
            return "Starting";
        case "working":
            return "Working";
        case "waiting_for_you":
            return "Needs your attention";
        case "paused":
            return "Paused";
        case "completed":
            return "Completed";
        case "blocked":
            return "Blocked";
        case "cancelled":
            return "Cancelled";
    }
}

export function formatRunDate(value: string): string {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) {
        return value;
    }
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(parsed);
}

export function isRunActive(status: RunStatus): boolean {
    return (
        status === "starting" ||
        status === "working" ||
        status === "waiting_for_you"
    );
}

export function errorMessage(error: unknown): string {
    return error instanceof Error
        ? error.message
        : "Banksia could not load this information.";
}
