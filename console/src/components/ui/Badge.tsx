import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "brand" | "accent";

export interface BadgeProps {
    readonly children: ReactNode;
    readonly tone?: BadgeTone;
}

export function Badge({ children, tone = "neutral" }: BadgeProps) {
    const toneClass = tone === "neutral" ? "" : ` ui-badge--${tone}`;
    return <span className={`ui-badge${toneClass}`}>{children}</span>;
}
