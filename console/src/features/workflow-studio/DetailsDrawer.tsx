import { X } from "lucide-react";
import {
    useEffect,
    useId,
    useRef,
    useState,
    type KeyboardEvent,
    type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { Button } from "../../components/ui";

const NARROW_QUERY = "(max-width: 48rem)";
const FOCUSABLE =
    'button:not([disabled]), [href], input:not([disabled]), [role="combobox"]:not([aria-disabled="true"]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface DetailsDrawerProps {
    readonly busy?: boolean;
    readonly children: ReactNode;
    readonly closeLabel: string;
    readonly focusRequest: number;
    readonly footer?: ReactNode;
    readonly heading: string;
    readonly identity: string;
    readonly initialFocusSelector?: string;
    readonly onClose: () => void;
    readonly open: boolean;
}

export function DetailsDrawer({
    busy = false,
    children,
    closeLabel,
    focusRequest,
    footer,
    heading,
    identity,
    initialFocusSelector = 'input:not([disabled]), [role="combobox"]:not([aria-disabled="true"]), textarea:not([disabled])',
    onClose,
    open,
}: DetailsDrawerProps) {
    const isNarrow = useNarrowViewport();
    const titleId = useId();
    const panelRef = useRef<HTMLDivElement>(null);
    const handledFocusRequest = useRef(0);

    useEffect(() => {
        const hasExplicitRequest = focusRequest > handledFocusRequest.current;
        if (!open || (!isNarrow && !hasExplicitRequest)) {
            return;
        }
        handledFocusRequest.current = focusRequest;
        const frame = requestAnimationFrame(() => {
            const panel = panelRef.current;
            (
                panel?.querySelector<HTMLElement>('[aria-invalid="true"]') ??
                panel?.querySelector<HTMLElement>(initialFocusSelector) ??
                panel?.querySelector<HTMLElement>("[data-details-heading]") ??
                panel
            )?.focus();
        });
        return () => cancelAnimationFrame(frame);
    }, [focusRequest, identity, initialFocusSelector, isNarrow, open]);

    useEffect(() => {
        if (!open || !isNarrow) {
            return;
        }
        const root = document.getElementById("root");
        const hadInert = root?.hasAttribute("inert") ?? false;
        const previousOverflow = document.body.style.overflow;
        root?.setAttribute("inert", "");
        document.body.style.overflow = "hidden";
        return () => {
            if (!hadInert) {
                root?.removeAttribute("inert");
            }
            document.body.style.overflow = previousOverflow;
        };
    }, [isNarrow, open]);

    if (!open) {
        return null;
    }

    const content = (
        <div
            aria-busy={busy || undefined}
            aria-labelledby={titleId}
            aria-modal={isNarrow || undefined}
            className="studio-member-details"
            data-details-surface
            onKeyDown={(event) =>
                handleDrawerKeyDown(event, panelRef.current, isNarrow, onClose)
            }
            ref={panelRef}
            role={isNarrow ? "dialog" : "complementary"}
            tabIndex={-1}
        >
            <header className="studio-member-details__header">
                <h2 data-details-heading id={titleId} tabIndex={-1}>
                    {heading}
                </h2>
                <Button
                    aria-label={closeLabel}
                    className="studio-member-details__close"
                    icon
                    onClick={onClose}
                    tone="quiet"
                >
                    <X aria-hidden="true" size={18} />
                </Button>
            </header>
            <div className="studio-member-details__body">{children}</div>
            {footer === undefined ? null : (
                <footer className="studio-member-details__footer">
                    {footer}
                </footer>
            )}
        </div>
    );

    return isNarrow
        ? createPortal(
              <div className="studio-member-details__backdrop">{content}</div>,
              document.body,
          )
        : content;
}

function useNarrowViewport(): boolean {
    const query = (): boolean =>
        typeof window.matchMedia === "function"
            ? window.matchMedia(NARROW_QUERY).matches
            : window.innerWidth <= 48 * 16;
    const [isNarrow, setIsNarrow] = useState(query);

    useEffect(() => {
        if (typeof window.matchMedia !== "function") {
            return;
        }
        const media = window.matchMedia(NARROW_QUERY);
        const update = () => setIsNarrow(media.matches);
        media.addEventListener("change", update);
        return () => media.removeEventListener("change", update);
    }, []);

    return isNarrow;
}

function handleDrawerKeyDown(
    event: KeyboardEvent<HTMLElement>,
    panel: HTMLElement | null,
    trapFocus: boolean,
    onClose: () => void,
): void {
    if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
    }
    if (!trapFocus || event.key !== "Tab") {
        return;
    }
    const focusable = [
        ...(panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []),
    ];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined || last === undefined) {
        event.preventDefault();
    } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}
