import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonTone = "primary" | "secondary" | "quiet" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    readonly children: ReactNode;
    readonly tone?: ButtonTone;
    readonly size?: ButtonSize;
    /** Square button holding a single icon. Requires an accessible label. */
    readonly icon?: boolean;
}

export function Button({
    children,
    className = "",
    icon = false,
    size = "md",
    tone = "secondary",
    type = "button",
    ...props
}: ButtonProps) {
    const classes = [
        "ui-button",
        `ui-button--${tone}`,
        size === "md" ? "" : `ui-button--${size}`,
        icon ? "ui-button--icon" : "",
        className,
    ]
        .filter(Boolean)
        .join(" ");
    return (
        <button className={classes} type={type} {...props}>
            {children}
        </button>
    );
}
