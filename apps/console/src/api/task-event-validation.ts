import type { components } from "./generated/openapi";

export type TaskEventRecord = components["schemas"]["TaskEventRecord"];

type TaskEventType = TaskEventRecord["event_type"];
type UnknownRecord = Record<string, unknown>;
type UnknownValidator = (value: unknown) => boolean;

const isIdentifier = acceptsBoundedText(255);
const isRef = acceptsBoundedText(2_048);
const isSummary = acceptsBoundedText(4_096);
const isStepText = acceptsBoundedText(512);
const isTaskIdentifier = acceptsNonEmptyText;
const isInteger = acceptsIntegerAtLeast(Number.MIN_SAFE_INTEGER);
const isNonNegativeInteger = acceptsIntegerAtLeast(0);
const isPositiveInteger = acceptsIntegerAtLeast(1);

const isTaskEventSource = acceptsEnumValue([
    "controller",
    "control_api",
    "operator_mcp",
    "node",
] as const);
const isCheckpointKind = acceptsEnumValue(["progress", "terminal"] as const);
const isCheckpointOutcome = acceptsEnumValue(["green", "retry", "blocked"] as const);
const isBoundaryOutcome = acceptsEnumValue(["yield", "green", "retry", "blocked"] as const);
const isCommandProgressState = acceptsEnumValue(["running", "cancellation_requested"] as const);
const isDispatchOpenedReason = acceptsEnumValue([
    "root",
    "boundary",
    "child_return",
    "human_result",
    "command_result",
    "watchdog_recovery",
    "semantic_retry",
    "operator_continue",
] as const);
const isHumanRequestKind = acceptsEnumValue(["direction", "approval", "input", "review"] as const);
const isHumanResolutionSurface = acceptsEnumValue([
    "control_api",
    "control_ui",
    "operator_mcp",
    "controller",
] as const);
const isPauseReason = acceptsEnumValue([
    "paused_by_operator",
    "runtime_recovery_exhausted",
    "runtime_transition_failed",
] as const);
const isProvider = acceptsEnumValue(["codex", "claude", "openclaw"] as const);
const isProviderStartRetryKind = acceptsEnumValue([
    "initial",
    "definite_failure",
    "uncertain_acceptance",
] as const);
const isStructuralOperation = acceptsEnumValue([
    "add_child",
    "update_child",
    "remove_child",
] as const);
const isWorkPlanStepStatus = acceptsEnumValue(["pending", "in_progress", "completed"] as const);

const isNullableIdentifier = acceptsNullable(isIdentifier);
const isNullableRef = acceptsNullable(isRef);
const isNullableSummary = acceptsNullable(isSummary);
const isNullableDateTime = acceptsNullable(acceptsDateTime);
const isNullableInteger = acceptsNullable(isInteger);
const isNullablePositiveInteger = acceptsNullable(isPositiveInteger);

const isWorkPlanSteps = acceptsArray(isWorkPlanStep, 1, 9);
const isArtifactRefs = acceptsArray(isArtifactRef, 0, 32);
const isTransientRefs = acceptsArray(isTransientRef, 0, 32);
const isLogRefs = acceptsArray(isRef, 0, 2);

const taskEventPayloadValidators = {
    boundary_accepted: isBoundaryAcceptedPayload,
    checkpoint_recorded: isCheckpointRecordedPayload,
    child_assignment_committed: isChildAssignmentPayload,
    child_assignment_staged: isChildAssignmentPayload,
    command_run_abandoned: (value: unknown) => isCommandRunTerminalPayload(value, "abandoned"),
    command_run_cancel_requested: isCommandRunCancelRequestedPayload,
    command_run_cancelled: (value: unknown) => isCommandRunTerminalPayload(value, "cancelled"),
    command_run_failed: (value: unknown) => isCommandRunTerminalPayload(value, "failed"),
    command_run_opened: isCommandRunOpenedPayload,
    command_run_progressed: isCommandRunProgressedPayload,
    command_run_started: isCommandRunStartedPayload,
    command_run_succeeded: (value: unknown) => isCommandRunTerminalPayload(value, "succeeded"),
    command_run_timed_out: (value: unknown) => isCommandRunTerminalPayload(value, "timed_out"),
    dispatch_opened: isDispatchOpenedPayload,
    dispatch_start_updated: isDispatchStartUpdatedPayload,
    human_request_cancelled: (value: unknown) =>
        isHumanRequestTerminalPayload(value, "cancelled", "cancelled"),
    human_request_opened: isHumanRequestOpenedPayload,
    human_request_resolved: (value: unknown) =>
        isHumanRequestTerminalPayload(value, "resolved", "answered"),
    human_request_timed_out: (value: unknown) =>
        isHumanRequestTerminalPayload(value, "timed_out", "timed_out"),
    structural_revision_adopted: isStructuralRevisionAdoptedPayload,
    task_cancelled: isTaskControlPayload,
    task_paused: isTaskPausedPayload,
    task_resumed: isTaskControlPayload,
    task_started: isTaskStartedPayload,
    work_plan_cleared: isWorkPlanClearedPayload,
    work_plan_set: isWorkPlanSetPayload,
} satisfies Record<TaskEventType, UnknownValidator>;

export function isTaskEventRecord(value: unknown): value is TaskEventRecord {
    if (!isRecord(value) || !isTaskEventType(value.event_type)) {
        return false;
    }

    return matchesExactRecord(
        value,
        {
            event_hash: isRef,
            event_id: isIdentifier,
            event_seq: isPositiveInteger,
            event_source: isTaskEventSource,
            event_type: isTaskEventType,
            occurred_at: acceptsDateTime,
            payload: taskEventPayloadValidators[value.event_type],
            task_id: isTaskIdentifier,
        },
        {
            actor_ref: isNullableIdentifier,
            attempt_id: isNullableIdentifier,
            dispatch_id: isNullableIdentifier,
            flow_revision_id: isNullableIdentifier,
            node_key: isNullableIdentifier,
            prev_event_hash: isNullableRef,
        },
    );
}

function isTaskStartedPayload(value: unknown): boolean {
    return matchesExactRecord(value, {
        compiled_plan_id: isIdentifier,
        flow_id: isIdentifier,
        manifest_ref: isRef,
        workflow_key: isIdentifier,
        workflow_revision_no: isPositiveInteger,
    });
}

function isDispatchOpenedPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            assignment_id: isIdentifier,
            attempt_id: isIdentifier,
            dispatch_id: isIdentifier,
            input_ref: isRef,
            instructions_ref: isRef,
            node_key: isIdentifier,
            opened_reason: isDispatchOpenedReason,
            requested_provider: isProvider,
            resolved_provider: isProvider,
            selection_basis: acceptsEnumValue(["explicit", "default"] as const),
            status: acceptsLiteral("starting"),
        },
        { predecessor_dispatch_id: isNullableIdentifier },
    );
}

function isDispatchStartUpdatedPayload(value: unknown): boolean {
    if (
        !matchesExactRecord(
            value,
            {
                attempt_count: isPositiveInteger,
                dispatch_id: isIdentifier,
                provider_start_revision: isNonNegativeInteger,
                state: acceptsEnumValue(["retry_scheduled", "accepted"] as const),
            },
            {
                last_error_code: isNullableIdentifier,
                next_attempt_at: isNullableDateTime,
                retry_kind: acceptsNullable(isProviderStartRetryKind),
            },
        )
    ) {
        return false;
    }

    if (value.state === "accepted") {
        return (
            isMissingOrNull(value.next_attempt_at) &&
            isMissingOrNull(value.retry_kind) &&
            isMissingOrNull(value.last_error_code)
        );
    }

    return (
        acceptsDateTime(value.next_attempt_at) &&
        isProviderStartRetryKind(value.retry_kind) &&
        isIdentifier(value.last_error_code)
    );
}

function isWorkPlanSetPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            assignment_id: isIdentifier,
            authored_by_dispatch_id: isIdentifier,
            revision: isPositiveInteger,
            steps: isWorkPlanSteps,
            updated_at: acceptsDateTime,
        },
        { explanation: isNullableSummary },
    );
}

function isWorkPlanClearedPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            assignment_id: isIdentifier,
            authored_by_dispatch_id: isIdentifier,
            revision: isPositiveInteger,
            updated_at: acceptsDateTime,
        },
        { explanation: isNullableSummary },
    );
}

function isWorkPlanStep(value: unknown): boolean {
    return matchesExactRecord(value, {
        status: isWorkPlanStepStatus,
        step: isStepText,
    });
}

function isCheckpointRecordedPayload(value: unknown): boolean {
    if (
        !matchesExactRecord(
            value,
            {
                assignment_id: isIdentifier,
                attempt_id: isIdentifier,
                authored_by_dispatch_id: isIdentifier,
                checkpoint_id: isIdentifier,
                checkpoint_kind: isCheckpointKind,
                checkpoint_ref: isRef,
                produced_artifacts: isArtifactRefs,
                summary: isSummary,
                transient_surfaces: isTransientRefs,
            },
            { outcome: acceptsNullable(isCheckpointOutcome) },
        )
    ) {
        return false;
    }

    return value.checkpoint_kind === "progress"
        ? isMissingOrNull(value.outcome)
        : isCheckpointOutcome(value.outcome);
}

function isArtifactRef(value: unknown): boolean {
    return matchesExactRecord(value, {
        path: isRef,
        publication_id: isIdentifier,
        slot: isIdentifier,
        version: isPositiveInteger,
    });
}

function isTransientRef(value: unknown): boolean {
    return matchesExactRecord(value, {
        description: isSummary,
        localization_id: isIdentifier,
        path: isRef,
    });
}

function isBoundaryAcceptedPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            assignment_id: isIdentifier,
            attempt_id: isIdentifier,
            outcome: isBoundaryOutcome,
            resulting_flow_status: acceptsEnumValue(["running", "completed"] as const),
            source_dispatch_id: isIdentifier,
        },
        {
            assignment_decision_id: isNullableIdentifier,
            checkpoint_id: isNullableIdentifier,
            checkpoint_ref: isNullableRef,
        },
    );
}

function isChildAssignmentPayload(value: unknown): boolean {
    return matchesExactRecord(value, {
        child_assignment_id: isIdentifier,
        child_attempt_id: isIdentifier,
        child_node_key: isIdentifier,
        flow_revision_id: isIdentifier,
        parent_assignment_id: isIdentifier,
        source_dispatch_id: isIdentifier,
    });
}

function isStructuralRevisionAdoptedPayload(value: unknown): boolean {
    return matchesExactRecord(value, {
        adopted_by_dispatch_id: isIdentifier,
        adopted_flow_revision_id: isIdentifier,
        cause: isSummary,
        operation: isStructuralOperation,
        source_flow_revision_id: isIdentifier,
        target_node_key: isIdentifier,
    });
}

function isHumanRequestOpenedPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            kind: isHumanRequestKind,
            opened_at: acceptsDateTime,
            request_id: isIdentifier,
            source_dispatch_id: isIdentifier,
            summary: isSummary,
        },
        { due_at: isNullableDateTime },
    );
}

function isHumanRequestTerminalPayload(
    value: unknown,
    expectedStatus: "resolved" | "timed_out" | "cancelled",
    expectedResolution: "answered" | "timed_out" | "cancelled",
): boolean {
    if (
        !matchesExactRecord(
            value,
            {
                kind: isHumanRequestKind,
                request_id: isIdentifier,
                resolution_kind: acceptsEnumValue(["answered", "timed_out", "cancelled"] as const),
                resolution_summary: isSummary,
                resolved_at: acceptsDateTime,
                resolved_by_surface: isHumanResolutionSurface,
                source_dispatch_id: isIdentifier,
                status: acceptsEnumValue(["resolved", "timed_out", "cancelled"] as const),
                summary: isSummary,
            },
            {
                due_at: isNullableDateTime,
                resolved_by_actor_ref: isNullableIdentifier,
            },
        )
    ) {
        return false;
    }

    return value.status === expectedStatus && value.resolution_kind === expectedResolution;
}

function isCommandRunOpenedPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            command: isSummary,
            created_at: acceptsDateTime,
            description: isSummary,
            ownership_revision: acceptsLiteral(0),
            run_id: isIdentifier,
            source_dispatch_id: isIdentifier,
            state: acceptsLiteral("pending_start"),
        },
        {
            timeout_seconds: isNullablePositiveInteger,
            workdir: isNullableRef,
        },
    );
}

function isCommandRunStartedPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            command: isSummary,
            description: isSummary,
            log_refs: isLogRefs,
            ownership_revision: isPositiveInteger,
            run_id: isIdentifier,
            source_dispatch_id: isIdentifier,
            started_at: acceptsDateTime,
            state: acceptsLiteral("running"),
        },
        {
            due_at: isNullableDateTime,
            workdir: isNullableRef,
        },
    );
}

function isCommandRunProgressedPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            occurred_at: acceptsDateTime,
            ownership_revision: isPositiveInteger,
            run_id: isIdentifier,
            source_dispatch_id: isIdentifier,
            state: isCommandProgressState,
            summary: isSummary,
        },
        { log_ref: isNullableRef },
    );
}

function isCommandRunCancelRequestedPayload(value: unknown): boolean {
    return matchesExactRecord(value, {
        ownership_revision: isNonNegativeInteger,
        requested_at: acceptsDateTime,
        run_id: isIdentifier,
        source_dispatch_id: isIdentifier,
        state: acceptsLiteral("cancellation_requested"),
    });
}

function isCommandRunTerminalPayload(
    value: unknown,
    expectedState: "succeeded" | "failed" | "timed_out" | "cancelled" | "abandoned",
): boolean {
    if (
        !matchesExactRecord(
            value,
            {
                ended_at: acceptsDateTime,
                log_refs: isLogRefs,
                ownership_revision: isNonNegativeInteger,
                run_id: isIdentifier,
                source_dispatch_id: isIdentifier,
                state: acceptsEnumValue([
                    "succeeded",
                    "failed",
                    "timed_out",
                    "cancelled",
                    "abandoned",
                ] as const),
                summary: isSummary,
            },
            {
                exit_code: isNullableInteger,
                failure_code: isNullableIdentifier,
                started_at: isNullableDateTime,
            },
        )
    ) {
        return false;
    }

    if (value.state !== expectedState) {
        return false;
    }
    return expectedState !== "abandoned" || value.failure_code === "command_ownership_lost";
}

function isTaskPausedPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            control_revision: isPositiveInteger,
            pause_reason: isPauseReason,
            summary: isSummary,
        },
        { actor_ref: isNullableIdentifier },
    );
}

function isTaskControlPayload(value: unknown): boolean {
    return matchesExactRecord(
        value,
        {
            control_revision: isPositiveInteger,
            summary: isSummary,
        },
        { actor_ref: isNullableIdentifier },
    );
}

function matchesExactRecord(
    value: unknown,
    requiredFields: Readonly<Record<string, UnknownValidator>>,
    optionalFields: Readonly<Record<string, UnknownValidator>> = {},
): value is UnknownRecord {
    if (!isRecord(value)) {
        return false;
    }

    for (const field of Object.keys(value)) {
        if (!Object.hasOwn(requiredFields, field) && !Object.hasOwn(optionalFields, field)) {
            return false;
        }
    }
    for (const [field, validate] of Object.entries(requiredFields)) {
        if (!Object.hasOwn(value, field) || !validate(value[field])) {
            return false;
        }
    }
    for (const [field, validate] of Object.entries(optionalFields)) {
        if (Object.hasOwn(value, field) && !validate(value[field])) {
            return false;
        }
    }

    return true;
}

function isTaskEventType(value: unknown): value is TaskEventType {
    return typeof value === "string" && Object.hasOwn(taskEventPayloadValidators, value);
}

function acceptsEnumValue<const TValue extends string>(
    values: readonly TValue[],
): (value: unknown) => value is TValue {
    const acceptedValues = new Set<string>(values);
    return (value: unknown): value is TValue =>
        typeof value === "string" && acceptedValues.has(value);
}

function acceptsLiteral<const TValue extends string | number>(
    expectedValue: TValue,
): (value: unknown) => value is TValue {
    return (value: unknown): value is TValue => value === expectedValue;
}

function acceptsArray(
    validateItem: UnknownValidator,
    minLength: number,
    maxLength: number,
): UnknownValidator {
    return (value: unknown): boolean =>
        Array.isArray(value) &&
        value.length >= minLength &&
        value.length <= maxLength &&
        value.every((item) => validateItem(item));
}

function acceptsNullable(validate: UnknownValidator): UnknownValidator {
    return (value: unknown): boolean => value === null || validate(value);
}

function acceptsBoundedText(maxLength: number): UnknownValidator {
    return (value: unknown): boolean => acceptsNonEmptyText(value) && value.length <= maxLength;
}

function acceptsNonEmptyText(value: unknown): value is string {
    return typeof value === "string" && value.length > 0 && value.trim() === value;
}

function acceptsDateTime(value: unknown): value is string {
    return acceptsNonEmptyText(value) && value.includes("T") && Number.isFinite(Date.parse(value));
}

function acceptsIntegerAtLeast(minimum: number): UnknownValidator {
    return (value: unknown): boolean => Number.isSafeInteger(value) && (value as number) >= minimum;
}

function isMissingOrNull(value: unknown): boolean {
    return value === undefined || value === null;
}

function isRecord(value: unknown): value is UnknownRecord {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
