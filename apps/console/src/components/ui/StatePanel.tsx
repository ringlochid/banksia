import type { ReactNode } from "react";

import {
    AlertTriangle,
    CheckCircle2,
    Inbox,
    LoaderCircle,
    RefreshCw,
    ShieldAlert,
} from "lucide-react";

import { classNames } from "../../lib/classNames";

export type StatePanelTone = "auth" | "empty" | "error" | "loading" | "stale" | "success";

export interface StatePanelProps {
    readonly action?: ReactNode;
    readonly className?: string;
    readonly summary?: ReactNode;
    readonly title: string;
    readonly tone?: StatePanelTone;
}

const toneClasses: Record<StatePanelTone, string> = {
    auth: "border-danger/25 bg-danger-soft text-danger",
    empty: "border-outline-soft bg-surface-muted text-muted",
    error: "border-danger/25 bg-danger-soft text-danger",
    loading: "border-primary/20 bg-primary-soft text-primary-foreground",
    stale: "border-warning/30 bg-warning-soft text-warning",
    success: "border-success/25 bg-success-soft text-success",
};

const iconClasses: Record<StatePanelTone, string> = {
    auth: "text-danger",
    empty: "text-muted",
    error: "text-danger",
    loading: "text-primary",
    stale: "text-warning",
    success: "text-success",
};

export function StatePanel({ action, className, summary, title, tone = "empty" }: StatePanelProps) {
    const role = tone === "auth" || tone === "error" || tone === "stale" ? "alert" : "status";

    return (
        <section
            className={classNames("rounded-card border p-4", toneClasses[tone], className)}
            role={role}
        >
            <div className="flex items-start gap-3">
                {renderStateIcon(tone)}
                <div className="min-w-0 flex-1">
                    <h2 className="font-display text-compact font-semibold text-foreground">
                        {title}
                    </h2>
                    {summary === undefined ? null : (
                        <div className="mt-1 text-compact text-muted">{summary}</div>
                    )}
                    {action === undefined ? null : (
                        <div className="mt-3 flex flex-wrap gap-2">{action}</div>
                    )}
                </div>
            </div>
        </section>
    );
}

function renderStateIcon(tone: StatePanelTone) {
    const className = classNames(
        "mt-0.5 size-4 shrink-0",
        tone === "loading" && "animate-spin",
        iconClasses[tone],
    );

    switch (tone) {
        case "auth":
            return <ShieldAlert aria-hidden="true" className={className} />;
        case "error":
            return <AlertTriangle aria-hidden="true" className={className} />;
        case "loading":
            return <LoaderCircle aria-hidden="true" className={className} />;
        case "stale":
            return <RefreshCw aria-hidden="true" className={className} />;
        case "success":
            return <CheckCircle2 aria-hidden="true" className={className} />;
        case "empty":
            return <Inbox aria-hidden="true" className={className} />;
    }
}
