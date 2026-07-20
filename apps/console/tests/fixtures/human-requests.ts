import type { components } from "../../src/api/generated/openapi";

export const HUMAN_REQUEST_TASK_ID = "task-runtime-copy-refresh";
export const HUMAN_REQUEST_RESOLVED_AT = "2026-06-29T15:45:00Z";

type HumanRequestItem = components["schemas"]["HumanRequestItem"];
type HumanRequestRead = components["schemas"]["HumanRequestRead"];
type HumanRequestResolution = components["schemas"]["HumanRequestResolution"];
type HumanRequestStatus = components["schemas"]["HumanRequestStatus"];
type PendingHumanRequest = components["schemas"]["PendingHumanRequest"];
type ResolveItemResponses = components["schemas"]["HumanRequestResolveRequest"]["item_responses"];

export function createHumanRequestPageList(): components["schemas"]["HumanRequestListResponse"] {
    return {
        items: [
            createHumanRequestRead({
                items: [
                    createOptionItem({
                        id: "due_handling",
                        prompt: "If this request reaches its due time unanswered, what should the controller do?",
                        options: [
                            {
                                description:
                                    "Continue with the safe fallback after the due time passes.",
                                id: "use-fallback",
                                title: "Use due fallback",
                            },
                            {
                                description: "Leave the request open and wait for a direct answer.",
                                id: "keep-waiting",
                                title: "Keep waiting",
                            },
                            {
                                description:
                                    "Close the human wait and return control to task review.",
                                id: "cancel-wait",
                                title: "Cancel this wait",
                            },
                        ],
                    }),
                    createOptionItem({
                        id: "next_scope",
                        prompt: "What should the next worker handle after this answer?",
                        options: [
                            {
                                description:
                                    "Keep the next pass limited to the human-request branch.",
                                id: "current-request",
                                title: "Current request only",
                            },
                            {
                                description:
                                    "Let the worker verify the surrounding task state before continuing.",
                                id: "whole-task",
                                title: "Whole task check",
                            },
                            {
                                description: "Record the answer but stop before the next dispatch.",
                                id: "pause-after-answer",
                                title: "Pause after answer",
                            },
                        ],
                    }),
                    createOptionItem({
                        id: "next_context",
                        prompt: "How much of this answer should be included for the next worker?",
                        options: [
                            {
                                description:
                                    "Pass the selected answer without extra operator context.",
                                id: "answer-only",
                                title: "Answer only",
                            },
                            {
                                description:
                                    "Include the request summary so the next worker has local context.",
                                id: "answer-and-summary",
                                title: "Answer and summary",
                            },
                            {
                                description:
                                    "Include every response and the controller timing fields.",
                                id: "full-request",
                                title: "Full request",
                            },
                        ],
                    }),
                ],
                kind: "direction",
                opened_at: "2026-06-20T19:12:00Z",
                request_id: "direction-due-handling",
                source_dispatch_id: "dispatch-direction-due-handling",
                summary: "Choose due handling",
                timeout: {
                    default_behavior: "Use the safe fallback after the due time.",
                    due_at: "2026-06-20T19:57:00Z",
                },
            }),
            createHumanRequestRead({
                items: [
                    createOptionItem({
                        id: "file_write",
                        prompt: "Can the worker write the generated task artifacts?",
                        options: [
                            {
                                description: "Allow the named writes and continue the task.",
                                id: "approve",
                                title: "Approve",
                            },
                            {
                                description:
                                    "Permit only the listed artifacts and reject extra file changes.",
                                id: "approve-limited",
                                title: "Approve named files only",
                            },
                            {
                                description: "Do not write files until the request is narrowed.",
                                id: "reject",
                                title: "Reject for now",
                            },
                        ],
                    }),
                ],
                kind: "approval",
                opened_at: "2026-06-20T18:49:00Z",
                request_id: "approval-generated-files",
                source_dispatch_id: "dispatch-approval-generated-files",
                summary: "Approve generated file writes",
                timeout: {
                    default_behavior: "Block the write until explicit approval arrives.",
                    due_at: "2026-06-20T20:10:00Z",
                },
            }),
            createHumanRequestRead({
                items: [
                    {
                        id: "handoff_payload",
                        prompt: "Enter the payload the controller should attach to the next dispatch.",
                        response_schema: {
                            properties: {
                                constraint: {
                                    title: "Constraint",
                                    type: "string",
                                },
                                expected_output: {
                                    title: "Expected output",
                                    type: "string",
                                },
                                target_node: {
                                    title: "Target node",
                                    type: "string",
                                },
                            },
                            required: ["target_node", "expected_output"],
                            type: "object",
                        },
                    },
                ],
                kind: "input",
                opened_at: "2026-06-20T18:27:00Z",
                request_id: "input-handoff-fields",
                source_dispatch_id: "dispatch-input-handoff-fields",
                summary: "Provide handoff fields",
                timeout: {
                    default_behavior: "Block until the missing fields are supplied.",
                    due_at: "2026-06-20T21:00:00Z",
                },
            }),
            createHumanRequestRead({
                items: [
                    createOptionItem({
                        id: "validation_result",
                        prompt: "Is the latest validation evidence sufficient?",
                        options: [
                            {
                                description:
                                    "Record the result and let the controller close the request.",
                                id: "accept",
                                title: "Accept evidence",
                            },
                            {
                                description:
                                    "Keep the request open and ask for another validation pass.",
                                id: "request-more-evidence",
                                title: "Request more evidence",
                            },
                            {
                                description:
                                    "Return the task for correction before another review.",
                                id: "reject-evidence",
                                title: "Reject evidence",
                            },
                        ],
                    }),
                ],
                kind: "review",
                opened_at: "2026-06-20T17:58:00Z",
                request_id: "review-validation",
                source_dispatch_id: "dispatch-review-validation",
                summary: "Review validation result",
                timeout: {
                    default_behavior: "Return to the reviewer with no acceptance.",
                    due_at: "2026-06-20T21:30:00Z",
                },
            }),
            createTerminalHumanRequestRead("resolved"),
            createTerminalHumanRequestRead("cancelled"),
            createTerminalHumanRequestRead("timed_out"),
        ],
        task_id: HUMAN_REQUEST_TASK_ID,
    };
}

export function createHumanRequestRead(
    overrides: Partial<PendingHumanRequest> = {},
    resolution: HumanRequestResolution | null = null,
): HumanRequestRead {
    const requestId = overrides.request_id ?? "hr-direction";
    return {
        request: {
            context_refs: [],
            items: [
                createOptionItem({
                    id: "default-item",
                    options: [
                        {
                            description: "Proceed with the focused page implementation.",
                            id: "proceed",
                            title: "Proceed",
                        },
                    ],
                    prompt: "Choose how the worker should continue.",
                }),
            ],
            kind: "direction",
            opened_at: "2026-06-29T15:12:00Z",
            request_id: requestId,
            source_dispatch_id: `dispatch-${requestId}`,
            status: "open",
            suggested_human_instruction:
                "Answer the active item, then resolve the request when the controller can continue without guessing.",
            summary: "Review requested",
            task_id: HUMAN_REQUEST_TASK_ID,
            timeout: {
                default_behavior: "Block until the operator answers.",
                due_at: "2026-06-29T17:00:00Z",
            },
            ...overrides,
            assignment_id: overrides.assignment_id ?? `assignment-${requestId}`,
            attempt_id: overrides.attempt_id ?? `attempt-${requestId}`,
            flow_id: overrides.flow_id ?? "flow-human-requests",
        },
        resolution,
    };
}

export function createAnsweredHumanRequestResolution(
    request: PendingHumanRequest,
    itemResponses: ResolveItemResponses = defaultItemResponses(request),
): HumanRequestResolution {
    return {
        item_responses: itemResponses,
        policy_basis: { policy_basis: "task_authorized_human_request_resolution" },
        request_id: request.request_id,
        resolution_kind: "answered",
        resolved_at: HUMAN_REQUEST_RESOLVED_AT,
        resolved_by_actor_ref: "local_operator",
        resolved_by_surface: "control_api",
        summary: "Human answered the controller-owned request.",
        task_id: request.task_id,
    };
}

export function createHumanRequestResolveResponse(
    request: PendingHumanRequest,
    itemResponses?: ResolveItemResponses,
): components["schemas"]["HumanRequestResolveResponse"] {
    return {
        resolution: createAnsweredHumanRequestResolution(request, itemResponses),
        task_id: request.task_id,
    };
}

function createOptionItem({
    id,
    options,
    prompt,
}: {
    readonly id: string;
    readonly options: NonNullable<HumanRequestItem["options"]>;
    readonly prompt: string;
}): HumanRequestItem {
    return {
        id,
        options,
        prompt,
    };
}

function defaultItemResponses(request: PendingHumanRequest): ResolveItemResponses {
    const firstItem = request.items[0];
    return {
        [firstItem.id]: firstItem.options?.[0]?.id ?? {},
    };
}

function createTerminalHumanRequestRead(
    status: Exclude<HumanRequestStatus, "open">,
): HumanRequestRead {
    const request = createHumanRequestRead({
        kind: status === "cancelled" ? "approval" : status === "timed_out" ? "direction" : "review",
        opened_at:
            status === "resolved"
                ? "2026-06-20T16:48:00Z"
                : status === "timed_out"
                  ? "2026-06-20T14:10:00Z"
                  : "2026-06-20T15:30:00Z",
        request_id:
            status === "resolved"
                ? "review-evidence-accepted"
                : status === "timed_out"
                  ? "direction-due-elapsed"
                  : "approval-write-cancelled",
        status,
        summary:
            status === "resolved"
                ? "Validation evidence accepted"
                : status === "timed_out"
                  ? "Due window elapsed"
                  : "Write approval withdrawn",
    }).request;

    const resolutionKind = status === "resolved" ? "answered" : status;
    const resolution: HumanRequestResolution = {
        item_responses:
            resolutionKind === "answered"
                ? { [request.items[0]?.id ?? "default-item"]: "proceed" }
                : null,
        policy_basis:
            resolutionKind === "timed_out" ? { default_behavior: "return_to_review" } : null,
        request_id: request.request_id,
        resolution_kind: resolutionKind,
        resolved_at:
            status === "resolved"
                ? "2026-06-20T17:03:00Z"
                : status === "timed_out"
                  ? "2026-06-20T14:55:00Z"
                  : "2026-06-20T15:41:00Z",
        resolved_by_actor_ref: resolutionKind === "cancelled" ? null : "local_operator",
        resolved_by_surface: resolutionKind === "timed_out" ? "controller" : "control_api",
        summary:
            resolutionKind === "answered"
                ? "Reviewer accepted the validation evidence."
                : resolutionKind === "timed_out"
                  ? "The request reached its controller-owned deadline."
                  : "Task cancellation withdrew the request.",
        task_id: request.task_id,
    };

    return { request, resolution };
}
