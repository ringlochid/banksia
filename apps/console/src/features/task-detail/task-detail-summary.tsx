import type { ReactNode } from "react";

import { Button, StatusChip } from "../../components/ui";
import { classNames } from "../../lib/classNames";
import type { TaskControlAction } from "./task-detail-data";
import { titleCaseNodeLabel } from "./task-detail-format";
import { flowStatusTone, type TaskDetailView } from "./task-detail-model";

export function TaskSummaryHeader({ view }: { readonly view: TaskDetailView }) {
    return (
        <div className="contents">
            {view.task.currentNodeKey === null ? null : (
                <HeaderFact label="Node">{titleCaseNodeLabel(view.task.currentNodeKey)}</HeaderFact>
            )}
            <HeaderFact label="Updated">
                <TaskDetailTimestamp value={view.task.updatedAt} />
            </HeaderFact>
        </div>
    );
}

export function TaskDetailEyebrow({ view }: { readonly view: TaskDetailView }) {
    return (
        <span className="flex min-w-0 flex-wrap items-center gap-2.5">
            <span>Task Detail</span>
            <StatusChip
                className="h-auto rounded-full px-3 py-1 normal-case"
                tone={flowStatusTone(view.task.status)}
            >
                {view.task.status}
            </StatusChip>
        </span>
    );
}

export function TaskActionControls({
    actionPending,
    onAction,
    view,
}: {
    readonly actionError: { readonly code: string } | null;
    readonly actionPending: TaskControlAction | null;
    readonly onAction: (action: TaskControlAction) => void;
    readonly view: TaskDetailView;
}) {
    return (
        <div className="flex flex-wrap items-center gap-3">
            <Button
                disabled={!view.actionMode.canPause || actionPending !== null}
                onClick={() => {
                    onAction("pause");
                }}
                variant="primary"
            >
                {actionPending === "pause" ? "Pausing" : "Pause"}
            </Button>
            <Button
                disabled={!view.actionMode.canContinue || actionPending !== null}
                onClick={() => {
                    onAction("continue");
                }}
            >
                {actionPending === "continue" ? "Continuing" : "Continue"}
            </Button>
            <Button
                disabled={!view.actionMode.canCancel || actionPending !== null}
                onClick={() => {
                    onAction("cancel");
                }}
                variant="danger"
            >
                {actionPending === "cancel" ? "Cancelling" : "Cancel"}
            </Button>
        </div>
    );
}

export function TaskDetailTimestamp({
    className,
    value,
    variant = "dateTime",
}: {
    readonly className?: string;
    readonly value: Date | string;
    readonly variant?: "dateTime" | "time";
}) {
    const date = value instanceof Date ? value : new Date(value);
    const label = Number.isNaN(date.valueOf())
        ? String(value)
        : formatSydneyTimestamp(date, variant);

    return (
        <time
            className={classNames("font-mono text-utility", className)}
            dateTime={Number.isNaN(date.valueOf()) ? undefined : date.toISOString()}
        >
            {label}
        </time>
    );
}

function HeaderFact({ children, label }: { readonly children: ReactNode; readonly label: string }) {
    return (
        <span className="inline-flex min-h-8 max-w-full items-center gap-2 rounded-full border border-outline-soft bg-surface-low px-3 py-1.5">
            <span className="shrink-0 font-mono text-label font-medium text-muted">{label}</span>
            <span className="min-w-0 text-utility text-foreground">{children}</span>
        </span>
    );
}

function formatSydneyTimestamp(date: Date, variant: "dateTime" | "time"): string {
    const options: Intl.DateTimeFormatOptions =
        variant === "time"
            ? {
                  hour: "numeric",
                  minute: "2-digit",
                  timeZone: "Australia/Sydney",
                  timeZoneName: "short",
              }
            : {
                  day: "numeric",
                  hour: "numeric",
                  minute: "2-digit",
                  month: "long",
                  timeZone: "Australia/Sydney",
                  timeZoneName: "short",
                  year: "numeric",
              };
    return new Intl.DateTimeFormat("en-AU", options).format(date).replace(" at ", ", ");
}
