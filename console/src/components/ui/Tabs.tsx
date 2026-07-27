import * as RadixTabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

export interface TabItem {
    readonly value: string;
    readonly label: string;
}

export interface TabsProps {
    readonly value: string;
    readonly onValueChange: (value: string) => void;
    readonly items: readonly TabItem[];
    readonly children: ReactNode;
    readonly ariaLabel: string;
}

export function Tabs({
    ariaLabel,
    children,
    items,
    onValueChange,
    value,
}: TabsProps) {
    return (
        <RadixTabs.Root onValueChange={onValueChange} value={value}>
            <RadixTabs.List aria-label={ariaLabel} className="ui-tabs__list">
                {items.map((item) => (
                    <RadixTabs.Trigger
                        className="ui-tabs__trigger"
                        key={item.value}
                        value={item.value}
                    >
                        {item.label}
                    </RadixTabs.Trigger>
                ))}
            </RadixTabs.List>
            {children}
        </RadixTabs.Root>
    );
}

export interface TabPanelProps {
    readonly value: string;
    readonly children: ReactNode;
}

export function TabPanel({ children, value }: TabPanelProps) {
    return <RadixTabs.Content value={value}>{children}</RadixTabs.Content>;
}
