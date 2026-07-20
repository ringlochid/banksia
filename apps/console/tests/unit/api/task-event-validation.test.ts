import { describe, expect, it } from "vitest";

import { isTaskEventRecord } from "../../../src/api/task-event-validation";
import { TEST_UPDATED_AT, createTaskEventRecord } from "../../fixtures/console-api";

describe("task-event validation", () => {
    it("accepts exact known event variants", () => {
        expect(isTaskEventRecord(createTaskEventRecord())).toBe(true);
        expect(isTaskEventRecord(createAbandonedCommandEvent())).toBe(true);
        expect(isTaskEventRecord(createWorkPlanEvent())).toBe(true);
        expect(isTaskEventRecord(createDispatchStartEvent("accepted"))).toBe(true);
        expect(
            isTaskEventRecord(
                createDispatchStartEvent("retry_scheduled", {
                    last_error_code: "provider_error",
                    next_attempt_at: TEST_UPDATED_AT,
                    retry_kind: "definite_failure",
                }),
            ),
        ).toBe(true);
    });

    it("rejects event and terminal-state discriminant mismatches", () => {
        expect(
            isTaskEventRecord({
                ...createAbandonedCommandEvent(),
                payload: {
                    ...createAbandonedCommandEvent().payload,
                    state: "succeeded",
                },
            }),
        ).toBe(false);
        expect(
            isTaskEventRecord({
                ...createAbandonedCommandEvent(),
                payload: {
                    ...createAbandonedCommandEvent().payload,
                    failure_code: "process_failed",
                },
            }),
        ).toBe(false);
        expect(
            isTaskEventRecord(
                createHumanTerminalEvent("human_request_resolved", "timed_out", "timed_out"),
            ),
        ).toBe(false);
    });

    it("rejects malformed array items, enum values, and extra payload fields", () => {
        expect(
            isTaskEventRecord({
                ...createWorkPlanEvent(),
                payload: {
                    ...createWorkPlanEvent().payload,
                    steps: [{ status: "queued", step: "Implement the API boundary." }],
                },
            }),
        ).toBe(false);
        expect(
            isTaskEventRecord({
                ...createWorkPlanEvent(),
                payload: {
                    ...createWorkPlanEvent().payload,
                    steps: ["not-a-step-record"],
                },
            }),
        ).toBe(false);
        expect(
            isTaskEventRecord({
                ...createWorkPlanEvent(),
                payload: {
                    ...createWorkPlanEvent().payload,
                    provider_output: "not a bounded task-event field",
                },
            }),
        ).toBe(false);
    });

    it("rejects malformed optional fields, dates, and envelope extras", () => {
        const humanRequestOpened = createHumanRequestOpenedEvent();

        expect(
            isTaskEventRecord({
                ...humanRequestOpened,
                payload: { ...humanRequestOpened.payload, due_at: 123 },
            }),
        ).toBe(false);
        expect(
            isTaskEventRecord({
                ...humanRequestOpened,
                occurred_at: "not-a-date",
            }),
        ).toBe(false);
        expect(
            isTaskEventRecord({
                ...humanRequestOpened,
                provider_session_id: "private-session",
            }),
        ).toBe(false);
    });

    it("enforces checkpoint and provider-start cross-field rules", () => {
        expect(isTaskEventRecord(createCheckpointEvent("progress", "green"))).toBe(false);
        expect(isTaskEventRecord(createCheckpointEvent("terminal", null))).toBe(false);
        expect(
            isTaskEventRecord(
                createDispatchStartEvent("accepted", {
                    last_error_code: "provider_error",
                    next_attempt_at: TEST_UPDATED_AT,
                    retry_kind: "definite_failure",
                }),
            ),
        ).toBe(false);
        expect(isTaskEventRecord(createDispatchStartEvent("retry_scheduled"))).toBe(false);
    });
});

interface TestEvent extends Record<string, unknown> {
    readonly payload: Record<string, unknown>;
}

function createEvent(eventType: string, payload: Record<string, unknown>): TestEvent {
    return {
        ...createTaskEventRecord(),
        event_type: eventType,
        payload,
    };
}

function createAbandonedCommandEvent(): TestEvent {
    return createEvent("command_run_abandoned", {
        ended_at: TEST_UPDATED_AT,
        failure_code: "command_ownership_lost",
        log_refs: ["_runtime/command-runs/run-001.log"],
        ownership_revision: 2,
        run_id: "run-001",
        source_dispatch_id: "dispatch-001",
        state: "abandoned",
        summary: "Exact process ownership was lost after restart.",
    });
}

function createWorkPlanEvent(): TestEvent {
    return createEvent("work_plan_set", {
        assignment_id: "assignment-001",
        authored_by_dispatch_id: "dispatch-001",
        explanation: null,
        revision: 1,
        steps: [{ status: "in_progress", step: "Implement the API boundary." }],
        updated_at: TEST_UPDATED_AT,
    });
}

function createHumanRequestOpenedEvent(): TestEvent {
    return createEvent("human_request_opened", {
        due_at: null,
        kind: "direction",
        opened_at: TEST_UPDATED_AT,
        request_id: "request-001",
        source_dispatch_id: "dispatch-001",
        summary: "Choose the target direction.",
    });
}

function createHumanTerminalEvent(
    eventType: string,
    status: string,
    resolutionKind: string,
): Record<string, unknown> {
    return createEvent(eventType, {
        due_at: null,
        kind: "direction",
        request_id: "request-001",
        resolution_kind: resolutionKind,
        resolution_summary: "The request became terminal.",
        resolved_at: TEST_UPDATED_AT,
        resolved_by_actor_ref: null,
        resolved_by_surface: "controller",
        source_dispatch_id: "dispatch-001",
        status,
        summary: "Choose the target direction.",
    });
}

function createCheckpointEvent(
    checkpointKind: string,
    outcome: string | null,
): Record<string, unknown> {
    return createEvent("checkpoint_recorded", {
        assignment_id: "assignment-001",
        attempt_id: "attempt-001",
        authored_by_dispatch_id: "dispatch-001",
        checkpoint_id: "checkpoint-001",
        checkpoint_kind: checkpointKind,
        checkpoint_ref: "_runtime/checkpoints/checkpoint-001.json",
        outcome,
        produced_artifacts: [],
        summary: "Checkpoint recorded.",
        transient_surfaces: [],
    });
}

function createDispatchStartEvent(
    state: string,
    retryFields: Readonly<Record<string, unknown>> = {},
): Record<string, unknown> {
    return createEvent("dispatch_start_updated", {
        attempt_count: 1,
        dispatch_id: "dispatch-001",
        provider_start_revision: 1,
        state,
        ...retryFields,
    });
}
