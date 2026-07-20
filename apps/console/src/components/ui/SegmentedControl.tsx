import type { ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export interface SegmentedControlOption<Value extends string> {
    readonly disabled?: boolean;
    readonly icon?: ReactNode;
    readonly label: string;
    readonly value: Value;
}

export interface SegmentedControlProps<Value extends string> {
    readonly label: string;
    readonly onChange: (value: Value) => void;
    readonly options: readonly SegmentedControlOption<Value>[];
    readonly value: Value;
}

export function SegmentedControl<Value extends string>({
    label,
    onChange,
    options,
    value,
}: SegmentedControlProps<Value>) {
    return (
        <div aria-label={label} className="inline-flex min-w-0 flex-wrap gap-2" role="group">
            {options.map((option) => {
                const isSelected = option.value === value;

                return (
                    <button
                        aria-pressed={isSelected}
                        className={classNames(
                            "inline-flex h-control items-center justify-center gap-2 rounded-control border px-3 text-utility font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55",
                            isSelected
                                ? "border-primary/25 bg-active text-active-foreground"
                                : "border-outline bg-surface-low text-foreground hover:border-primary/45 hover:text-primary-foreground",
                        )}
                        disabled={option.disabled}
                        key={option.value}
                        onClick={() => {
                            onChange(option.value);
                        }}
                        type="button"
                    >
                        {option.icon === undefined ? null : (
                            <span aria-hidden="true" className="inline-flex size-4 shrink-0">
                                {option.icon}
                            </span>
                        )}
                        <span className="min-w-0 truncate">{option.label}</span>
                    </button>
                );
            })}
        </div>
    );
}
