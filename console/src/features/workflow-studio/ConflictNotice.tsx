import { useEffect, useRef, useState } from "react";

import { Button, Notice } from "../../components/ui";
import type { StudioContextValue } from "./state/contracts";

export function ConflictNotice({ snapshot, actions }: StudioContextValue) {
    const headingRef = useRef<HTMLHeadingElement>(null);
    const [copyMessage, setCopyMessage] = useState<string | null>(null);

    useEffect(() => {
        if (snapshot.conflict !== null) {
            headingRef.current?.focus();
        }
    }, [snapshot.conflict]);

    if (snapshot.conflict === null) {
        return null;
    }
    return (
        <Notice tone="danger" urgent>
            <h2 ref={headingRef} tabIndex={-1}>
                This draft changed elsewhere
            </h2>
            <p>
                {snapshot.conflict.message} Your unsaved values are still in
                this tab. Reload the latest version or copy only your changed
                fields first.
            </p>
            <div className="studio-notice-actions">
                <Button
                    disabled={snapshot.save.kind === "checking_current"}
                    onClick={() => void actions.reloadCurrent()}
                    tone="primary"
                >
                    {snapshot.save.kind === "checking_current"
                        ? "Reloading…"
                        : "Reload current"}
                </Button>
                <Button
                    onClick={() => {
                        void actions.copyUnsavedValues().then((copied) => {
                            setCopyMessage(
                                copied
                                    ? "Your changed values are copied. Paste them somewhere safe before reloading."
                                    : "Copy was unavailable in this browser.",
                            );
                        });
                    }}
                >
                    Copy my unsaved values
                </Button>
            </div>
            {copyMessage === null ? null : <p role="status">{copyMessage}</p>}
        </Notice>
    );
}
