import type { KeyboardEvent } from "react";
import { useRef } from "react";

import { classNames } from "../../lib/classNames";

export interface TabOption<Value extends string> {
    readonly disabled?: boolean;
    readonly label: string;
    readonly panelId?: string;
    readonly tabId?: string;
    readonly value: Value;
}

export interface TabsProps<Value extends string> {
    readonly label: string;
    readonly onChange: (value: Value) => void;
    readonly tabs: readonly TabOption<Value>[];
    readonly value: Value;
}

export function Tabs<Value extends string>({ label, onChange, tabs, value }: TabsProps<Value>) {
    const tabRefs = useRef(new Map<Value, HTMLButtonElement>());
    const enabledTabs = tabs.filter((tab) => tab.disabled !== true);

    const getTargetTab = (currentValue: Value, key: string): TabOption<Value> | null => {
        if (enabledTabs.length === 0) {
            return null;
        }

        const currentIndex = enabledTabs.findIndex((tab) => tab.value === currentValue);
        const selectedIndex = enabledTabs.findIndex((tab) => tab.value === value);
        const activeIndex = currentIndex === -1 ? Math.max(selectedIndex, 0) : currentIndex;

        switch (key) {
            case "ArrowDown":
            case "ArrowRight":
                return enabledTabs[(activeIndex + 1) % enabledTabs.length] ?? null;
            case "ArrowLeft":
            case "ArrowUp":
                return (
                    enabledTabs[(activeIndex - 1 + enabledTabs.length) % enabledTabs.length] ?? null
                );
            case "End":
                return enabledTabs[enabledTabs.length - 1] ?? null;
            case "Home":
                return enabledTabs[0] ?? null;
            default:
                return null;
        }
    };

    const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, currentValue: Value) => {
        const targetTab = getTargetTab(currentValue, event.key);

        if (targetTab === null) {
            return;
        }

        event.preventDefault();
        onChange(targetTab.value);
        tabRefs.current.get(targetTab.value)?.focus();
    };

    return (
        <div aria-label={label} className="flex min-w-0 flex-wrap gap-2" role="tablist">
            {tabs.map((tab) => {
                const isSelected = tab.value === value;
                const tabId =
                    tab.tabId ??
                    (tab.panelId === undefined ? undefined : tabIdForPanel(tab.panelId));

                return (
                    <button
                        aria-controls={tab.panelId}
                        aria-selected={isSelected}
                        className={classNames(
                            "inline-flex h-9 items-center justify-center rounded-control border px-3 text-utility font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55",
                            isSelected
                                ? "border-primary/25 bg-primary-soft text-primary-foreground"
                                : "border-transparent bg-surface-muted text-muted hover:bg-surface-high hover:text-foreground",
                        )}
                        disabled={tab.disabled}
                        id={tabId}
                        key={tab.value}
                        onClick={() => {
                            onChange(tab.value);
                        }}
                        onKeyDown={(event) => {
                            handleTabKeyDown(event, tab.value);
                        }}
                        ref={(node) => {
                            if (node === null) {
                                tabRefs.current.delete(tab.value);
                                return;
                            }

                            tabRefs.current.set(tab.value, node);
                        }}
                        role="tab"
                        tabIndex={isSelected ? 0 : -1}
                        type="button"
                    >
                        {tab.label}
                    </button>
                );
            })}
        </div>
    );
}

function tabIdForPanel(panelId: string): string {
    return `${panelId}-tab`;
}
