import { useEffect, useState } from "react";

/**
 * Shared by every list that filters as you type. Lives outside `features/`
 * because the workflow library and the run list both use it, and the Console
 * has one search interaction rather than one per feature.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
    const [debounced, setDebounced] = useState(value);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            setDebounced(value);
        }, delayMs);
        return () => {
            window.clearTimeout(timer);
        };
    }, [delayMs, value]);

    return debounced;
}
