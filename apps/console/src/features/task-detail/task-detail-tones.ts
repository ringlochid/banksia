import type { StatusTone } from "../../components/ui";
import type { components } from "../../api/generated/openapi";
import type { TaskEventType } from "../../api/view-models";

export function flowStatusTone(
    status: components["schemas"]["RuntimeLifecycleStatus"],
): StatusTone {
    switch (status) {
        case "running":
            return "active";
        case "completed":
            return "success";
        case "cancelled":
            return "danger";
        case "paused":
        case "pending":
            return "warning";
    }
}

export function commandRunTone(status: components["schemas"]["CommandRunState"]): StatusTone {
    switch (status) {
        case "running":
        case "cancellation_requested":
            return "active";
        case "succeeded":
            return "success";
        case "failed":
        case "timed_out":
        case "cancelled":
        case "abandoned":
            return "danger";
        case "pending_start":
            return "warning";
    }
}

export function humanRequestTone(status: components["schemas"]["HumanRequestStatus"]): StatusTone {
    switch (status) {
        case "open":
            return "warning";
        case "resolved":
            return "success";
        case "cancelled":
        case "timed_out":
            return "danger";
    }
}

export function taskEventTone(eventType: TaskEventType): StatusTone {
    if (
        eventType === "command_run_abandoned" ||
        eventType === "command_run_failed" ||
        eventType === "command_run_timed_out" ||
        eventType.endsWith("cancelled")
    ) {
        return "danger";
    }
    if (eventType.includes("succeeded") || eventType === "boundary_accepted") {
        return "success";
    }
    if (eventType.includes("human_request") || eventType.includes("checkpoint")) {
        return "warning";
    }
    return "active";
}
