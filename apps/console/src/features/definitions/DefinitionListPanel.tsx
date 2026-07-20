import type { ReactNode } from "react";

import { ChevronDown, Search } from "lucide-react";

import { Button, StatePanel, StatusChip } from "../../components/ui";
import { classNames } from "../../lib/classNames";
import { isAuthError, type DefinitionsController } from "./definition-controller";
import {
    DEFINITION_KIND_OPTIONS,
    DEFINITION_SORT_OPTIONS,
    NODE_KIND_FILTERS,
    kindLabel,
    listLabelForKind,
    type DefinitionListSort,
    type DefinitionRow,
    type NodeKind,
} from "./definition-model";

export function DefinitionsHeaderControls({
    controller,
}: {
    readonly controller: DefinitionsController;
}) {
    return (
        <div className="space-y-5">
            <DefinitionsKindSwitch controller={controller} />
            <DefinitionsControls controller={controller} />
        </div>
    );
}

export function DefinitionListPanel({
    controller,
}: {
    readonly controller: DefinitionsController;
}) {
    const { listState } = controller;

    if (listState.isLoading) {
        return (
            <DefinitionListStateShell controller={controller}>
                <StatePanel
                    summary="Reading stored registry rows from the selected definition route."
                    title="Loading Definitions"
                    tone="loading"
                />
            </DefinitionListStateShell>
        );
    }

    if (listState.error !== null) {
        return (
            <DefinitionListStateShell controller={controller}>
                <StatePanel
                    action={<Button onClick={controller.refresh}>Retry</Button>}
                    summary={listState.error.summary}
                    title={
                        isAuthError(listState.error)
                            ? "Access to Definitions failed"
                            : "Definitions could not load"
                    }
                    tone={isAuthError(listState.error) ? "auth" : "error"}
                />
            </DefinitionListStateShell>
        );
    }

    if (listState.rows.length === 0) {
        if (controller.hasActiveNarrowing) {
            return (
                <DefinitionListStateShell controller={controller}>
                    <StatePanel
                        action={<Button onClick={controller.clearFilters}>Clear filters</Button>}
                        summary={`No ${listLabelForKind(controller.kind)} match the current search or ${controller.activeFilterSummary.toLowerCase()}.`}
                        title={`No matching ${listLabelForKind(controller.kind)}`}
                        tone="empty"
                    />
                </DefinitionListStateShell>
            );
        }

        return (
            <DefinitionListStateShell controller={controller}>
                <StatePanel
                    summary={`The controller did not return stored ${listLabelForKind(controller.kind)}.`}
                    title={`No stored ${listLabelForKind(controller.kind)}`}
                    tone="empty"
                />
            </DefinitionListStateShell>
        );
    }

    return (
        <div className="definition-list-shell">
            <div className="hidden border-b border-outline-soft bg-surface-muted px-5 py-3 font-mono text-label font-medium uppercase text-muted lg:grid lg:grid-cols-[minmax(0,1fr)_8rem] lg:items-center lg:gap-4">
                <span id="definitions-list-heading">{kindLabel(controller.singularKind)}s</span>
                <span>Updated</span>
            </div>
            <ol aria-label="Definition rows" className="definition-list-body space-y-2 px-3 py-3">
                {listState.rows.map((row) => (
                    <li key={row.key}>
                        <DefinitionRowButton
                            isSelected={controller.selectedKey === row.key}
                            onSelect={() => {
                                controller.selectDefinition(row.key);
                            }}
                            row={row}
                        />
                    </li>
                ))}
            </ol>
            <DefinitionListFooter controller={controller} />
        </div>
    );
}

function DefinitionsKindSwitch({ controller }: { readonly controller: DefinitionsController }) {
    return (
        <div aria-label="Definition kind" className="flex min-w-0 flex-wrap gap-2" role="group">
            {DEFINITION_KIND_OPTIONS.map((option) => {
                const isSelected = option.listKind === controller.kind;
                return (
                    <button
                        aria-pressed={isSelected}
                        className={classNames(
                            "kind-button inline-flex h-control items-center justify-center gap-3 rounded-control border px-4 text-utility font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
                            isSelected
                                ? "border-primary/25 bg-active text-active-foreground"
                                : "border-outline bg-surface-low text-foreground hover:border-primary/45 hover:bg-surface-muted",
                        )}
                        key={option.listKind}
                        onClick={() => {
                            controller.setKind(option.listKind);
                        }}
                        type="button"
                    >
                        <span
                            aria-hidden="true"
                            className={classNames(
                                "size-2 rounded-full",
                                isSelected ? "bg-primary" : "bg-outline-soft",
                            )}
                        />
                        <span>{option.label}</span>
                    </button>
                );
            })}
        </div>
    );
}

function DefinitionsControls({ controller }: { readonly controller: DefinitionsController }) {
    return (
        <div
            className={classNames(
                "grid gap-3",
                controller.kind === "workflows"
                    ? "lg:grid-cols-[minmax(0,1fr)_220px]"
                    : "lg:grid-cols-[minmax(0,1fr)_220px_220px]",
            )}
        >
            <div>
                <label className="sr-only" htmlFor="definitions-query">
                    Search
                </label>
                <div className="relative">
                    <Search
                        aria-hidden="true"
                        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted"
                    />
                    <input
                        className={controlClassName("pl-10")}
                        id="definitions-query"
                        onChange={(event) => {
                            controller.setQuery(event.target.value);
                        }}
                        placeholder={`Search ${listLabelForKind(controller.kind)}`}
                        type="search"
                        value={controller.query}
                    />
                </div>
            </div>
            <KindFilterSelect controller={controller} />
            <DefinitionSelect
                id="definitions-sort"
                label="Sort"
                onChange={(value) => {
                    controller.setSort(value as DefinitionListSort);
                }}
                options={DEFINITION_SORT_OPTIONS}
                value={controller.sort}
            />
        </div>
    );
}

function KindFilterSelect({ controller }: { readonly controller: DefinitionsController }) {
    if (controller.kind === "roles") {
        return (
            <DefinitionSelect
                id="definitions-role-filter"
                label="Allowed node kind"
                onChange={(value) => {
                    controller.setRoleNodeKindFilter(value as NodeKind | "any");
                }}
                options={[
                    { label: "Allowed node kind", value: "any" },
                    ...NODE_KIND_FILTERS.map((option) => ({
                        label: option.label,
                        value: option.value,
                    })),
                ]}
                value={controller.roleNodeKindFilter}
            />
        );
    }

    if (controller.kind === "policies") {
        return (
            <DefinitionSelect
                id="definitions-policy-filter"
                label="Applies to"
                onChange={(value) => {
                    controller.setAppliesToFilter(value as NodeKind | "any");
                }}
                options={[
                    { label: "Applies to", value: "any" },
                    ...NODE_KIND_FILTERS.map((option) => ({
                        label: option.label,
                        value: option.value,
                    })),
                ]}
                value={controller.appliesToFilter}
            />
        );
    }

    return null;
}

function DefinitionSelect({
    id,
    label,
    onChange,
    options,
    value,
}: {
    readonly id: string;
    readonly label: string;
    readonly onChange: (value: string) => void;
    readonly options: readonly { readonly label: string; readonly value: string }[];
    readonly value: string;
}) {
    return (
        <label className="relative block" htmlFor={id}>
            <span className="sr-only">{label}</span>
            <select
                aria-label={label}
                className={controlClassName("appearance-none bg-none pr-10")}
                id={id}
                onChange={(event) => {
                    onChange(event.target.value);
                }}
                value={value}
            >
                {options.map((option) => (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                ))}
            </select>
            <ChevronDown
                aria-hidden="true"
                className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-foreground"
            />
        </label>
    );
}

function DefinitionListStateShell({
    children,
    controller,
}: {
    readonly children: ReactNode;
    readonly controller: DefinitionsController;
}) {
    return (
        <div className="definition-list-shell">
            <span className="sr-only" id="definitions-list-heading">
                {kindLabel(controller.singularKind)}s
            </span>
            <div className="definition-list-state-body">{children}</div>
        </div>
    );
}

function DefinitionRowButton({
    isSelected,
    onSelect,
    row,
}: {
    readonly isSelected: boolean;
    readonly onSelect: () => void;
    readonly row: DefinitionRow;
}) {
    return (
        <button
            aria-pressed={isSelected}
            className={classNames(
                "definition-row block w-full min-w-0 rounded-card border bg-surface-low text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary",
                isSelected ? "border-primary/35" : "border-outline-soft",
            )}
            onClick={onSelect}
            type="button"
        >
            <div className="space-y-3 px-4 py-3 sm:px-6 md:grid md:grid-cols-[minmax(0,1fr)_8rem] md:items-start md:gap-4 md:space-y-0">
                <div className="min-w-0 space-y-1.5">
                    <div className="space-y-0.5">
                        <span className="definition-title min-w-0 break-words font-display text-body font-semibold text-foreground">
                            {row.key}
                        </span>
                        <p className="definition-summary text-compact text-muted">
                            {row.description ?? "No description reported."}
                        </p>
                    </div>
                    <div className="flex min-w-0 flex-wrap gap-2">
                        {row.compatibilityLabels.map((label) => (
                            <StatusChip key={label}>{label}</StatusChip>
                        ))}
                    </div>
                </div>
                <div className="flex items-start justify-between gap-3 text-right md:block">
                    <span className="font-mono text-label font-medium uppercase text-muted md:sr-only">
                        Updated
                    </span>
                    <time
                        className="block font-body text-compact text-foreground md:whitespace-nowrap"
                        dateTime={row.updatedAt}
                    >
                        {formatRowUpdatedDate(row.updatedAt)}
                    </time>
                </div>
            </div>
        </button>
    );
}

function DefinitionListFooter({ controller }: { readonly controller: DefinitionsController }) {
    const { listState } = controller;
    if (listState.rows.length === 0) {
        return null;
    }

    return (
        <footer className="flex flex-col gap-3 border-t border-outline-soft bg-surface px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-compact text-muted">
                {String(listState.rows.length)} {listLabelForKind(controller.kind)} loaded.
            </p>
            {listState.nextCursor === null ? null : (
                <Button
                    disabled={
                        listState.isLoading || listState.isLoadingMore || listState.isRefreshing
                    }
                    onClick={controller.loadMore}
                >
                    {listState.isLoadingMore ? "Loading" : "Load more"}
                </Button>
            )}
        </footer>
    );
}

function formatRowUpdatedDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) {
        return value;
    }

    return new Intl.DateTimeFormat(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
    }).format(date);
}

function controlClassName(extraClassName?: string): string {
    return classNames(
        "h-control w-full rounded-control border border-outline bg-surface-low px-4 text-compact text-foreground shadow-hairline transition-colors placeholder:text-muted focus:border-primary/50 focus:outline-none focus:ring-2 focus:ring-primary/15",
        extraClassName,
    );
}
