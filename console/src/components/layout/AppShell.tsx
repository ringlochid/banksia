import { Sprout } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

export function AppShell() {
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
        </>
    );
}
