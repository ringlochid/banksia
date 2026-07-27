import * as RadixTooltip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export interface TooltipProviderProps {
    readonly children: ReactNode;
    readonly delayDuration?: number;
}

export function TooltipProvider({
    children,
    delayDuration = 400,
}: TooltipProviderProps) {
    return (
        <RadixTooltip.Provider delayDuration={delayDuration}>
            {children}
        </RadixTooltip.Provider>
    );
}

export interface TooltipProps {
    readonly children: ReactNode;
    readonly label: string;
    readonly side?: "top" | "right" | "bottom" | "left";
}

export function Tooltip({ children, label, side = "top" }: TooltipProps) {
    return (
        <RadixTooltip.Root>
            <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
            <RadixTooltip.Portal>
                <RadixTooltip.Content
                    className="ui-tooltip"
                    side={side}
                    sideOffset={6}
                >
                    {label}
                </RadixTooltip.Content>
            </RadixTooltip.Portal>
        </RadixTooltip.Root>
    );
}
