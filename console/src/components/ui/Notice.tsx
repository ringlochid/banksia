import type { ReactNode } from "react";

export interface NoticeProps {
    readonly children: ReactNode;
    readonly title?: string;
    readonly tone?: "info" | "warning" | "danger" | "success";
    readonly urgent?: boolean;
}

export function Notice({
    children,
    title,
    tone = "info",
    urgent = false,
}: NoticeProps) {
    return (
        <section
            className={`ui-notice ui-notice--${tone}`}
            role={urgent ? "alert" : "status"}
        >
            {title === undefined ? null : <h2>{title}</h2>}
            <div>{children}</div>
        </section>
    );
}
