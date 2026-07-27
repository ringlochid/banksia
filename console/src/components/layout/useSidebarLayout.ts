import { useCallback, useEffect, useState } from "react";

/**
 * Collapse state and width for the main sidebar.
 *
 * Translated from n8n's `app/composables/useSidebarLayout.ts` at pinned commit
 * 43c6f329fb1fb528259a78f80b163e4ed1405c02, including its collapsed width and
 * resize bounds. Copyright (c) n8n GmbH and contributors. Sustainable Use
 * License; see console/LICENSE and console/NOTICE.
 */
export const SIDEBAR_COLLAPSED_WIDTH = 42;
export const SIDEBAR_MIN_WIDTH = 200;
export const SIDEBAR_MAX_WIDTH = 500;
const SIDEBAR_GRID = 8;

const WIDTH_KEY = "banksia.sidebar.width";
const COLLAPSED_KEY = "banksia.sidebar.collapsed";

export interface SidebarLayout {
    readonly isCollapsed: boolean;
    readonly isResizing: boolean;
    readonly width: number;
    readonly toggleCollapse: () => void;
    readonly startResize: () => void;
}

export function useSidebarLayout(): SidebarLayout {
    const [isCollapsed, setCollapsed] = useState(
        () => readStored(COLLAPSED_KEY) === "1",
    );
    const [width, setWidth] = useState(() => {
        const stored = Number(readStored(WIDTH_KEY));
        return Number.isFinite(stored) && stored >= SIDEBAR_MIN_WIDTH
            ? Math.min(stored, SIDEBAR_MAX_WIDTH)
            : SIDEBAR_MIN_WIDTH;
    });
    const [isResizing, setResizing] = useState(false);

    const toggleCollapse = useCallback(() => {
        setCollapsed((collapsed) => {
            writeStored(COLLAPSED_KEY, collapsed ? "0" : "1");
            return !collapsed;
        });
    }, []);

    const startResize = useCallback(() => {
        setResizing(true);
    }, []);

    // Dragging is tracked on the document so the pointer can leave the handle.
    useEffect(() => {
        if (!isResizing) {
            return;
        }
        function handleMove(event: PointerEvent): void {
            const snapped =
                Math.round(event.clientX / SIDEBAR_GRID) * SIDEBAR_GRID;
            setWidth(
                Math.min(
                    SIDEBAR_MAX_WIDTH,
                    Math.max(SIDEBAR_MIN_WIDTH, snapped),
                ),
            );
        }
        function handleUp(): void {
            setResizing(false);
        }
        document.addEventListener("pointermove", handleMove);
        document.addEventListener("pointerup", handleUp);
        return () => {
            document.removeEventListener("pointermove", handleMove);
            document.removeEventListener("pointerup", handleUp);
        };
    }, [isResizing]);

    useEffect(() => {
        if (!isResizing) {
            writeStored(WIDTH_KEY, String(width));
        }
    }, [isResizing, width]);

    // n8n binds `[` to the collapse toggle; keep the same shortcut.
    useEffect(() => {
        function handleKey(event: KeyboardEvent): void {
            if (event.key !== "[" || event.metaKey || event.ctrlKey) {
                return;
            }
            const target = event.target;
            if (
                target instanceof HTMLElement &&
                (target.isContentEditable ||
                    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
            ) {
                return;
            }
            event.preventDefault();
            toggleCollapse();
        }
        document.addEventListener("keydown", handleKey);
        return () => document.removeEventListener("keydown", handleKey);
    }, [toggleCollapse]);

    return {
        isCollapsed,
        isResizing,
        startResize,
        toggleCollapse,
        width: isCollapsed ? SIDEBAR_COLLAPSED_WIDTH : width,
    };
}

function readStored(key: string): string | null {
    try {
        return window.localStorage.getItem(key);
    } catch {
        return null;
    }
}

function writeStored(key: string, value: string): void {
    try {
        window.localStorage.setItem(key, value);
    } catch {
        // Storage can be unavailable; the layout still works for this session.
    }
}
