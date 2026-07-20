import type { StatusTone } from "../components/ui";
import type { components } from "./generated/openapi";

export type RuntimeLifecycleStatus = components["schemas"]["RuntimeLifecycleStatus"];
export type RuntimeFlowTerminalOutcome = components["schemas"]["RuntimeFlowTerminalOutcome"];

export interface TaskOutcome {
    readonly isBlocked: boolean;
    readonly isTerminal: boolean;
    readonly label: string;
    readonly tone: StatusTone;
}

/**
 * User-facing task outcome. The controller separates lifecycle status from
 * terminal outcome: `completed` means the runtime ended, and only
 * `terminal_outcome` says whether the work succeeded (`green`) or ended
 * blocked. Every status badge must render this, never the raw lifecycle word.
 */
export function taskOutcome(
    status: RuntimeLifecycleStatus,
    terminalOutcome: RuntimeFlowTerminalOutcome | null | undefined,
): TaskOutcome {
    switch (status) {
        case "completed":
            if (terminalOutcome === "blocked") {
                return { isBlocked: true, isTerminal: true, label: "Blocked", tone: "danger" };
            }
            return { isBlocked: false, isTerminal: true, label: "Completed", tone: "success" };
        case "cancelled":
            return { isBlocked: false, isTerminal: true, label: "Cancelled", tone: "neutral" };
        case "running":
            return { isBlocked: false, isTerminal: false, label: "Running", tone: "active" };
        case "paused":
            return { isBlocked: false, isTerminal: false, label: "Paused", tone: "warning" };
        case "pending":
            return { isBlocked: false, isTerminal: false, label: "Pending", tone: "neutral" };
    }
}
