import type { ReactNode } from "react";

import type { components } from "../../api/generated/openapi";
import type { CommandRunRow } from "../../api/view-models";
import type { StatusTone } from "../../components/ui";

export type CommandRunState = components["schemas"]["CommandRunState"];
export type CommandRunRecord = components["schemas"]["CommandRunRecord"];
export type CommandRunLogReadResponse = components["schemas"]["CommandRunLogReadResponse"];

export interface CommandRunDetailView {
    readonly assignmentId: string;
    readonly attemptId: string;
    readonly cancellationRequestedAt: string | null;
    readonly cancellationRequestedByActorRef: string | null;
    readonly command: string;
    readonly createdAt: string;
    readonly description: string;
    readonly dueAt: string | null;
    readonly endedAt: string | null;
    readonly expectedOutputs: readonly components["schemas"]["CommandExpectedOutput"][];
    readonly failureCode: string | null;
    readonly flowId: string;
    readonly ownershipRevision: number;
    readonly preferredLogRef: string | null;
    readonly runId: string;
    readonly sourceDispatchId: string;
    readonly startedAt: string | null;
    readonly state: CommandRunState;
    readonly stateLabel: string;
    readonly stateTone: StatusTone;
    readonly stderrLogRef: string | null;
    readonly stdoutLogRef: string | null;
    readonly successorDispatchId: string | null;
    readonly taskId: string;
    readonly terminalActorRef: string | null;
    readonly terminalEventSource: components["schemas"]["CommandRunTerminalSource"] | null;
    readonly terminalResult: components["schemas"]["CommandRunTerminalResult"] | null;
    readonly timeoutSeconds: number | null;
    readonly workdir: string | null;
}

export interface CommandRunRowView extends CommandRunRow {
    readonly canCancel: boolean;
    readonly stateLabel: string;
    readonly stateTone: StatusTone;
}

export function mapCommandRunRowView(row: CommandRunRow): CommandRunRowView {
    return {
        ...row,
        canCancel: isCommandRunCancellable(row.state),
        stateLabel: commandRunStateLabel(row.state),
        stateTone: commandRunStateTone(row.state),
    };
}

export function mapCommandRunDetailView(record: CommandRunRecord): CommandRunDetailView {
    const terminalResult = record.terminal_result ?? null;
    const stdoutLogRef = record.stdout_log_ref ?? null;
    const stderrLogRef = record.stderr_log_ref ?? null;

    return {
        assignmentId: record.assignment_id,
        attemptId: record.attempt_id,
        cancellationRequestedAt: record.cancellation_requested_at ?? null,
        cancellationRequestedByActorRef: record.cancellation_requested_by_actor_ref ?? null,
        command: formatCommandSpec(record.request.command),
        createdAt: record.created_at,
        description: record.request.summary,
        dueAt: record.due_at ?? null,
        endedAt: terminalResult?.ended_at ?? record.ended_at ?? null,
        expectedOutputs: record.request.expected_outputs,
        failureCode: terminalResult?.failure_code ?? null,
        flowId: record.flow_id,
        ownershipRevision: record.ownership_revision,
        preferredLogRef: preferredCommandLogRef(record.state, stdoutLogRef, stderrLogRef),
        runId: record.run_id,
        sourceDispatchId: record.source_dispatch_id,
        startedAt: terminalResult?.started_at ?? record.started_at ?? null,
        state: record.state,
        stateLabel: commandRunStateLabel(record.state),
        stateTone: commandRunStateTone(record.state),
        stderrLogRef,
        stdoutLogRef,
        successorDispatchId: record.successor_dispatch_id ?? null,
        taskId: record.task_id,
        terminalActorRef: terminalResult?.terminal_actor_ref ?? null,
        terminalEventSource: terminalResult?.terminal_event_source ?? null,
        terminalResult,
        timeoutSeconds: record.request.timeout_seconds ?? null,
        workdir: record.request.cwd ?? null,
    };
}

function preferredCommandLogRef(
    state: CommandRunState,
    stdoutLogRef: string | null,
    stderrLogRef: string | null,
): string | null {
    return state === "failed" || state === "timed_out"
        ? (stderrLogRef ?? stdoutLogRef)
        : (stdoutLogRef ?? stderrLogRef);
}

export function formatCommandSpec(command: components["schemas"]["CommandSpec"]): string {
    return command.kind === "shell" ? command.command : command.argv.join(" ");
}

export function isCommandRunCancellable(state: CommandRunState): boolean {
    return state === "pending_start" || state === "running";
}

export function isTerminalCommandRunState(state: CommandRunState): boolean {
    return (
        state === "succeeded" ||
        state === "failed" ||
        state === "timed_out" ||
        state === "cancelled" ||
        state === "abandoned"
    );
}

export function commandRunStateLabel(state: CommandRunState): string {
    switch (state) {
        case "pending_start":
            return "Pending start";
        case "running":
            return "Running";
        case "cancellation_requested":
            return "Cancel requested";
        case "succeeded":
            return "Succeeded";
        case "failed":
            return "Failed";
        case "timed_out":
            return "Timed out";
        case "cancelled":
            return "Cancelled";
        case "abandoned":
            return "Abandoned";
    }
}

export function commandRunStateTone(state: CommandRunState): StatusTone {
    switch (state) {
        case "running":
            return "active";
        case "succeeded":
            return "success";
        case "failed":
        case "timed_out":
        case "cancelled":
        case "abandoned":
            return "danger";
        case "pending_start":
        case "cancellation_requested":
            return "warning";
    }
}

export function formatOptionalNumber(value: number | null): string {
    return value === null ? "Not reported" : String(value);
}

export function renderOptionalText(value: string | null): ReactNode {
    return value === null || value.trim() === "" ? "Not reported" : value;
}
