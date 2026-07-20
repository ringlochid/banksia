import type { ButtonHTMLAttributes, ReactNode } from "react";

import { classNames } from "../../lib/classNames";

export type ButtonVariant = "danger" | "ghost" | "primary" | "secondary";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    readonly icon?: ReactNode;
    readonly variant?: ButtonVariant;
}

const buttonVariantClasses: Record<ButtonVariant, string> = {
    danger: "border-danger/30 bg-surface-low text-danger hover:bg-danger-soft focus-visible:bg-danger-soft",
    ghost: "border-transparent bg-transparent text-muted hover:bg-surface-muted hover:text-foreground",
    primary: "border-primary bg-primary text-primary-contrast shadow-sm hover:bg-primary-hover",
    secondary:
        "border-outline bg-surface-low text-foreground hover:border-primary/45 hover:text-primary-foreground",
};

const buttonBaseClasses =
    "inline-flex h-control items-center justify-center gap-2 rounded-control border text-utility font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55";

export function Button({
    children,
    className,
    icon,
    type = "button",
    variant = "secondary",
    ...props
}: ButtonProps) {
    return (
        <button
            className={classNames(
                buttonBaseClasses,
                "px-4",
                buttonVariantClasses[variant],
                className,
            )}
            type={type}
            {...props}
        >
            {icon === undefined ? null : (
                <span aria-hidden="true" className="inline-flex size-4 shrink-0 items-center">
                    {icon}
                </span>
            )}
            <span className="min-w-0 truncate">{children}</span>
        </button>
    );
}
