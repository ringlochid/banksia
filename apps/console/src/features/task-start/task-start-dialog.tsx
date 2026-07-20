import { useEffect, useRef, type ReactNode } from "react";

import { X } from "lucide-react";

export function TaskStartDialog({
    children,
    footer,
    label,
    onClose,
    title,
}: {
    readonly children: ReactNode;
    readonly footer: ReactNode;
    readonly label: string;
    readonly onClose: () => void;
    readonly title: string;
}) {
    const dialogRef = useRef<HTMLElement | null>(null);
    const onCloseRef = useRef(onClose);
    const previousFocusRef = useRef<HTMLElement | null>(null);

    useEffect(() => {
        onCloseRef.current = onClose;
    }, [onClose]);

    useEffect(() => {
        const activeElement = document.activeElement;
        previousFocusRef.current =
            activeElement instanceof HTMLElement && activeElement !== document.body
                ? activeElement
                : null;
        const dialog = dialogRef.current;
        const initialFocusTarget = dialog?.querySelector<HTMLElement>(
            "[data-dialog-initial-focus]",
        );
        const focusableElements = getDialogFocusableElements(dialog);
        const focusTarget =
            initialFocusTarget ?? (focusableElements.length > 0 ? focusableElements[0] : dialog);
        focusTarget?.focus({ preventScroll: true });

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                onCloseRef.current();
                return;
            }

            if (event.key !== "Tab") {
                return;
            }

            const currentDialog = dialogRef.current;
            const currentFocusableElements = getDialogFocusableElements(currentDialog);
            if (currentDialog === null || currentFocusableElements.length === 0) {
                event.preventDefault();
                currentDialog?.focus({ preventScroll: true });
                return;
            }

            const firstElement = currentFocusableElements[0];
            const lastElement = currentFocusableElements[currentFocusableElements.length - 1];
            const activeDialogElement = document.activeElement;

            if (
                event.shiftKey &&
                (activeDialogElement === firstElement ||
                    !(activeDialogElement instanceof HTMLElement) ||
                    !currentDialog.contains(activeDialogElement))
            ) {
                event.preventDefault();
                lastElement.focus({ preventScroll: true });
                return;
            }

            if (!event.shiftKey && activeDialogElement === lastElement) {
                event.preventDefault();
                firstElement.focus({ preventScroll: true });
                return;
            }

            if (
                activeDialogElement instanceof HTMLElement &&
                !currentDialog.contains(activeDialogElement)
            ) {
                event.preventDefault();
                firstElement.focus({ preventScroll: true });
            }
        };

        document.body.classList.add("overflow-hidden");
        document.addEventListener("keydown", handleKeyDown, true);
        return () => {
            document.body.classList.remove("overflow-hidden");
            document.removeEventListener("keydown", handleKeyDown, true);
            const previousFocus = previousFocusRef.current;
            if (previousFocus?.isConnected === true) {
                previousFocus.focus({ preventScroll: true });
            }
        };
    }, []);

    return (
        <div
            className="fixed inset-0 z-50 grid place-items-center bg-foreground/35 p-4 backdrop-blur-[2px]"
            role="presentation"
        >
            <section
                aria-labelledby="task-start-dialog-title"
                aria-modal="true"
                className="max-h-[calc(100vh-4rem)] w-full max-w-2xl overflow-hidden rounded-shell border border-outline-soft bg-surface shadow-popover"
                ref={dialogRef}
                role="dialog"
                tabIndex={-1}
            >
                <header className="flex items-start justify-between gap-4 border-b border-outline-soft px-5 py-4">
                    <div className="min-w-0">
                        <p className="font-mono text-label font-medium uppercase text-muted">
                            {label}
                        </p>
                        <h2
                            className="mt-1 font-display text-compact font-semibold text-foreground"
                            id="task-start-dialog-title"
                        >
                            {title}
                        </h2>
                    </div>
                    <button
                        aria-label={`Close ${label.toLowerCase()}`}
                        className="inline-flex size-icon-control shrink-0 items-center justify-center rounded-control border border-outline bg-surface-low text-muted transition-colors hover:border-primary/45 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                        onClick={onClose}
                        type="button"
                    >
                        <X aria-hidden="true" className="size-4" />
                    </button>
                </header>
                <div
                    className="max-h-[calc(100vh-14rem)] overflow-y-auto px-5 py-5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary"
                    tabIndex={0}
                >
                    {children}
                </div>
                <footer className="flex flex-col gap-2 border-t border-outline-soft px-5 py-4 sm:flex-row sm:justify-end">
                    {footer}
                </footer>
            </section>
        </div>
    );
}

function getDialogFocusableElements(dialog: HTMLElement | null): HTMLElement[] {
    if (dialog === null) {
        return [];
    }

    return Array.from(
        dialog.querySelectorAll<HTMLElement>(
            [
                "a[href]",
                "button:not([disabled])",
                "input:not([disabled])",
                "select:not([disabled])",
                "textarea:not([disabled])",
                "[tabindex]:not([tabindex='-1'])",
            ].join(", "),
        ),
    ).filter(
        (element) =>
            element.tabIndex >= 0 &&
            !element.hasAttribute("hidden") &&
            element.getAttribute("aria-hidden") !== "true",
    );
}
