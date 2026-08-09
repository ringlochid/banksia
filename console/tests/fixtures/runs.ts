import type {
    ControllerResponse,
    ProductEventSource,
} from "../../src/api/client";
import type {
    CommandRunOutputPage,
    HumanRequestResponseReceipt,
    MemberSteerReceipt,
    RunApi,
    TaskActivityPage,
    TaskSearchResponse,
    TaskStartReceipt,
    TaskView,
    WorkflowSearchResponse,
} from "../../src/features/runs/run-api";

export const TEST_TASK_ID = "t_7m4k2d9x";

export function taskFixture(overrides: Partial<TaskView> = {}): TaskView {
    return {
        id: TEST_TASK_ID,
        prompt_excerpt: "Compare the release candidates and recommend one.",
        workflow: {
            id: "production-feature-delivery",
            description: "Complete work with independent review.",
        },
        status: "waiting_for_you",
        status_message: "The team needs one decision before continuing.",
        started_at: "2026-07-26T01:00:00Z",
        updated_at: "2026-07-26T01:10:00Z",
        team: {
            id: "member-lead",
            name: "Delivery lead",
            purpose: "Own the recommendation.",
            state: "waiting",
            latest_update: null,
            plan: {
                explanation: "Compare, review, then integrate.",
                updated_at: "2026-07-26T01:02:00Z",
                steps: [
                    { text: "Compare candidates", status: "completed" },
                    {
                        text: "Resolve the final choice",
                        status: "in_progress",
                    },
                ],
            },
            children: [
                {
                    id: "member-review",
                    name: "Independent reviewer",
                    purpose: "Challenge the evidence.",
                    state: "done",
                    latest_update: {
                        summary: "Independent review is complete.",
                        occurred_at: "2026-07-26T01:08:00Z",
                        files: [
                            {
                                path: ".banksia/t_7m4k2d9x/artifacts/review.md",
                                description: "Independent findings.",
                            },
                        ],
                    },
                    plan: {
                        explanation:
                            "Challenge the recommendation independently.",
                        updated_at: "2026-07-26T01:06:00Z",
                        steps: [
                            {
                                text: "Inspect the supporting evidence",
                                status: "completed",
                            },
                            {
                                text: "Report material weaknesses",
                                status: "completed",
                            },
                        ],
                    },
                    children: [],
                },
            ],
        },
        attention: [
            {
                id: "attention-one",
                kind: "human_request",
                title: "Choose the release priority",
                summary: "The team needs your priority.",
                member: { id: "member-lead", name: "Delivery lead" },
                files: [],
                action: null,
                link: null,
            },
        ],
        actions: [
            {
                id: "action-pause",
                kind: "pause",
                label: "Pause Run",
                href: `/api/tasks/${TEST_TASK_ID}/controls/action-pause`,
                input_schema: null,
                confirmation: {
                    required: false,
                    title: "Pause this Run?",
                    consequence:
                        "The team will stop starting new work until resumed.",
                },
            },
            {
                id: "action-cancel",
                kind: "cancel",
                label: "Cancel Run",
                href: `/api/tasks/${TEST_TASK_ID}/controls/action-cancel`,
                input_schema: null,
                confirmation: {
                    required: true,
                    title: "Cancel this Run?",
                    consequence:
                        "The team will stop and cannot be resumed afterward.",
                },
            },
        ],
        activities: [
            {
                id: "activity-one",
                kind: "task_started",
                occurred_at: "2026-07-26T01:00:00Z",
                title: "Run started",
                summary: "The Delivery team accepted the work.",
                member: null,
                outcome: null,
                files: [],
                action: null,
            },
        ],
        activities_href: `/api/tasks/${TEST_TASK_ID}/activities`,
        activities_truncated: false,
        human_requests: [
            {
                id: "request-one",
                kind: "direction",
                summary: "Choose the release priority",
                status: "open",
                opened_at: "2026-07-26T01:09:00Z",
                due_at: null,
                member: { id: "member-lead", name: "Delivery lead" },
                files: [],
                resolution: null,
                items: [
                    {
                        id: "priority",
                        prompt: "Which outcome matters most?",
                        allow_other: true,
                        allow_skip: false,
                        response_schema: null,
                        options: [
                            {
                                id: "reliability",
                                title: "Reliability",
                                description:
                                    "Prefer the lowest operational risk.",
                            },
                            {
                                id: "speed",
                                title: "Speed",
                                description: "Prefer the fastest delivery.",
                            },
                        ],
                    },
                ],
                action: {
                    id: "answer-request",
                    kind: "answer",
                    label: "Submit response",
                    href: `/api/tasks/${TEST_TASK_ID}/human-requests/request-one/responses`,
                    input_schema: null,
                    confirmation: {
                        required: false,
                        title: "Submit response?",
                        consequence: "The team can use this answer.",
                    },
                },
                cancel_action: {
                    id: "cancel-request",
                    kind: "cancel",
                    label: "Cancel request",
                    href: `/api/tasks/${TEST_TASK_ID}/human-requests/request-one/responses`,
                    input_schema: null,
                    confirmation: {
                        required: true,
                        title: "Cancel this request?",
                        consequence:
                            "The team will continue without this answer.",
                    },
                },
            },
        ],
        human_request_count: 1,
        human_requests_truncated: false,
        command_runs: [
            {
                id: "c_q3m8y1ka",
                purpose: "Run the release verification suite",
                state: "running",
                member: { id: "member-review", name: "Independent reviewer" },
                created_at: "2026-07-26T01:03:00Z",
                started_at: "2026-07-26T01:03:02Z",
                ended_at: null,
                elapsed_seconds: 420,
                outcome_summary: null,
                output_complete: false,
                output_href: `/api/tasks/${TEST_TASK_ID}/command-runs/c_q3m8y1ka/output`,
                cancel_action: {
                    id: "cancel-command",
                    kind: "cancel",
                    label: "Cancel action",
                    href: `/api/tasks/${TEST_TASK_ID}/command-runs/c_q3m8y1ka/cancel`,
                    input_schema: null,
                    confirmation: {
                        required: true,
                        title: "Cancel this Action?",
                        consequence:
                            "The verification process will be asked to stop.",
                    },
                },
            },
        ],
        command_run_count: 1,
        command_runs_truncated: false,
        result: null,
        ...overrides,
    };
}

export function taskSearchFixture(): TaskSearchResponse {
    const task = taskFixture();
    return {
        items: [
            {
                id: task.id,
                prompt_excerpt: task.prompt_excerpt,
                workflow: task.workflow,
                status: task.status,
                status_message: task.status_message,
                attention_count: task.attention.length,
                result_status: null,
                started_at: task.started_at,
                updated_at: task.updated_at,
            },
        ],
        next_cursor: null,
    };
}

export function workflowSearchFixture(): WorkflowSearchResponse {
    return {
        items: [
            {
                workflow_id: "production-feature-delivery",
                description: "Complete work with independent review.",
                state: "published",
                updated_at: "2026-07-25T23:00:00Z",
                provenance: "user",
                published_revision_no: 3,
                has_retired_provider_selection: false,
                available_actions: ["edit", "start_run", "remove"],
            },
        ],
        next_cursor: null,
    };
}

export function taskStartReceiptFixture(): TaskStartReceipt {
    return {
        task_id: TEST_TASK_ID,
        workflow_id: "production-feature-delivery",
        workflow_revision: 3,
        workspace: "/workspace/project",
        manifest: `.banksia/${TEST_TASK_ID}/manifest.md`,
        receipt_id: "receipt-start",
        status: "accepted",
        status_message:
            "The Run was accepted. Work starts asynchronously and may still need attention.",
    };
}

export function humanResponseReceiptFixture(): HumanRequestResponseReceipt {
    const request = taskFixture().human_requests[0];
    if (request === undefined) {
        throw new Error("Expected Human Request fixture");
    }
    return {
        receipt_id: "receipt-answer",
        continuation_pending: true,
        status_message: "Your response was accepted.",
        request: {
            ...request,
            status: "answered",
            resolution: {
                status: "answered",
                summary: "Reliability selected.",
                resolved_at: "2026-07-26T01:12:00Z",
            },
        },
    };
}

export function memberSteerReceiptFixture(task: TaskView): MemberSteerReceipt {
    return {
        receipt_id: "receipt-steer",
        status: "delivered",
        status_message: "The Member was steered.",
        task,
    };
}

export function commandOutputFixture(): CommandRunOutputPage {
    return {
        command_id: "c_q3m8y1ka",
        content: "checking release\nall focused checks passed\n",
        is_bounded: true,
        is_changed: false,
        is_missing: false,
        output_complete: false,
        next_cursor: null,
    };
}

export function response<T>(body: T, status = 200): ControllerResponse<T> {
    return { body, etag: null, status };
}

export function activityPageFixture(): TaskActivityPage {
    return { items: [], next_cursor: null };
}

export function runApiStub(overrides: Partial<RunApi>): RunApi {
    const unavailable = (): never => {
        throw new Error("Unexpected Run API call");
    };
    return {
        searchRuns: unavailable,
        searchWorkflows: unavailable,
        startRun: unavailable,
        getRun: unavailable,
        getRunActivities: () =>
            Promise.resolve(response(activityPageFixture())),
        openRunActivityStream: () => inactiveEventSource(),
        controlRun: unavailable,
        steerMember: unavailable,
        respondToHumanRequest: unavailable,
        cancelCommandRun: unavailable,
        getCommandOutput: unavailable,
        ...overrides,
    };
}

function inactiveEventSource(): ProductEventSource {
    return {
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        close: () => undefined,
    };
}
