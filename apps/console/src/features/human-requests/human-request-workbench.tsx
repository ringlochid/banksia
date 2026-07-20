import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button, FormField, StatePanel } from "../../components/ui";
import type { components } from "../../api/generated/openapi";
import { classNames } from "../../lib/classNames";
import { isStaleActionError, type HumanRequestsController } from "./human-request-controller";
import {
    getStructuredSchemaModel,
    type HumanRequestItemDraft,
    type HumanRequestValidationError,
    type StructuredSchemaField,
} from "./human-request-model";

type HumanRequestItem = components["schemas"]["HumanRequestItem"];

const fieldClassName =
    "min-h-control w-full min-w-0 rounded-control border border-outline-soft bg-surface-low px-3 py-2 text-compact text-foreground transition-colors placeholder:text-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary";

export function FocusedRequestWorkbench({
    controller,
}: {
    readonly controller: HumanRequestsController;
}) {
    const item = controller.selectedItem;
    const draft = controller.selectedItemDraft;
    const read = controller.selectedRead;
    const headingRef = useRef<HTMLHeadingElement>(null);
    const previousItemIdRef = useRef<string | null>(null);
    const isCompactLayout = useCompactHumanRequestLayout();

    useEffect(() => {
        const itemId = item?.id ?? null;
        if (previousItemIdRef.current !== null && previousItemIdRef.current !== itemId) {
            headingRef.current?.focus();
        }
        previousItemIdRef.current = itemId;
    }, [item?.id]);

    if (item === null || draft === null || read === null) {
        return null;
    }

    const itemErrors = controller.validationErrors.filter((error) => error.itemId === item.id);

    if (isCompactLayout) {
        return (
            <MobileFocusedRequestWorkbench
                controller={controller}
                draft={draft}
                item={item}
                itemErrors={itemErrors}
                read={read}
            />
        );
    }

    return (
        <section className="overflow-hidden rounded-card border border-outline-soft bg-surface">
            <header className="flex flex-col gap-3 border-b border-outline-soft px-3 py-2.5 2xl:flex-row 2xl:items-center 2xl:justify-between">
                <div className="min-w-0">
                    <SectionLabel>Current item</SectionLabel>
                    <h2
                        className="mt-1 font-mono text-utility text-muted"
                        ref={headingRef}
                        tabIndex={-1}
                    >
                        {item.id}
                    </h2>
                </div>
                <ItemNavigator controller={controller} read={read} />
            </header>
            <div className="divide-y divide-outline-soft">
                <WorkbenchRow label="Instruction">
                    <p className="text-compact text-foreground">
                        {read.request.suggested_human_instruction ??
                            "Answer every item using its controller-defined response contract."}
                    </p>
                </WorkbenchRow>
                <WorkbenchRow label="Question">
                    <p className="text-compact text-foreground">{item.prompt}</p>
                </WorkbenchRow>
                <WorkbenchRow label="Response">
                    <div className="space-y-2">
                        <ResponseControls
                            draft={draft}
                            item={item}
                            onUpdate={controller.updateSelectedItemDraft}
                        />
                        <StructuredInputControls
                            draft={draft}
                            item={item}
                            onUpdate={controller.updateSelectedItemDraft}
                        />
                    </div>
                </WorkbenchRow>
            </div>
            <ValidationAndActionState controller={controller} itemErrors={itemErrors} />
        </section>
    );
}

function MobileFocusedRequestWorkbench({
    controller,
    draft,
    item,
    itemErrors,
    read,
}: {
    readonly controller: HumanRequestsController;
    readonly draft: HumanRequestItemDraft;
    readonly item: HumanRequestItem;
    readonly itemErrors: readonly HumanRequestValidationError[];
    readonly read: components["schemas"]["HumanRequestRead"];
}) {
    return (
        <section className="space-y-4">
            <section className="rounded-card border border-outline-soft bg-surface-low p-4">
                <SectionLabel>Instruction</SectionLabel>
                <p className="mt-2 text-compact text-foreground">
                    {read.request.suggested_human_instruction ??
                        "Answer every item using its controller-defined response contract."}
                </p>
            </section>

            <section className="overflow-hidden rounded-card border border-outline-soft bg-surface-low">
                <MobileItemNavigator controller={controller} read={read} />
                <section className="border-t border-outline-soft px-4 py-3">
                    <SectionLabel>Question</SectionLabel>
                    <p className="mt-2 text-compact text-foreground">{item.prompt}</p>
                </section>
            </section>

            <section className="space-y-2">
                <SectionLabel>Response</SectionLabel>
                <ResponseControls
                    draft={draft}
                    item={item}
                    onUpdate={controller.updateSelectedItemDraft}
                />
                <StructuredInputControls
                    draft={draft}
                    item={item}
                    onUpdate={controller.updateSelectedItemDraft}
                />
            </section>

            <ValidationAndActionState controller={controller} itemErrors={itemErrors} />
        </section>
    );
}

function MobileItemNavigator({
    controller,
    read,
}: {
    readonly controller: HumanRequestsController;
    readonly read: components["schemas"]["HumanRequestRead"];
}) {
    const itemCount = read.request.items.length;

    return (
        <div className="flex items-center justify-between gap-3 px-4 py-3">
            <span className="font-display text-compact font-semibold text-foreground">
                {String(controller.selectedItemIndex + 1)} of {String(itemCount)}
            </span>
            <div className="flex items-center gap-2">
                <button
                    className="inline-flex h-8 items-center justify-center rounded-control border border-outline-soft bg-surface px-3 font-mono text-utility text-foreground transition-colors disabled:opacity-40"
                    disabled={controller.selectedItemIndex === 0}
                    onClick={() => {
                        controller.selectItemIndex(controller.selectedItemIndex - 1);
                    }}
                    type="button"
                >
                    Prev
                </button>
                <button
                    className="inline-flex h-8 items-center justify-center rounded-control border border-outline-soft bg-surface px-3 font-mono text-utility text-foreground transition-colors disabled:opacity-40"
                    disabled={controller.selectedItemIndex >= itemCount - 1}
                    onClick={() => {
                        controller.selectItemIndex(controller.selectedItemIndex + 1);
                    }}
                    type="button"
                >
                    Next
                </button>
            </div>
        </div>
    );
}

function useCompactHumanRequestLayout(): boolean {
    const [isCompact, setIsCompact] = useState(() => {
        if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
            return false;
        }

        return window.matchMedia("(max-width: 1023px)").matches;
    });

    useEffect(() => {
        if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
            return;
        }

        const mediaQuery = window.matchMedia("(max-width: 1023px)");
        const updateCompactLayout = () => {
            setIsCompact(mediaQuery.matches);
        };

        updateCompactLayout();
        mediaQuery.addEventListener("change", updateCompactLayout);
        return () => {
            mediaQuery.removeEventListener("change", updateCompactLayout);
        };
    }, []);

    return isCompact;
}

function ItemNavigator({
    controller,
    read,
}: {
    readonly controller: HumanRequestsController;
    readonly read: components["schemas"]["HumanRequestRead"];
}) {
    const requestDraft = controller.drafts[read.request.request_id];
    const itemCount = read.request.items.length;

    return (
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="font-display text-compact font-semibold text-foreground">
                    {String(controller.selectedItemIndex + 1)} of {String(itemCount)}
                </span>
                <div className="flex flex-wrap items-center gap-2">
                    {Array.from({ length: itemCount }, (_item, index) => {
                        const isSelected = index === controller.selectedItemIndex;
                        const item = read.request.items[index];
                        const itemDraft = requestDraft?.items[item.id];
                        const isComplete = !isSelected && isItemDraftComplete(itemDraft);

                        return (
                            <button
                                aria-label={`Item ${String(index + 1)}`}
                                className={classNames(
                                    "inline-flex h-8 min-w-8 items-center justify-center rounded-full border px-2 font-mono text-utility transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
                                    isSelected
                                        ? "border-primary/45 bg-primary-soft text-primary-foreground"
                                        : isComplete
                                          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                                          : "border-outline-soft bg-surface-low text-muted hover:border-primary/35 hover:text-foreground",
                                )}
                                key={index}
                                onClick={() => {
                                    controller.selectItemIndex(index);
                                }}
                                type="button"
                            >
                                {String(index + 1)}
                            </button>
                        );
                    })}
                </div>
            </div>
            <div className="flex flex-wrap gap-2">
                <button
                    className="inline-flex h-8 items-center justify-center rounded-full border border-outline-soft bg-surface-low px-3 font-mono text-utility text-foreground transition-colors disabled:opacity-40"
                    disabled={controller.selectedItemIndex === 0}
                    onClick={() => {
                        controller.selectItemIndex(controller.selectedItemIndex - 1);
                    }}
                    type="button"
                >
                    Previous
                </button>
                <button
                    className="inline-flex h-8 items-center justify-center rounded-full border border-outline-soft bg-surface-low px-3 font-mono text-utility text-foreground transition-colors disabled:opacity-40"
                    disabled={controller.selectedItemIndex >= itemCount - 1}
                    onClick={() => {
                        controller.selectItemIndex(controller.selectedItemIndex + 1);
                    }}
                    type="button"
                >
                    Next
                </button>
            </div>
        </div>
    );
}

function isItemDraftComplete(draft: HumanRequestItemDraft | undefined): boolean {
    if (draft === undefined) {
        return false;
    }

    return (
        draft.selectedOption !== null ||
        Object.values(draft.responseFields).some((value) => value?.trim().length) ||
        (draft.responseJson.trim() !== "" && draft.responseJson.trim() !== "{}")
    );
}

function ResponseControls({
    draft,
    item,
    onUpdate,
}: {
    readonly draft: HumanRequestItemDraft;
    readonly item: HumanRequestItem;
    readonly onUpdate: (patch: Partial<HumanRequestItemDraft>) => void;
}) {
    const options = item.options ?? [];
    return (
        <div className="space-y-2">
            {options.length === 0 ? null : (
                <fieldset className="space-y-2">
                    <legend className="sr-only">Response options</legend>
                    {options.map((option) => (
                        <label
                            className={classNames(
                                "flex cursor-pointer gap-3 rounded-card border px-3 py-2.5 transition-colors",
                                draft.selectedOption === option.id
                                    ? "border-primary/70 bg-primary-soft shadow-panel"
                                    : "border-outline-soft bg-surface-low hover:border-primary/25",
                            )}
                            key={option.id}
                        >
                            <input
                                checked={draft.selectedOption === option.id}
                                className="mt-1.5 size-2.5 shrink-0 appearance-none rounded-full border border-outline bg-surface checked:border-primary checked:bg-primary checked:shadow-[0_0_0_4px_rgba(59,130,246,0.16)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                                name={`option-${item.id}`}
                                onChange={() => {
                                    onUpdate({
                                        selectedOption: option.id,
                                    });
                                }}
                                type="radio"
                            />
                            <span className="min-w-0">
                                <span className="font-display text-compact font-semibold text-foreground">
                                    {option.title}
                                </span>
                                {option.description === null ||
                                option.description === undefined ? null : (
                                    <span className="mt-1 block text-utility text-muted">
                                        {option.description}
                                    </span>
                                )}
                            </span>
                        </label>
                    ))}
                </fieldset>
            )}
        </div>
    );
}

function StructuredInputControls({
    draft,
    item,
    onUpdate,
}: {
    readonly draft: HumanRequestItemDraft;
    readonly item: HumanRequestItem;
    readonly onUpdate: (patch: Partial<HumanRequestItemDraft>) => void;
}) {
    const schemaModel = getStructuredSchemaModel(item);
    if (schemaModel === null) {
        return null;
    }

    if (schemaModel.mode === "json") {
        return (
            <FormField id={`response-${item.id}`} label="JSON response">
                <textarea
                    className={classNames(fieldClassName, "font-mono")}
                    onChange={(event) => {
                        onUpdate({ responseJson: event.target.value });
                    }}
                    rows={5}
                    value={draft.responseJson}
                />
            </FormField>
        );
    }

    return (
        <div className="rounded-card border border-outline-soft bg-surface-muted p-4">
            <div className="grid gap-4 md:grid-cols-2">
                {schemaModel.fields.map((field) => (
                    <StructuredFieldControl
                        draft={draft}
                        field={field}
                        itemId={item.id}
                        key={field.name}
                        onUpdate={onUpdate}
                    />
                ))}
            </div>
        </div>
    );
}

function WorkbenchRow({
    children,
    label,
}: {
    readonly children: ReactNode;
    readonly label: string;
}) {
    return (
        <section className="px-3 py-3">
            <SectionLabel>{label}</SectionLabel>
            <div className="mt-2">{children}</div>
        </section>
    );
}

function StructuredFieldControl({
    draft,
    field,
    itemId,
    onUpdate,
}: {
    readonly draft: HumanRequestItemDraft;
    readonly field: StructuredSchemaField;
    readonly itemId: string;
    readonly onUpdate: (patch: Partial<HumanRequestItemDraft>) => void;
}) {
    const id = `payload-${itemId}-${field.name}`;
    const value = draft.responseFields[field.name] ?? "";
    const updateValue = (nextValue: string) => {
        onUpdate({
            responseFields: {
                ...draft.responseFields,
                [field.name]: nextValue,
            },
        });
    };

    return (
        <FormField id={id} label={field.title}>
            {field.type === "boolean" ? (
                <select
                    className={fieldClassName}
                    onChange={(event) => {
                        updateValue(event.target.value);
                    }}
                    value={value}
                >
                    <option value="">Choose true or false</option>
                    <option value="true">True</option>
                    <option value="false">False</option>
                </select>
            ) : (
                <input
                    className={fieldClassName}
                    onChange={(event) => {
                        updateValue(event.target.value);
                    }}
                    type={field.type === "string" ? "text" : "number"}
                    value={value}
                />
            )}
        </FormField>
    );
}

function ValidationAndActionState({
    controller,
    itemErrors,
}: {
    readonly controller: HumanRequestsController;
    readonly itemErrors: readonly HumanRequestValidationError[];
}) {
    const actionError = controller.actionError;
    const isStaleError = actionError !== null && isStaleActionError(actionError.code);
    if (itemErrors.length === 0 && actionError === null) {
        return null;
    }

    return (
        <div className="space-y-3 px-3 py-3">
            {itemErrors.length === 0 ? null : (
                <StatePanel
                    summary={
                        <ul className="list-disc space-y-1 pl-4">
                            {itemErrors.map((error) => (
                                <li key={`${error.itemId}-${error.message}`}>{error.message}</li>
                            ))}
                        </ul>
                    }
                    title="Response validation failed"
                    tone="stale"
                />
            )}
            {actionError === null ? null : (
                <StatePanel
                    action={
                        isStaleError ? (
                            <Button
                                disabled={controller.isLoading || controller.isRefreshing}
                                icon={
                                    <RefreshCw
                                        className={controller.isRefreshing ? "animate-spin" : ""}
                                    />
                                }
                                onClick={controller.refresh}
                                variant="secondary"
                            >
                                Reread current truth
                            </Button>
                        ) : undefined
                    }
                    summary={
                        <ActionErrorSummary
                            suggestedNextStep={actionError.suggestedNextStep}
                            summary={actionError.summary}
                        />
                    }
                    title={isStaleError ? "Request resolved elsewhere" : "Resolution failed"}
                    tone={isStaleError ? "stale" : "error"}
                />
            )}
        </div>
    );
}

function ActionErrorSummary({
    suggestedNextStep,
    summary,
}: {
    readonly suggestedNextStep: string | null;
    readonly summary: string;
}) {
    return (
        <div className="space-y-2">
            <p>{summary}</p>
            {suggestedNextStep === null ? null : (
                <p>
                    <span className="font-mono text-label font-medium uppercase">
                        Suggested next step
                    </span>{" "}
                    {suggestedNextStep}
                </p>
            )}
        </div>
    );
}

function SectionLabel({ children }: { readonly children: string }) {
    return <p className="font-mono text-label font-medium text-muted">{children}</p>;
}
