import type { components } from "../../api/generated/openapi";
import type {
    TaskActionMode,
    TaskRuntimeDispatchView,
    TaskRuntimeView,
    TaskWorkPlanView,
} from "./task-detail-types";

export function mapTaskRuntimeView(
    task: components["schemas"]["RuntimeFlowRead"],
): TaskRuntimeView {
    return {
        activeAssignmentId: task.active_assignment_id ?? null,
        controlRevision: task.control_revision,
        currentCommandRun: task.current_command_run ?? null,
        currentDispatch:
            task.current_dispatch === null || task.current_dispatch === undefined
                ? null
                : mapTaskRuntimeDispatch(task.current_dispatch),
        currentHumanRequest: task.current_human_request ?? null,
        currentPlan:
            task.current_plan === null || task.current_plan === undefined
                ? null
                : mapTaskWorkPlan(task.current_plan),
        latestDispatchId: task.latest_dispatch_id ?? null,
        pauseReason: task.pause_reason ?? null,
        waitingCause: task.waiting_cause ?? null,
        watchdogRecoveryCount: task.watchdog_recovery_count ?? 0,
    };
}

export function buildTaskActionMode(
    task: components["schemas"]["RuntimeFlowRead"],
): TaskActionMode {
    if (task.status === "completed" || task.status === "cancelled") {
        return {
            canCancel: false,
            canContinue: false,
            canPause: false,
            note: "Terminal tasks have no task-level controls.",
        };
    }

    if (task.status === "paused") {
        const unresolvedSource = hasUnresolvedExternalSource(task);
        return {
            canCancel: true,
            canContinue: !unresolvedSource,
            canPause: false,
            note: unresolvedSource
                ? "Resolve the current human request or command run before continuing."
                : "Continue commits the next dispatch before provider start begins.",
        };
    }

    return {
        canCancel: true,
        canContinue: false,
        canPause: true,
        note: "Pause and cancel commit controller truth without waiting for provider cleanup.",
    };
}

function mapTaskRuntimeDispatch(
    dispatch: components["schemas"]["DispatchRuntimeRead"],
): TaskRuntimeDispatchView {
    return {
        adapterStartedAt: dispatch.adapter_started_at ?? null,
        assignmentId: dispatch.assignment_id,
        attemptId: dispatch.attempt_id,
        dispatchId: dispatch.dispatch_id,
        effectiveCapabilities: dispatch.effective_capabilities,
        isExperimentalProvider: dispatch.resolved_provider === "openclaw",
        lastNodeActivityAt: dispatch.last_node_activity_at ?? null,
        nodeActivityRevision: dispatch.node_activity_revision,
        openedReason: dispatch.opened_reason,
        predecessorDispatchId: dispatch.predecessor_dispatch_id ?? null,
        providerStart: dispatch.provider_start ?? null,
        requestedProvider: dispatch.requested_provider,
        resolvedProvider: dispatch.resolved_provider,
        selectionBasis: dispatch.selection_basis,
        status: dispatch.status,
        watchdogDueAt: dispatch.watchdog_due_at ?? null,
    };
}

function mapTaskWorkPlan(plan: components["schemas"]["WorkPlanRead"]): TaskWorkPlanView {
    return {
        assignmentId: plan.assignment_id,
        authoredByDispatchId: plan.authored_by_dispatch_id,
        explanation: plan.explanation ?? null,
        revision: plan.revision,
        steps: plan.steps,
        updatedAt: plan.updated_at,
    };
}

function hasUnresolvedExternalSource(task: components["schemas"]["RuntimeFlowRead"]): boolean {
    if (task.waiting_cause !== null && task.waiting_cause !== undefined) {
        return true;
    }

    if (task.current_human_request?.status === "open") {
        return true;
    }

    const commandState = task.current_command_run?.state;
    return (
        commandState === "pending_start" ||
        commandState === "running" ||
        commandState === "cancellation_requested"
    );
}
