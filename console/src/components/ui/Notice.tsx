import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { ReactNode } from "react";

export type NoticeTone = "info" | "warning" | "danger" | "success";

export interface NoticeProps {
    readonly children: ReactNode;
    readonly title?: string;
    readonly tone?: NoticeTone;
    readonly urgent?: boolean;
}

const ICONS = {
    danger: XCircle,
    info: Info,
    success: CheckCircle2,
    warning: AlertTriangle,
} as const;

export function Notice({
    children,
    title,
    tone = "info",
    urgent = false,
}: NoticeProps) {
    const Icon = ICONS[tone];
    return (
        <section
            className={`ui-notice ui-notice--${tone}`}
            role={urgent ? "alert" : "status"}
        >
            <Icon aria-hidden="true" size={15} />
            <div className="ui-notice__body">
                {title === undefined ? null : (
                    <p className="ui-notice__title">{title}</p>
                )}
                <div>{children}</div>
            </div>
        </section>
    );
}
