import type { ReactNode } from "react";

import { IdRefText, StatusChip, Surface, TimestampText } from "../../components/ui";
import type {
    TaskDetailView,
    TaskRuntimeDispatchView,
    TaskRuntimeView,
    TaskWorkPlanView,
} from "./task-detail-types";

export function TaskRuntimeSummary({ view }: { readonly view: TaskDetailView }) {
    return (
        <section
            aria-label="Current controller runtime"
            className="grid min-w-0 gap-3 xl:grid-cols-3"
        >
            <CurrentAuthority runtime={view.runtime} view={view} />
            <CurrentDispatch dispatch={view.runtime.currentDispatch} runtime={view.runtime} />
            <CurrentWorkPlan plan={view.runtime.currentPlan} />
        </section>
    );
}

function CurrentAuthority({
    runtime,
    view,
}: {
    readonly runtime: TaskRuntimeView;
    readonly view: TaskDetailView;
}) {
    return (
        <Surface label="Controller truth" title="Current authority">
            <RuntimeFacts
                facts={[
                    { label: "Task", value: <IdRefText value={view.task.taskId} /> },
                    {
                        label: "Assignment",
                        value: renderOptionalId(runtime.activeAssignmentId),
                    },
                    {
                        label: "Attempt",
                        value: renderOptionalId(view.task.activeAttemptId),
                    },
                    {
                        label: "Latest dispatch",
                        value: renderOptionalId(runtime.latestDispatchId),
                    },
                    { label: "Control revision", value: String(runtime.controlRevision) },
                    ...(runtime.waitingCause === null
                        ? []
                        : [{ label: "Current wait", value: runtime.waitingCause }]),
                    ...(runtime.pauseReason === null
                        ? []
                        : [{ label: "Pause reason", value: runtime.pauseReason }]),
                ]}
            />
            <CurrentWait runtime={runtime} />
        </Surface>
    );
}

function CurrentWait({ runtime }: { readonly runtime: TaskRuntimeView }) {
    const humanRequest = runtime.currentHumanRequest;
    const commandRun = runtime.currentCommandRun;

    if (humanRequest === null && commandRun === null) {
        return null;
    }

    return (
        <div className="mt-4 space-y-2 border-t border-outline-soft pt-4">
            {humanRequest === null ? null : (
                <div className="rounded-card border border-outline-soft bg-surface-low p-3">
                    <p className="font-mono text-label font-medium text-muted">Human request</p>
                    <p className="mt-1 text-compact text-foreground">{humanRequest.summary}</p>
                    <p className="mt-2 font-mono text-utility text-muted">
                        {humanRequest.status} · {humanRequest.kind} ·{" "}
                        {humanRequest.source_dispatch_id}
                    </p>
                </div>
            )}
            {commandRun === null ? null : (
                <div className="rounded-card border border-outline-soft bg-surface-low p-3">
                    <p className="font-mono text-label font-medium text-muted">Command run</p>
                    <p className="mt-1 text-compact text-foreground">{commandRun.summary}</p>
                    <p className="mt-2 font-mono text-utility text-muted">
                        {commandRun.state} · {commandRun.source_dispatch_id}
                    </p>
                </div>
            )}
        </div>
    );
}

function CurrentDispatch({
    dispatch,
    runtime,
}: {
    readonly dispatch: TaskRuntimeDispatchView | null;
    readonly runtime: TaskRuntimeView;
}) {
    if (dispatch === null) {
        return (
            <Surface label="Dispatch" title="No current dispatch">
                <p className="text-compact text-muted">
                    No provider authority is current. The controller wait, pause, or terminal state
                    above explains why.
                </p>
            </Surface>
        );
    }

    const providerStart = dispatch.providerStart;
    return (
        <Surface
            label="Dispatch"
            title={dispatch.status === "starting" ? "Provider start pending" : "Open dispatch"}
        >
            <div className="flex flex-wrap items-center gap-2">
                <StatusChip tone={dispatch.status === "starting" ? "warning" : "active"} withDot>
                    {dispatch.status}
                </StatusChip>
                <StatusChip tone="neutral">
                    {dispatch.resolvedProvider} · {dispatch.selectionBasis}
                </StatusChip>
                {dispatch.isExperimentalProvider ? (
                    <StatusChip tone="warning">Experimental</StatusChip>
                ) : null}
            </div>
            <RuntimeFacts
                className="mt-4"
                facts={[
                    { label: "Dispatch", value: <IdRefText value={dispatch.dispatchId} /> },
                    {
                        label: "Predecessor",
                        value: renderOptionalId(dispatch.predecessorDispatchId),
                    },
                    { label: "Opened reason", value: dispatch.openedReason },
                    {
                        label: "Provider route",
                        value: `${dispatch.requestedProvider} → ${dispatch.resolvedProvider}`,
                    },
                    {
                        label: "Adapter accepted",
                        value: renderOptionalTimestamp(dispatch.adapterStartedAt),
                    },
                    {
                        label: "Node activity",
                        value:
                            dispatch.lastNodeActivityAt === null
                                ? "No admitted Node call yet"
                                : renderOptionalTimestamp(dispatch.lastNodeActivityAt),
                    },
                    {
                        label: "Watchdog due",
                        value: renderOptionalTimestamp(dispatch.watchdogDueAt),
                    },
                    {
                        label: "Watchdog recovery",
                        value: String(runtime.watchdogRecoveryCount),
                    },
                ]}
            />
            {providerStart === null ? null : (
                <div className="mt-4 rounded-card border border-outline-soft bg-surface-low p-3">
                    <p className="font-mono text-label font-medium text-muted">Provider start</p>
                    <p className="mt-1 text-compact text-foreground">
                        Attempt {String(providerStart.attempt_count)}
                        {providerStart.retry_kind === null || providerStart.retry_kind === undefined
                            ? ""
                            : ` · ${providerStart.retry_kind}`}
                    </p>
                    {providerStart.next_attempt_at === null ||
                    providerStart.next_attempt_at === undefined ? null : (
                        <p className="mt-1 text-utility text-muted">
                            Next attempt <TimestampText value={providerStart.next_attempt_at} />
                        </p>
                    )}
                    {providerStart.last_error_code === null ||
                    providerStart.last_error_code === undefined ? null : (
                        <p className="mt-1 font-mono text-utility text-danger">
                            {providerStart.last_error_code}
                        </p>
                    )}
                </div>
            )}
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <CapabilityFact
                    label="Provider-native access"
                    source={dispatch.effectiveCapabilities.provider_native_access.source}
                    value={dispatch.effectiveCapabilities.provider_native_access.effective}
                />
                <CapabilityFact
                    label="Network access"
                    source={dispatch.effectiveCapabilities.network_access.source}
                    value={dispatch.effectiveCapabilities.network_access.effective}
                />
            </div>
        </Surface>
    );
}

function CurrentWorkPlan({ plan }: { readonly plan: TaskWorkPlanView | null }) {
    if (plan === null) {
        return (
            <Surface label="Assignment plan" title="No current work plan">
                <p className="text-compact text-muted">
                    This is a legal controller state. A plan is optional and does not gate work.
                </p>
            </Surface>
        );
    }

    return (
        <Surface label="Assignment plan" title={`Revision ${String(plan.revision)}`}>
            {plan.explanation === null ? null : (
                <p className="mb-4 text-compact text-muted">{plan.explanation}</p>
            )}
            <ol aria-label="Current work plan" className="space-y-2">
                {plan.steps.map((step, index) => (
                    <li
                        className="flex min-w-0 items-start gap-3 rounded-card border border-outline-soft bg-surface-low p-3"
                        key={`${String(index)}-${step.step}`}
                    >
                        <StatusChip
                            tone={
                                step.status === "completed"
                                    ? "success"
                                    : step.status === "in_progress"
                                      ? "active"
                                      : "neutral"
                            }
                        >
                            {step.status}
                        </StatusChip>
                        <span className="min-w-0 text-compact text-foreground">{step.step}</span>
                    </li>
                ))}
            </ol>
            <p className="mt-4 break-all font-mono text-label text-muted">
                Authored by {plan.authoredByDispatchId} · <TimestampText value={plan.updatedAt} />
            </p>
        </Surface>
    );
}

function CapabilityFact({
    label,
    source,
    value,
}: {
    readonly label: string;
    readonly source: string;
    readonly value: string;
}) {
    return (
        <div className="rounded-card border border-outline-soft bg-surface-low p-3">
            <p className="font-mono text-label font-medium text-muted">{label}</p>
            <p className="mt-1 text-compact font-semibold text-foreground">{value}</p>
            <p className="mt-1 font-mono text-label text-muted">Source: {source}</p>
        </div>
    );
}

function RuntimeFacts({
    className,
    facts,
}: {
    readonly className?: string;
    readonly facts: readonly { readonly label: string; readonly value: ReactNode }[];
}) {
    return (
        <dl className={className === undefined ? "grid gap-3" : `grid gap-3 ${className}`}>
            {facts.map((fact) => (
                <div className="min-w-0" key={fact.label}>
                    <dt className="font-mono text-label font-medium text-muted">{fact.label}</dt>
                    <dd className="mt-1 min-w-0 break-words text-utility text-foreground">
                        {fact.value}
                    </dd>
                </div>
            ))}
        </dl>
    );
}

function renderOptionalId(value: string | null): ReactNode {
    return value === null ? "None" : <IdRefText value={value} />;
}

function renderOptionalTimestamp(value: string | null): ReactNode {
    return value === null ? "Not set" : <TimestampText value={value} />;
}
