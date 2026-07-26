import { Bot, Sprout } from "lucide-react";
import { useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { operatorApi } from "../../app/api";
import { OperatorPanel } from "../../features/operator/OperatorPanel";

export function AppShell() {
    const [operatorOpen, setOperatorOpen] = useState(false);
    const operatorToggleRef = useRef<HTMLButtonElement>(null);

    function closeOperator(): void {
        setOperatorOpen(false);
        operatorToggleRef.current?.focus();
    }

    return (
        <>
            <a className="shell__skip" href="#banksia-main">
                Skip to main content
            </a>
            <header className="shell__header">
                <div className="page-frame shell__header-inner">
                    <NavLink className="shell__brand" to="/workflows">
                        <span aria-hidden="true" className="shell__brand-mark">
                            <Sprout size={21} strokeWidth={2.2} />
                        </span>
                        <span>Banksia</span>
                    </NavLink>
                    <nav aria-label="Primary" className="shell__nav">
                        <NavLink
                            className={({ isActive }) =>
                                isActive
                                    ? "shell__nav-link is-active"
                                    : "shell__nav-link"
                            }
                            to="/workflows"
                        >
                            Workflows
                        </NavLink>
                        <NavLink
                            className={({ isActive }) =>
                                isActive
                                    ? "shell__nav-link is-active"
                                    : "shell__nav-link"
                            }
                            to="/runs"
                        >
                            Runs
                        </NavLink>
                        <button
                            aria-controls="banksia-operator"
                            aria-expanded={operatorOpen}
                            className="ui-button ui-button--quiet shell__operator-toggle"
                            onClick={() => setOperatorOpen((open) => !open)}
                            ref={operatorToggleRef}
                            type="button"
                        >
                            <Bot aria-hidden="true" size={17} />
                            Operator
                        </button>
                    </nav>
                </div>
            </header>
            <main
                aria-label="Banksia Console"
                className="shell__main"
                id="banksia-main"
                tabIndex={-1}
            >
                <Outlet />
            </main>
            <OperatorPanel
                api={operatorApi}
                isOpen={operatorOpen}
                onClose={closeOperator}
            />
        </>
    );
}
