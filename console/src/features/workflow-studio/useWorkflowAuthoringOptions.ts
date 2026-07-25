import { useCallback, useEffect, useState } from "react";

import type { WorkflowApi } from "../../api/client";
import type { WorkflowAuthoringOptionsState } from "./state/contracts";

export interface WorkflowAuthoringOptionsResource {
    readonly retry: () => void;
    readonly state: WorkflowAuthoringOptionsState;
}

export function useWorkflowAuthoringOptions(
    api: WorkflowApi,
    isAuthoring: boolean,
): WorkflowAuthoringOptionsResource {
    const [attempt, setAttempt] = useState(0);
    const [state, setState] = useState<WorkflowAuthoringOptionsState>({
        kind: "loading",
    });

    useEffect(() => {
        if (!isAuthoring) {
            return;
        }
        const controller = new AbortController();
        void api
            .getAuthoringOptions(controller.signal)
            .then(({ body }) => {
                if (!controller.signal.aborted) {
                    setState({ kind: "ready", options: body });
                }
            })
            .catch((error: unknown) => {
                if (!controller.signal.aborted) {
                    setState({
                        kind: "error",
                        message:
                            error instanceof Error && error.message !== ""
                                ? error.message
                                : "Provider and access choices could not be loaded.",
                    });
                }
            });
        return () => controller.abort();
    }, [api, attempt, isAuthoring]);

    const retry = useCallback(() => {
        setState({ kind: "loading" });
        setAttempt((current) => current + 1);
    }, []);

    return { state, retry };
}
