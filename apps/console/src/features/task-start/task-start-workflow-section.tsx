import { useState } from "react";
import { Link } from "react-router-dom";

import { ArrowUpRight, Search } from "lucide-react";

import { Button, StatePanel } from "../../components/ui";
import type { TaskStartController } from "./task-start-controller";
import { isAuthError } from "./task-start-data";
import type { TaskStartWorkflowChoice } from "./task-start-model";
import { controlClassName } from "./task-start-ui";

export function WorkflowSection({ controller }: { readonly controller: TaskStartController }) {
    const [isSearchOpen, setSearchOpen] = useState(false);
    const showChoices =
        controller.listState.error !== null ||
        (controller.selectedWorkflowKey === null && controller.listState.isLoading) ||
        (isSearchOpen && controller.workflowQuery.trim().length > 0);

    return (
        <div
            className="space-y-3"
            onBlur={(event) => {
                const nextTarget = event.relatedTarget;
                if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
                    return;
                }
                setSearchOpen(false);
            }}
        >
            <WorkflowSearch
                controller={controller}
                onSearchOpen={() => {
                    setSearchOpen(true);
                }}
            />
            {showChoices ? (
                <WorkflowChoices
                    controller={controller}
                    onSelectWorkflow={(key) => {
                        controller.selectWorkflow(key);
                        setSearchOpen(false);
                    }}
                />
            ) : null}
            {showChoices ? null : <SelectedWorkflow controller={controller} />}
        </div>
    );
}

function WorkflowSearch({
    controller,
    onSearchOpen,
}: {
    readonly controller: TaskStartController;
    readonly onSearchOpen: () => void;
}) {
    return (
        <div className="min-w-0 flex-1">
            <label
                className="block font-display text-compact font-semibold text-foreground"
                htmlFor="task-start-workflow-search"
            >
                Search workflow
            </label>
            <div className="relative mt-2">
                <Search
                    aria-hidden="true"
                    className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted"
                />
                <input
                    aria-autocomplete="list"
                    aria-expanded={controller.workflowQuery.trim().length > 0}
                    className={controlClassName("pl-10")}
                    id="task-start-workflow-search"
                    onChange={(event) => {
                        onSearchOpen();
                        controller.updateWorkflowQuery(event.target.value);
                    }}
                    onFocus={onSearchOpen}
                    placeholder="Search stored workflows"
                    role="combobox"
                    type="search"
                    value={controller.workflowQuery}
                />
            </div>
            {controller.formErrors.workflow === undefined ? null : (
                <p className="mt-1 text-utility font-semibold text-danger">
                    {controller.formErrors.workflow}
                </p>
            )}
        </div>
    );
}

function WorkflowChoices({
    controller,
    onSelectWorkflow,
}: {
    readonly controller: TaskStartController;
    readonly onSelectWorkflow: (key: string) => void;
}) {
    const { listState } = controller;

    if (listState.isLoading) {
        return <CompactStatePanel title="Loading workflows" />;
    }

    if (listState.error !== null) {
        return (
            <StatePanel
                action={<Button onClick={controller.refresh}>Retry</Button>}
                summary={listState.error.summary}
                title={
                    isAuthError(listState.error)
                        ? "Access to workflows failed"
                        : "Workflows could not load"
                }
                tone={isAuthError(listState.error) ? "auth" : "error"}
            />
        );
    }

    if (listState.rows.length === 0) {
        return (
            <CompactStatePanel
                summary={
                    controller.workflowQuery.trim().length === 0
                        ? "Type a workflow key or description."
                        : "No stored workflows match this search."
                }
                title={
                    controller.workflowQuery.trim().length === 0
                        ? "Select a stored workflow"
                        : "No matching workflows"
                }
            />
        );
    }

    return (
        <ol
            aria-label="Workflow choices"
            className="overflow-hidden rounded-card border border-outline-soft bg-surface-low shadow-panel"
        >
            {listState.rows.map((workflow) => (
                <li className="border-b border-outline-soft last:border-b-0" key={workflow.key}>
                    <WorkflowChoiceButton
                        onSelect={() => {
                            onSelectWorkflow(workflow.key);
                        }}
                        workflow={workflow}
                    />
                </li>
            ))}
        </ol>
    );
}

function CompactStatePanel({
    summary,
    title,
}: {
    readonly summary?: string;
    readonly title: string;
}) {
    return (
        <div className="rounded-card border border-outline-soft bg-surface-low px-4 py-3 shadow-hairline">
            <p className="font-display text-compact font-semibold text-foreground">{title}</p>
            {summary === undefined ? null : (
                <p className="mt-1 text-compact text-muted">{summary}</p>
            )}
        </div>
    );
}

function WorkflowChoiceButton({
    onSelect,
    workflow,
}: {
    readonly onSelect: () => void;
    readonly workflow: TaskStartWorkflowChoice;
}) {
    return (
        <button
            className="grid w-full min-w-0 gap-1 bg-surface-low px-4 py-3 text-left transition-colors hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary"
            onClick={onSelect}
            type="button"
        >
            <span className="min-w-0 truncate font-mono text-compact font-semibold text-foreground">
                {workflow.key}
            </span>
            <span className="break-words text-compact text-muted">
                {workflow.description ?? "No description reported."}
            </span>
        </button>
    );
}

function SelectedWorkflow({ controller }: { readonly controller: TaskStartController }) {
    if (controller.selectedWorkflowKey === null) {
        return (
            <div className="rounded-card border border-outline-soft bg-surface-low p-4 shadow-hairline">
                <p className="font-mono text-label font-medium text-muted">Selected workflow</p>
                <p className="mt-1 text-compact text-muted">Select a stored workflow.</p>
            </div>
        );
    }

    if (!controller.isSelectedWorkflowInRows && controller.listState.hasLoaded) {
        return (
            <StatePanel
                summary="The selected workflow is no longer present in the current search result."
                title="Selected workflow is outside the current search"
                tone="stale"
            />
        );
    }

    if (controller.detailState.error !== null) {
        return (
            <StatePanel
                action={<Button onClick={controller.refresh}>Retry</Button>}
                summary={controller.detailState.error.summary}
                title={
                    isAuthError(controller.detailState.error)
                        ? "Access to selected workflow failed"
                        : "Selected workflow could not load"
                }
                tone={isAuthError(controller.detailState.error) ? "auth" : "stale"}
            />
        );
    }

    if (controller.selectedWorkflow === null) {
        return null;
    }

    const selectedWorkflowUpdatedAt =
        controller.detailState.detail?.updatedAt ?? controller.selectedWorkflow.updatedAt;
    const selectedWorkflowUpdatedAtLabel = formatTaskStartTimestamp(selectedWorkflowUpdatedAt);
    const selectedDescription =
        controller.detailState.detail?.description ??
        controller.selectedWorkflow.description ??
        "No workflow description reported.";

    return (
        <div
            aria-label="Selected workflow"
            className="rounded-card border border-outline-soft bg-surface-low px-4 py-3 shadow-hairline"
            role="group"
        >
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                    <p className="font-mono text-label font-medium text-muted">Selected workflow</p>
                    <h2 className="mt-1 break-all font-mono text-compact font-semibold text-foreground">
                        {controller.selectedWorkflow.key}
                    </h2>
                    <p className="mt-2 max-w-3xl break-words text-utility text-muted">
                        {selectedDescription}
                    </p>
                </div>
                <div className="flex w-full min-w-0 flex-col items-end gap-2 lg:w-auto lg:shrink-0">
                    <span
                        aria-label={`Updated ${selectedWorkflowUpdatedAtLabel}`}
                        className="inline-flex max-w-full items-center gap-2 rounded-full bg-surface-high px-3 py-1 font-mono text-utility text-muted"
                    >
                        <span>Updated</span>
                        <span className="font-mono text-utility">
                            {selectedWorkflowUpdatedAtLabel}
                        </span>
                    </span>
                    <Link
                        className="inline-flex h-control w-full items-center justify-center gap-2 rounded-control border border-outline bg-surface-low px-4 text-utility font-semibold text-foreground transition-colors hover:border-primary/45 hover:text-primary-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:w-auto"
                        to={workflowDefinitionRoute(controller.selectedWorkflow.key)}
                    >
                        Open definition details
                        <ArrowUpRight aria-hidden="true" className="size-4 shrink-0" />
                    </Link>
                </div>
            </div>
        </div>
    );
}

function workflowDefinitionRoute(key: string): string {
    const query = new URLSearchParams({
        key,
        kind: "workflow",
    });
    return `/definitions?${query.toString()}`;
}

function formatTaskStartTimestamp(value: string): string {
    const date = new Date(value);

    if (Number.isNaN(date.valueOf())) {
        return value;
    }

    return new Intl.DateTimeFormat("en-AU", {
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        month: "short",
        timeZone: "Australia/Sydney",
        timeZoneName: "short",
        year: "numeric",
    }).format(date);
}
