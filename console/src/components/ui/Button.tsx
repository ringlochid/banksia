import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonTone = "primary" | "secondary" | "quiet" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    readonly children: ReactNode;
    readonly tone?: ButtonTone;
}

export function Button({
    children,
    className = "",
    tone = "secondary",
    type = "button",
    ...props
}: ButtonProps) {
    return (
        <button
            className={`ui-button ui-button--${tone} ${className}`.trim()}
            type={type}
            {...props}
        >
            {children}
        </button>
    );
}
