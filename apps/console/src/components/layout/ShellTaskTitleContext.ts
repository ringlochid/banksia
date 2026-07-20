import { createContext, useContext, useEffect } from "react";

export interface ShellTaskTitleContextValue {
    readonly registerTaskTitle: (taskPath: string, title: string) => () => void;
}

export const ShellTaskTitleContext = createContext<ShellTaskTitleContextValue | null>(null);

export function useShellTaskTitle(taskId: string | null, title: string | null) {
    const context = useContext(ShellTaskTitleContext);

    useEffect(() => {
        if (context === null || taskId === null || title === null || title.trim().length === 0) {
            return undefined;
        }

        return context.registerTaskTitle(`/tasks/${encodeURIComponent(taskId)}`, title);
    }, [context, taskId, title]);
}
