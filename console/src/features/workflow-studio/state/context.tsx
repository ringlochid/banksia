import {
    createContext,
    type ReactNode,
    useContext,
    useEffect,
    useMemo,
    useSyncExternalStore,
} from "react";

import type { WorkflowApi } from "../../../api/client";
import type { StudioContextValue } from "./contracts";
import { WorkflowStudioController } from "./controller";
import { selectHasPendingWork } from "./selectors";

const StudioContext = createContext<StudioContextValue | null>(null);

export interface StudioProviderProps {
    readonly api: WorkflowApi;
    readonly children: ReactNode;
    readonly workflowId: string;
}

export function StudioProvider({
    api,
    children,
    workflowId,
}: StudioProviderProps) {
    const controller = useMemo(
        () => new WorkflowStudioController(workflowId, api),
        [api, workflowId],
    );
    const snapshot = useSyncExternalStore(
        controller.subscribe,
        controller.getSnapshot,
        controller.getSnapshot,
    );

    useEffect(() => {
        return controller.activate();
    }, [controller]);

    useEffect(() => {
        if (!selectHasPendingWork(snapshot)) {
            return;
        }
        const warn = (event: BeforeUnloadEvent) => {
            event.preventDefault();
        };
        window.addEventListener("beforeunload", warn);
        return () => {
            window.removeEventListener("beforeunload", warn);
        };
    }, [snapshot]);

    return (
        <StudioContext.Provider value={{ snapshot, actions: controller }}>
            {children}
        </StudioContext.Provider>
    );
}

// This hook intentionally shares the provider module so its context stays private.
// eslint-disable-next-line react-refresh/only-export-components
export function useStudio(): StudioContextValue {
    const value = useContext(StudioContext);
    if (value === null) {
        throw new Error("useStudio must be used within StudioProvider");
    }
    return value;
}
