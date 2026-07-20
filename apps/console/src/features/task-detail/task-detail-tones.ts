import type { StatusTone } from "../../components/ui";
import type { components } from "../../api/generated/openapi";

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

export function checkpointOutcomeTone(outcome: string | null): StatusTone {
    switch (outcome) {
        case "green":
            return "success";
        case "blocked":
            return "danger";
        case "retry":
            return "warning";
        default:
            return "neutral";
    }
}
