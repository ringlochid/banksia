import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends HTMLAttributes<HTMLElement> {
    readonly children: ReactNode;
    readonly as?: "article" | "section" | "div";
}

export function Card({
    as: Element = "section",
    children,
    className = "",
    ...props
}: CardProps) {
    return (
        <Element className={`ui-card ${className}`.trim()} {...props}>
            {children}
        </Element>
    );
}
