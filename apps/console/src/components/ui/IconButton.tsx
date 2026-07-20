import type { ButtonHTMLAttributes, ReactNode } from "react";

import { classNames } from "../../lib/classNames";
import type { ButtonVariant } from "./Button";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    readonly icon: ReactNode;
    readonly label: string;
    readonly variant?: ButtonVariant;
}

const iconButtonVariantClasses: Record<ButtonVariant, string> = {
    danger: "border-danger/30 bg-surface-low text-danger hover:bg-danger-soft focus-visible:bg-danger-soft",
    ghost: "border-transparent bg-transparent text-muted hover:bg-surface-muted hover:text-foreground",
    primary: "border-primary bg-primary text-white shadow-sm hover:bg-primary-foreground",
    secondary:
        "border-outline bg-surface-low text-foreground hover:border-primary/45 hover:text-primary-foreground",
};

export function IconButton({
    className,
    icon,
    label,
    title,
    type = "button",
    variant = "secondary",
    ...props
}: IconButtonProps) {
    return (
        <button
            aria-label={label}
            className={classNames(
                "inline-flex size-icon-control items-center justify-center rounded-control border px-0 text-utility font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55",
                iconButtonVariantClasses[variant],
                className,
            )}
            title={title ?? label}
            type={type}
            {...props}
        >
            <span aria-hidden="true" className="inline-flex size-4 items-center justify-center">
                {icon}
            </span>
        </button>
    );
}
