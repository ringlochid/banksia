import { useRef, useState } from "react";
import { Outlet, useNavigate } from "react-router";

import { operatorApi } from "../../app/api";
import { OperatorPanel } from "../../features/operator/OperatorPanel";
import { TooltipProvider } from "../ui";
import { Sidebar } from "./Sidebar";
import { useSidebarLayout } from "./useSidebarLayout";

export function AppShell() {
    const navigate = useNavigate();
    const layout = useSidebarLayout();
    const [operatorOpen, setOperatorOpen] = useState(false);
    const operatorToggleRef = useRef<HTMLButtonElement>(null);

    function closeOperator(): void {
        setOperatorOpen(false);
        operatorToggleRef.current?.focus();
    }

    return (
        <TooltipProvider delayDuration={400}>
            <a className="shell__skip" href="#oms-main">
                Skip to main content
            </a>
            <div className="shell">
                <Sidebar
                    layout={layout}
                    onCreateWorkflow={() => {
                        void navigate("/workflows?create=1");
                    }}
                    onToggleOperator={() => setOperatorOpen((open) => !open)}
                    operatorOpen={operatorOpen}
                />
                <main
                    aria-label="Oh My Subagents Console"
                    className="shell__main"
                    id="oms-main"
                    tabIndex={-1}
                >
                    <Outlet />
                </main>
            </div>
            <OperatorPanel
                api={operatorApi}
                isOpen={operatorOpen}
                onClose={closeOperator}
            />
        </TooltipProvider>
    );
}
