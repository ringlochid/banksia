import type { ReactNode } from "react";

import { taskOutcome } from "../../api/task-outcome";
import { Button, StatusChip, TimestampText } from "../../components/ui";
import type { TaskControlAction } from "./task-detail-data";
import { titleCaseNodeLabel } from "./task-detail-format";
import type { TaskDetailView } from "./task-detail-model";

export function TaskSummaryHeader({ view }: { readonly view: TaskDetailView }) {
    return (
        <div className="contents">
            {view.task.currentNodeKey === null ? null : (
                <HeaderFact label="Node">{titleCaseNodeLabel(view.task.currentNodeKey)}</HeaderFact>
            )}
            <HeaderFact label="Updated">
                <TimestampText value={view.task.updatedAt} />
            </HeaderFact>
        </div>
    );
}

export function TaskDetailEyebrow({ view }: { readonly view: TaskDetailView }) {
    const outcome = taskOutcome(view.task.status, view.task.terminalOutcome);
    return (
        <span className="flex min-w-0 flex-wrap items-center gap-2.5">
            <span>Task Detail</span>
            <StatusChip className="h-auto rounded-full px-3 py-1 normal-case" tone={outcome.tone}>
                {outcome.label}
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
    const { canCancel, canContinue, canPause } = view.actionMode;
    if (!canPause && !canContinue && !canCancel) {
        return null;
    }

    return (
        <div className="flex flex-wrap items-center gap-3">
            {canPause ? (
                <Button
                    disabled={actionPending !== null}
                    onClick={() => {
                        onAction("pause");
                    }}
                    variant="primary"
                >
                    {actionPending === "pause" ? "Pausing" : "Pause"}
                </Button>
            ) : null}
            {canContinue ? (
                <Button
                    disabled={actionPending !== null}
                    onClick={() => {
                        onAction("continue");
                    }}
                >
                    {actionPending === "continue" ? "Continuing" : "Continue"}
                </Button>
            ) : null}
            {canCancel ? (
                <Button
                    disabled={actionPending !== null}
                    onClick={() => {
                        onAction("cancel");
                    }}
                    variant="danger"
                >
                    {actionPending === "cancel" ? "Cancelling" : "Cancel"}
                </Button>
            ) : null}
        </div>
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
