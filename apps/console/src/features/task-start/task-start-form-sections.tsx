import type { ReactNode } from "react";

import { Button, FormField, IdRefText, StatePanel, StatusChip } from "../../components/ui";
import { classNames } from "../../lib/classNames";
import type { TaskStartController } from "./task-start-controller";
import { isAuthError } from "./task-start-data";
import {
    TASK_START_FIELD_PLACEHOLDERS,
    TASK_ROOT_MODE_OPTIONS,
    countTaskStartRequiredInputs,
    shouldShowHostPath,
    type TaskRootMode,
} from "./task-start-model";
import { TaskStartDialog } from "./task-start-dialog";
import { controlClassName, textAreaClassName } from "./task-start-ui";

export function TaskIdentitySection({ controller }: { readonly controller: TaskStartController }) {
    const labelClassName =
        "font-display text-compact font-semibold tracking-normal !normal-case text-foreground";

    return (
        <div className="grid gap-4 lg:grid-cols-2">
            <FormField
                error={controller.formErrors.taskKey}
                id="task-start-key"
                label="Task key"
                labelClassName={labelClassName}
            >
                <input
                    className={controlClassName()}
                    onChange={(event) => {
                        controller.setField("taskKey", event.target.value);
                    }}
                    placeholder={TASK_START_FIELD_PLACEHOLDERS.taskKey}
                    value={controller.form.taskKey}
                />
            </FormField>
            <FormField
                error={controller.formErrors.title}
                id="task-start-title"
                label="Title"
                labelClassName={labelClassName}
            >
                <input
                    className={controlClassName()}
                    onChange={(event) => {
                        controller.setField("title", event.target.value);
                    }}
                    placeholder={TASK_START_FIELD_PLACEHOLDERS.title}
                    value={controller.form.title}
                />
            </FormField>
            <div className="lg:col-span-2">
                <FormField
                    error={controller.formErrors.summary}
                    id="task-start-summary"
                    label="Summary"
                    labelClassName={labelClassName}
                >
                    <textarea
                        className={textAreaClassName("min-h-19")}
                        onChange={(event) => {
                            controller.setField("summary", event.target.value);
                        }}
                        placeholder={TASK_START_FIELD_PLACEHOLDERS.summary}
                        rows={3}
                        value={controller.form.summary}
                    />
                </FormField>
            </div>
            <div className="lg:col-span-2">
                <FormField
                    id="task-start-instruction"
                    label="Instruction"
                    labelClassName={labelClassName}
                >
                    <textarea
                        className={textAreaClassName("min-h-21")}
                        onChange={(event) => {
                            controller.setField("instruction", event.target.value);
                        }}
                        placeholder={TASK_START_FIELD_PLACEHOLDERS.instruction}
                        rows={3}
                        value={controller.form.instruction}
                    />
                </FormField>
            </div>
        </div>
    );
}

export function RootsSection({ controller }: { readonly controller: TaskStartController }) {
    return (
        <div className="divide-y divide-outline-soft rounded-card border border-outline-soft bg-surface-low shadow-hairline">
            <RootBindingControl
                error={controller.formErrors.workspaceHostPath}
                hostPath={controller.form.workspaceHostPath}
                label="Workspace"
                mode={controller.form.workspaceMode}
                onHostPathChange={(value) => {
                    controller.setField("workspaceHostPath", value);
                }}
                onModeChange={(mode) => {
                    controller.setWorkspaceMode(mode);
                }}
            />
        </div>
    );
}

export function TaskStartSection({
    children,
    label,
}: {
    readonly children: ReactNode;
    readonly label: string;
}) {
    const headingId = `task-start-section-${label.toLowerCase()}`;

    return (
        <section
            aria-labelledby={headingId}
            className="grid gap-4 px-4 py-4 sm:px-5 sm:py-5 xl:grid-cols-[13rem_minmax(0,1fr)]"
        >
            <h2 className="font-mono text-label font-medium text-muted lg:pt-2" id={headingId}>
                {label}
            </h2>
            <div className="min-w-0">{children}</div>
        </section>
    );
}

function RootBindingControl({
    error,
    hostPath,
    label,
    mode,
    onHostPathChange,
    onModeChange,
}: {
    readonly error: string | undefined;
    readonly hostPath: string;
    readonly label: string;
    readonly mode: TaskRootMode;
    readonly onHostPathChange: (value: string) => void;
    readonly onModeChange: (mode: TaskRootMode) => void;
}) {
    const hostPathId = `task-start-${label.toLowerCase()}-host-path`;

    return (
        <section aria-label={`${label} root`} className="p-4">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0">
                    <h2 className="font-display text-compact font-semibold text-foreground">
                        {label}
                    </h2>
                </div>
                <RootModeButtons
                    label={`${label} root mode`}
                    onChange={onModeChange}
                    value={mode}
                />
            </div>
            {shouldShowHostPath(mode) ? (
                <div className="mt-4">
                    <FormField error={error} id={hostPathId} label="Host path">
                        <input
                            className={controlClassName()}
                            onChange={(event) => {
                                onHostPathChange(event.target.value);
                            }}
                            placeholder={rootHostPathPlaceholder(mode)}
                            value={hostPath}
                        />
                    </FormField>
                </div>
            ) : null}
        </section>
    );
}

function RootModeButtons({
    label,
    onChange,
    value,
}: {
    readonly label: string;
    readonly onChange: (value: TaskRootMode) => void;
    readonly value: TaskRootMode;
}) {
    return (
        <div aria-label={label} className="inline-flex min-w-0 flex-wrap gap-2" role="group">
            {TASK_ROOT_MODE_OPTIONS.map((option) => {
                const isSelected = option.value === value;

                return (
                    <button
                        aria-pressed={isSelected}
                        className={classNames(
                            "inline-flex h-control items-center justify-center gap-2 rounded-control border px-4 text-utility font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55",
                            isSelected
                                ? "border-primary/25 bg-primary-soft text-primary-foreground"
                                : "border-outline bg-surface-low text-foreground hover:border-primary/45 hover:text-primary-foreground",
                        )}
                        key={option.value}
                        onClick={() => {
                            onChange(option.value);
                        }}
                        type="button"
                    >
                        {isSelected ? (
                            <span
                                aria-hidden="true"
                                className="size-1.5 shrink-0 rounded-full bg-primary"
                            />
                        ) : null}
                        <span className="min-w-0 truncate">{option.label}</span>
                    </button>
                );
            })}
        </div>
    );
}

function rootHostPathPlaceholder(mode: TaskRootMode): string {
    return mode === "ensure_host_path" ? "/workspaces/new-task" : "/workspaces/existing-root";
}

export function TaskStartActions({ controller }: { readonly controller: TaskStartController }) {
    const requiredInputCount = countTaskStartRequiredInputs(
        controller.form,
        controller.selectedWorkflowKey,
    );
    const requiredInputLabel = String(requiredInputCount);
    const isStartDisabled = controller.submitState.isSubmitting || requiredInputCount > 0;

    return (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-compact text-muted">
                {requiredInputCount > 0
                    ? `${requiredInputLabel} required input${
                          requiredInputCount === 1 ? "" : "s"
                      } still need attention.`
                    : "Ready to start from the selected workflow."}
            </p>
            <div className="flex flex-wrap gap-2">
                <Button onClick={controller.showPreview}>Preview</Button>
                <Button
                    className="disabled:border-outline disabled:bg-outline disabled:text-white disabled:opacity-100"
                    disabled={isStartDisabled}
                    onClick={controller.start}
                    variant="primary"
                >
                    {controller.submitState.isSubmitting ? "Starting" : "Start Task"}
                </Button>
            </div>
        </div>
    );
}

export function ResultPanel({ controller }: { readonly controller: TaskStartController }) {
    if (!controller.resultOpen) {
        return null;
    }

    if (controller.submitState.error !== null) {
        const error = controller.submitState.error;
        return (
            <TaskStartDialog
                footer={
                    <>
                        <Button
                            data-dialog-initial-focus
                            onClick={() => {
                                controller.setResultOpen(false);
                            }}
                        >
                            Back to edit
                        </Button>
                        <Button onClick={controller.start} variant="primary">
                            Retry Start Task
                        </Button>
                    </>
                }
                label="Result"
                onClose={() => {
                    controller.setResultOpen(false);
                }}
                title={
                    isAuthError(error)
                        ? "Access to Task Start failed"
                        : error.source === "validation"
                          ? "Task Start validation failed"
                          : "Task could not start"
                }
            >
                <StatePanel
                    summary={error.summary}
                    title={
                        isAuthError(error)
                            ? "Access to Task Start failed"
                            : error.source === "validation"
                              ? "Task Start validation failed"
                              : "Task could not start"
                    }
                    tone={isAuthError(error) ? "auth" : "error"}
                />
            </TaskStartDialog>
        );
    }

    if (controller.submitState.result === null) {
        return null;
    }

    return (
        <TaskStartResult
            onClose={() => {
                controller.setResultOpen(false);
            }}
            result={controller.submitState.result}
        />
    );
}

function TaskStartResult({
    onClose,
    result,
}: {
    readonly onClose: () => void;
    readonly result: NonNullable<TaskStartController["submitState"]["result"]>;
}) {
    return (
        <TaskStartDialog
            footer={
                <Button data-dialog-initial-focus onClick={onClose}>
                    Back to edit
                </Button>
            }
            label="Result"
            onClose={onClose}
            title="Result"
        >
            <StatePanel
                summary="The controller launch committed. Provider start follows asynchronously; use Tasks to read current controller state."
                title="Task launch committed"
                tone="success"
            />
            <dl className="mt-4 overflow-hidden rounded-card border border-outline-soft bg-surface-low">
                <ResultReadbackRow label="Task ID">
                    <IdRefText value={result.taskId} />
                </ResultReadbackRow>
                <ResultReadbackRow label="Flow status">
                    <StatusChip tone={result.flowStatusTone}>{result.flowStatusLabel}</StatusChip>
                </ResultReadbackRow>
                <ResultReadbackRow label="Flow revision">
                    <IdRefText value={result.activeFlowRevisionId} />
                </ResultReadbackRow>
                <ResultReadbackRow label="Compiled plan">
                    <IdRefText value={result.compiledPlanId} />
                </ResultReadbackRow>
                <ResultReadbackRow label="Manifest">
                    <p>{result.manifestDescription}</p>
                    <IdRefText className="mt-1" value={result.manifestPath} />
                </ResultReadbackRow>
            </dl>
        </TaskStartDialog>
    );
}

function ResultReadbackRow({
    children,
    label,
}: {
    readonly children: ReactNode;
    readonly label: string;
}) {
    return (
        <div className="grid gap-2 border-b border-outline-soft px-4 py-3 last:border-b-0 sm:grid-cols-[8.5rem_minmax(0,1fr)]">
            <dt className="font-mono text-label font-medium uppercase text-muted">{label}</dt>
            <dd className="min-w-0 text-compact text-foreground">{children}</dd>
        </div>
    );
}
