import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { WorkflowSearchItem } from "./run-api";

export interface WorkflowPickerProps {
    readonly "aria-describedby"?: string;
    readonly "aria-invalid"?: boolean | "false" | "true";
    readonly disabled?: boolean;
    readonly id?: string;
    readonly onValueChange: (value: string) => void;
    readonly value: string;
    readonly workflows: readonly WorkflowSearchItem[];
}

export function WorkflowPicker({
    disabled = false,
    id,
    onValueChange,
    value,
    workflows,
    ...ariaProps
}: WorkflowPickerProps) {
    const generatedId = useId();
    const listboxId = `${id ?? generatedId}-listbox`;
    const searchRef = useRef<HTMLInputElement>(null);
    const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
    const [isOpen, setIsOpen] = useState(false);
    const [query, setQuery] = useState("");
    const selected = workflows.find(
        (workflow) => workflow.workflow_id === value,
    );
    const matches = useMemo(() => {
        const normalized = query.trim().toLocaleLowerCase();
        if (normalized === "") {
            return workflows;
        }
        return workflows.filter((workflow) =>
            `${workflow.workflow_id} ${workflow.description}`
                .toLocaleLowerCase()
                .includes(normalized),
        );
    }, [query, workflows]);

    const choose = (workflowId: string) => {
        onValueChange(workflowId);
        setQuery("");
        setIsOpen(false);
    };

    const handleSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === "ArrowDown") {
            event.preventDefault();
            optionRefs.current[0]?.focus();
        } else if (event.key === "Enter" && matches[0] !== undefined) {
            event.preventDefault();
            choose(matches[0].workflow_id);
        }
    };

    const focusAdjacentOption = (
        event: KeyboardEvent<HTMLButtonElement>,
        index: number,
    ) => {
        const nextIndex =
            event.key === "ArrowDown"
                ? Math.min(index + 1, matches.length - 1)
                : event.key === "ArrowUp"
                  ? index - 1
                  : null;
        if (nextIndex === null) {
            return;
        }
        event.preventDefault();
        if (nextIndex < 0) {
            searchRef.current?.focus();
        } else {
            optionRefs.current[nextIndex]?.focus();
        }
    };

    return (
        <Popover.Root
            onOpenChange={(open) => {
                setIsOpen(open);
                if (!open) {
                    setQuery("");
                }
            }}
            open={isOpen}
        >
            <Popover.Trigger asChild>
                <button
                    {...ariaProps}
                    aria-controls={listboxId}
                    aria-expanded={isOpen}
                    aria-haspopup="listbox"
                    className="run-workflow-picker__trigger"
                    disabled={disabled}
                    id={id}
                    role="combobox"
                    type="button"
                >
                    <span className="run-workflow-picker__value">
                        <Search aria-hidden="true" size={15} />
                        {selected?.workflow_id ?? "Search Workflows"}
                    </span>
                    <ChevronsUpDown
                        aria-hidden="true"
                        className="run-workflow-picker__chevrons"
                        size={15}
                    />
                </button>
            </Popover.Trigger>
            <Popover.Portal>
                <Popover.Content
                    align="start"
                    className="run-workflow-picker__content"
                    onOpenAutoFocus={(event) => {
                        event.preventDefault();
                        searchRef.current?.focus();
                    }}
                    sideOffset={4}
                >
                    <div className="run-workflow-picker__search">
                        <Search aria-hidden="true" size={15} />
                        <label
                            className="sr-only"
                            htmlFor={`${listboxId}-search`}
                        >
                            Search Workflows
                        </label>
                        <input
                            autoComplete="off"
                            id={`${listboxId}-search`}
                            onChange={(event) => setQuery(event.target.value)}
                            onKeyDown={handleSearchKeyDown}
                            placeholder="Search Workflows"
                            ref={searchRef}
                            type="search"
                            value={query}
                        />
                    </div>
                    <div
                        aria-label="Workflows"
                        className="run-workflow-picker__list"
                        id={listboxId}
                        role="listbox"
                    >
                        {matches.length === 0 ? (
                            <p className="run-workflow-picker__empty">
                                No Workflows match this search
                            </p>
                        ) : (
                            matches.map((workflow, index) => (
                                <button
                                    aria-selected={
                                        workflow.workflow_id === value
                                    }
                                    className="run-workflow-picker__option"
                                    key={workflow.workflow_id}
                                    onClick={() => choose(workflow.workflow_id)}
                                    onKeyDown={(event) =>
                                        focusAdjacentOption(event, index)
                                    }
                                    ref={(node) => {
                                        optionRefs.current[index] = node;
                                    }}
                                    role="option"
                                    type="button"
                                >
                                    <span className="run-workflow-picker__option-copy">
                                        <strong>{workflow.workflow_id}</strong>
                                        <span>{workflow.description}</span>
                                    </span>
                                    {workflow.workflow_id === value ? (
                                        <Check aria-hidden="true" size={15} />
                                    ) : null}
                                </button>
                            ))
                        )}
                    </div>
                </Popover.Content>
            </Popover.Portal>
        </Popover.Root>
    );
}
