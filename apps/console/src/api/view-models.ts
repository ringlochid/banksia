import type { components } from "./generated/openapi";

export interface TaskRow {
    readonly activeAssignmentId: string | null;
    readonly activeAttemptId: string | null;
    readonly currentNodeKey: string | null;
    readonly status: components["schemas"]["RuntimeLifecycleStatus"];
    readonly summary: string;
    readonly taskId: string;
    readonly title: string;
    readonly updatedAt: string;
    readonly workflowKey: string | null;
}

export interface TaskEventItem {
    readonly attemptId: string | null;
    readonly eventId: string;
    readonly eventSeq: number;
    readonly eventSource: components["schemas"]["TaskEventSource"];
    readonly eventType: TaskEventType;
    readonly flowRevisionId: string | null;
    readonly nodeKey: string | null;
    readonly occurredAt: string;
    readonly taskId: string;
}

export type TaskEventRecord = components["schemas"]["TaskEventRecord"];
export type TaskEventType = TaskEventRecord["event_type"];

export interface HumanRequestQueueItem {
    readonly itemCount: number;
    readonly kind: components["schemas"]["HumanRequestKind"];
    readonly openedAt: string;
    readonly requestId: string;
    readonly status: components["schemas"]["HumanRequestStatus"];
    readonly summary: string;
    readonly taskId: string;
    readonly title: string;
}

export interface CommandRunRow {
    readonly command: string;
    readonly createdAt: string;
    readonly description: string | null;
    readonly endedAt: string | null;
    readonly exitCode: number | null;
    readonly hasLog: boolean;
    readonly logRef: string | null;
    readonly runId: string;
    readonly signal: string | null;
    readonly startedAt: string | null;
    readonly state: components["schemas"]["CommandRunState"];
    readonly summary: string | null;
    readonly timeoutSeconds: number | null;
    readonly workdir: string | null;
}

export interface DefinitionSummary {
    readonly allowedNodeKinds: readonly components["schemas"]["NodeKind"][];
    readonly appliesTo: readonly components["schemas"]["NodeKind"][];
    readonly budgetSpec: components["schemas"]["BudgetSpec"] | null;
    readonly currentRevisionNo: number;
    readonly description: string | null;
    readonly key: string;
    readonly labels: readonly string[];
    readonly title: string | null;
    readonly updatedAt: string;
}

export interface DefinitionDraftSummary {
    readonly key: string;
    readonly kind: components["schemas"]["DefinitionKind"];
    readonly mode: components["schemas"]["DefinitionDraftMode"];
    readonly status: components["schemas"]["DefinitionDraftStatus"];
    readonly updatedAt: string;
}

export interface TaskStartResult {
    readonly flowStatus: components["schemas"]["FlowStatus"];
    readonly taskId: string;
}

export function mapTaskRow(task: components["schemas"]["RuntimeFlowSummary"]): TaskRow {
    return {
        activeAssignmentId: task.active_assignment_id ?? null,
        activeAttemptId: task.active_attempt_id ?? null,
        currentNodeKey: task.current_node_key ?? null,
        status: task.status,
        summary: task.task_summary,
        taskId: task.task_id,
        title: task.task_title,
        updatedAt: task.updated_at,
        workflowKey: task.workflow_key ?? null,
    };
}

export function mapTaskEventItem(event: components["schemas"]["TaskEventRecord"]): TaskEventItem {
    return {
        attemptId: event.attempt_id ?? null,
        eventId: event.event_id,
        eventSeq: event.event_seq,
        eventSource: event.event_source,
        eventType: event.event_type,
        flowRevisionId: event.flow_revision_id ?? null,
        nodeKey: event.node_key ?? null,
        occurredAt: event.occurred_at,
        taskId: event.task_id,
    };
}

export function mapHumanRequestQueueItem(
    requestRead: components["schemas"]["HumanRequestRead"],
): HumanRequestQueueItem {
    const request = requestRead.request;
    return {
        itemCount: request.items.length,
        kind: request.kind,
        openedAt: request.opened_at,
        requestId: request.request_id,
        status: request.status,
        summary: request.summary,
        taskId: request.task_id,
        title: request.summary,
    };
}

export function mapCommandRunRow(run: components["schemas"]["CommandRunListItem"]): CommandRunRow {
    return {
        command: run.command,
        createdAt: run.created_at,
        description: run.description ?? null,
        endedAt: run.ended_at ?? null,
        exitCode: run.exit_code ?? null,
        hasLog: run.log_ref !== null && run.log_ref !== undefined,
        logRef: run.log_ref ?? null,
        runId: run.run_id,
        signal: run.signal ?? null,
        startedAt: run.started_at ?? null,
        state: run.state,
        summary: run.summary ?? null,
        timeoutSeconds: run.timeout_seconds ?? null,
        workdir: run.workdir ?? null,
    };
}

export function mapDefinitionSummary(
    definition: components["schemas"]["DefinitionSummaryRead"],
): DefinitionSummary {
    return {
        allowedNodeKinds: definition.allowed_node_kinds ?? [],
        appliesTo: definition.applies_to ?? [],
        budgetSpec: definition.budget_spec ?? null,
        currentRevisionNo: definition.current_revision_no,
        description: definition.description ?? null,
        key: definition.key,
        labels: definition.labels,
        title: definition.title ?? null,
        updatedAt: definition.updated_at,
    };
}

export function mapDefinitionDraftSummary(
    draft: components["schemas"]["DefinitionDraftSummary"],
): DefinitionDraftSummary {
    return {
        key: draft.key,
        kind: draft.kind,
        mode: draft.mode,
        status: draft.status,
        updatedAt: draft.updated_at,
    };
}

export function mapTaskStartResult(
    response: components["schemas"]["TaskStartResponse"],
): TaskStartResult {
    return {
        flowStatus: response.flow_status,
        taskId: response.task_id,
    };
}
