import type { components } from "../../api/generated/openapi";
import { mapDefinitionSummary, type DefinitionSummary } from "../../api/view-models";
import type { StatusTone } from "../../components/ui";

export type TaskRootMode = components["schemas"]["TaskRootMode"];
export type TaskStartRequest = components["schemas"]["TaskStartRequest"];
export type TaskStartResponse = components["schemas"]["TaskStartResponse"];
export type TaskComposePreviewResponse = components["schemas"]["TaskComposePreviewResponse"];
export type DefinitionSummaryRead = components["schemas"]["DefinitionSummaryRead"];
export type DefinitionRevisionDetailResponse =
    components["schemas"]["DefinitionRevisionDetailResponse"];
export type DefinitionRevisionHistoryEntry =
    components["schemas"]["DefinitionRevisionHistoryEntry"];
export type WorkflowDefinitionContent = components["schemas"]["WorkflowDefinitionInput-Output"];

export interface TaskStartFormState {
    readonly instruction: string;
    readonly summary: string;
    readonly taskKey: string;
    readonly title: string;
    readonly workspaceHostPath: string;
    readonly workspaceMode: TaskRootMode;
}

export interface TaskStartFormErrors {
    readonly summary?: string;
    readonly taskKey?: string;
    readonly title?: string;
    readonly workflow?: string;
    readonly workspaceHostPath?: string;
}

export interface TaskStartFieldPlaceholders {
    readonly instruction: string;
    readonly summary: string;
    readonly taskKey: string;
    readonly title: string;
}

export interface TaskStartWorkflowChoice extends DefinitionSummary {
    readonly displayName: string;
}

export interface TaskStartWorkflowDetail {
    readonly description: string;
    readonly key: string;
    readonly revisionNo: number;
    readonly updatedAt: string;
}

export interface TaskStartVersionRow {
    readonly recordedBy: string | null;
    readonly revisionNo: number;
    readonly updatedAt: string;
}

export interface TaskStartPreview {
    readonly errors: readonly TaskStartPreviewIssue[];
    readonly instructionSummary: string;
    readonly nodes: readonly TaskStartPreviewNode[];
    readonly status: TaskComposePreviewResponse["status"];
    readonly summary: string;
    readonly taskKey: string;
    readonly title: string;
    readonly warnings: readonly TaskStartPreviewIssue[];
    readonly workflowDescription: string;
    readonly workflowKey: string;
    readonly workspaceHostPath: string | null;
    readonly workspaceModeLabel: string;
    readonly workspaceSummary: string;
}

export interface TaskStartPreviewIssue {
    readonly code: string;
    readonly kind: components["schemas"]["TaskComposePreviewIssue"]["kind"];
    readonly message: string;
    readonly path: string | null;
}

export interface TaskStartPreviewNode {
    readonly isExperimentalProvider: boolean;
    readonly networkAccess: components["schemas"]["EffectiveNetworkAccess"];
    readonly nodeKey: string;
    readonly providerNativeAccess: components["schemas"]["EffectiveProviderNativeAccess"];
    readonly requestedProvider: components["schemas"]["ProviderKind"];
    readonly resolvedProvider: components["schemas"]["ProviderKind"];
    readonly selectionBasis: components["schemas"]["ProviderSelectionBasis"];
}

export interface TaskStartResultView {
    readonly activeFlowRevisionId: string;
    readonly compiledPlanId: string;
    readonly flowStatus: components["schemas"]["FlowStatus"];
    readonly flowStatusLabel: string;
    readonly flowStatusTone: StatusTone;
    readonly manifestDescription: string;
    readonly manifestPath: string;
    readonly taskId: string;
}

export const TASK_START_INITIAL_FORM: TaskStartFormState = {
    instruction: "",
    summary: "",
    taskKey: "",
    title: "",
    workspaceHostPath: "",
    workspaceMode: "ensure_task_default",
};

export const TASK_START_FIELD_PLACEHOLDERS: TaskStartFieldPlaceholders = {
    instruction:
        "Keep the work scoped to the current task-start UI and publish focused verification.",
    summary: "Launch one bounded implementation task from stored workflow truth.",
    taskKey: "implement-task-start-launch-form",
    title: "Implement Task Start launch form",
};

export const TASK_ROOT_MODE_OPTIONS: readonly {
    readonly label: string;
    readonly value: TaskRootMode;
}[] = [
    { label: "Task default", value: "ensure_task_default" },
    { label: "Create host path", value: "ensure_host_path" },
    { label: "Use existing host", value: "use_existing_host" },
];

export function mapTaskStartWorkflowChoice(
    definition: DefinitionSummaryRead,
): TaskStartWorkflowChoice {
    const summary = mapDefinitionSummary(definition);
    return {
        ...summary,
        displayName: summary.title ?? summary.key,
    };
}

export function mapTaskStartWorkflowDetail(
    detail: DefinitionRevisionDetailResponse,
): TaskStartWorkflowDetail {
    const content = detail.content as WorkflowDefinitionContent;
    return {
        description: content.description,
        key: detail.key,
        revisionNo: detail.revision_no,
        updatedAt: detail.updated_at,
    };
}

export function mapTaskStartVersionRow(
    version: DefinitionRevisionHistoryEntry,
): TaskStartVersionRow {
    return {
        recordedBy: version.recorded_by ?? null,
        revisionNo: version.revision_no,
        updatedAt: version.updated_at,
    };
}

export function validateTaskStartForm(
    form: TaskStartFormState,
    selectedWorkflowKey: string | null,
): TaskStartFormErrors {
    return {
        workflow: selectedWorkflowKey === null ? "Workflow selection is required." : undefined,
        taskKey: form.taskKey.trim().length === 0 ? "Task key is required." : undefined,
        title: form.title.trim().length === 0 ? "Title is required." : undefined,
        summary: form.summary.trim().length === 0 ? "Summary is required." : undefined,
        workspaceHostPath:
            form.workspaceMode === "ensure_task_default" || form.workspaceHostPath.trim().length > 0
                ? undefined
                : "Workspace host path is required.",
    };
}

export function hasTaskStartFormErrors(errors: TaskStartFormErrors): boolean {
    return Object.values(errors).some((value) => value !== undefined);
}

export function countTaskStartRequiredInputs(
    form: TaskStartFormState,
    selectedWorkflowKey: string | null,
): number {
    return Object.values(validateTaskStartForm(form, selectedWorkflowKey)).filter(
        (value) => value !== undefined,
    ).length;
}

export function buildTaskStartRequest(
    form: TaskStartFormState,
    workflowKey: string,
): TaskStartRequest {
    const workspace = buildRootBinding(form.workspaceMode, form.workspaceHostPath);
    const roots = workspace === null ? undefined : { workspace };
    const instruction = form.instruction.trim();

    return {
        ...(roots === undefined ? {} : { roots }),
        task: {
            ...(instruction.length === 0 ? {} : { instruction }),
            key: form.taskKey.trim(),
            summary: form.summary.trim(),
            title: form.title.trim(),
        },
        workflow: {
            key: workflowKey,
        },
    };
}

export function buildTaskStartPreview({
    detail,
    form,
    response,
    workflow,
}: {
    readonly detail: TaskStartWorkflowDetail | null;
    readonly form: TaskStartFormState;
    readonly response: TaskComposePreviewResponse;
    readonly workflow: TaskStartWorkflowChoice;
}): TaskStartPreview {
    return {
        errors: response.errors.map(mapTaskStartPreviewIssue),
        instructionSummary:
            form.instruction.trim().length === 0
                ? "No additional instruction provided."
                : form.instruction.trim(),
        nodes: response.nodes.map((node) => ({
            isExperimentalProvider:
                node.provider_resolution.requested_provider === "openclaw" ||
                node.provider_resolution.resolved_provider === "openclaw",
            networkAccess: node.network_access,
            nodeKey: node.node_key,
            providerNativeAccess: node.provider_native_access,
            requestedProvider: node.provider_resolution.requested_provider,
            resolvedProvider: node.provider_resolution.resolved_provider,
            selectionBasis: node.provider_resolution.selection_basis,
        })),
        status: response.status,
        summary: form.summary.trim(),
        taskKey: form.taskKey.trim(),
        title: form.title.trim(),
        workflowDescription:
            detail?.description ?? workflow.description ?? "No workflow description reported.",
        workflowKey: workflow.key,
        workspaceHostPath:
            form.workspaceMode === "ensure_task_default" ? null : form.workspaceHostPath.trim(),
        workspaceModeLabel: rootModeLabel(form.workspaceMode),
        workspaceSummary: rootModeSummary(form.workspaceMode),
        warnings: response.warnings.map(mapTaskStartPreviewIssue),
    };
}

export function mapTaskStartResult(response: TaskStartResponse): TaskStartResultView {
    return {
        activeFlowRevisionId: response.active_flow_revision_id,
        compiledPlanId: response.compiled_plan_id,
        flowStatus: response.flow_status,
        flowStatusLabel: flowStatusLabel(response.flow_status),
        flowStatusTone: flowStatusTone(response.flow_status),
        manifestDescription: response.workflow_manifest_ref.description,
        manifestPath: response.workflow_manifest_ref.path,
        taskId: response.task_id,
    };
}

export function rootModeLabel(mode: TaskRootMode): string {
    switch (mode) {
        case "ensure_task_default":
            return "Task default";
        case "ensure_host_path":
            return "Create host path";
        case "use_existing_host":
            return "Use existing host";
    }
}

export function rootModeSummary(mode: TaskRootMode): string {
    switch (mode) {
        case "ensure_task_default":
            return "Controller will assign the task-owned default root.";
        case "ensure_host_path":
            return "Controller will create or reuse the provided host placement.";
        case "use_existing_host":
            return "Controller will use the provided existing host placement.";
    }
}

export function shouldShowHostPath(mode: TaskRootMode): boolean {
    return mode !== "ensure_task_default";
}

function buildRootBinding(
    mode: TaskRootMode,
    hostPath: string,
): components["schemas"]["TaskRootBindingInput"] | null {
    if (mode === "ensure_task_default") {
        return null;
    }

    return {
        host_path: hostPath.trim(),
        mode,
    };
}

function mapTaskStartPreviewIssue(
    issue: components["schemas"]["TaskComposePreviewIssue"],
): TaskStartPreviewIssue {
    return {
        code: issue.code,
        kind: issue.kind,
        message: issue.message,
        path: issue.path ?? null,
    };
}

function flowStatusLabel(status: components["schemas"]["FlowStatus"]): string {
    switch (status) {
        case "blocked":
            return "Blocked";
        case "cancelled":
            return "Cancelled";
        case "paused":
            return "Paused";
        case "pending":
            return "Pending";
        case "running":
            return "Running";
        case "succeeded":
            return "Succeeded";
    }
}

function flowStatusTone(status: components["schemas"]["FlowStatus"]): StatusTone {
    switch (status) {
        case "running":
            return "active";
        case "succeeded":
            return "success";
        case "blocked":
        case "paused":
            return "warning";
        case "cancelled":
            return "danger";
        case "pending":
            return "neutral";
    }
}
