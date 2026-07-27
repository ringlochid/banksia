import { LoaderCircle, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export type PageStateKind = "loading" | "empty" | "error";

export interface PageStateProps {
    readonly actions?: ReactNode;
    readonly className?: string;
    readonly detail?: ReactNode;
    readonly fill?: boolean;
    readonly icon?: LucideIcon;
    readonly kind?: PageStateKind;
    readonly title: string;
}

/**
 * Shared page-level loading, empty, and failure presentation.
 *
 * All routes use the same centered geometry and type rhythm so state does not
 * jump between the top-left corner, a toolbar offset, and the middle of a
 * screen. Small inline waits still belong beside the action that caused them.
 */
export function PageState({
    actions,
    className = "",
    detail,
    fill = false,
    icon: Icon,
    kind = "empty",
    title,
}: PageStateProps) {
    const isLoading = kind === "loading";
    const isError = kind === "error";
    return (
        <section
            aria-live={isLoading ? "polite" : undefined}
            className={[
                "ui-page-state",
                `ui-page-state--${kind}`,
                fill ? "ui-page-state--fill" : "",
                className,
            ]
                .filter(Boolean)
                .join(" ")}
            role={isLoading ? "status" : isError ? "alert" : undefined}
        >
            <span aria-hidden="true" className="ui-page-state__icon">
                {isLoading ? (
                    <LoaderCircle className="ui-spin" size={20} />
                ) : Icon === undefined ? null : (
                    <Icon size={22} />
                )}
            </span>
            <div className="ui-page-state__copy">
                <h2>{title}</h2>
                {detail === undefined ? null : <p>{detail}</p>}
            </div>
            {actions === undefined ? null : (
                <div className="ui-page-state__actions">{actions}</div>
            )}
        </section>
    );
}
