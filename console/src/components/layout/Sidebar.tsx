import {
    Bot,
    ListChecks,
    PanelLeft,
    Plus,
    Sprout,
    Workflow,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { Tooltip } from "../ui";
import type { SidebarLayout } from "./useSidebarLayout";

export interface SidebarProps {
    readonly layout: SidebarLayout;
    readonly onCreateWorkflow: () => void;
    readonly onToggleOperator: () => void;
    readonly operatorOpen: boolean;
}

/**
 * Main navigation.
 *
 * Structure translated from n8n's `MainSidebar.vue` and `MainSidebarHeader.vue`
 * at pinned commit 43c6f329fb1fb528259a78f80b163e4ed1405c02: a header holding
 * the brand plus add/collapse controls, a scrolling nav region, and a
 * bottom group, all inside a resize wrapper.
 * Copyright (c) n8n GmbH and contributors. Sustainable Use License; see
 * console/LICENSE and console/NOTICE.
 *
 * The destinations are Banksia's — Workflows, Runs, Operator — not n8n's
 * projects, templates, or executions.
 */
export function Sidebar({
    layout,
    onCreateWorkflow,
    onToggleOperator,
    operatorOpen,
}: SidebarProps) {
    const { isCollapsed, isResizing, startResize, toggleCollapse, width } =
        layout;

    return (
        <div
            className={[
                "sidebar",
                isCollapsed ? "sidebar--collapsed" : "",
                isResizing ? "sidebar--resizing" : "",
            ]
                .filter(Boolean)
                .join(" ")}
            style={{ width: `${String(width)}px` }}
        >
            <div className="sidebar__header">
                {isCollapsed ? null : (
                    <NavLink
                        aria-label="Banksia home"
                        className="sidebar__logo"
                        to="/workflows"
                    >
                        <span className="sidebar__mark">
                            <Sprout aria-hidden="true" size={16} />
                        </span>
                        <span className="sidebar__wordmark">Banksia</span>
                    </NavLink>
                )}
                <SidebarIconButton
                    label="Create workflow"
                    onClick={onCreateWorkflow}
                    side={isCollapsed ? "right" : "bottom"}
                >
                    <Plus aria-hidden="true" size={18} />
                </SidebarIconButton>
                <SidebarIconButton
                    label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                    onClick={toggleCollapse}
                    side={isCollapsed ? "right" : "bottom"}
                >
                    <PanelLeft aria-hidden="true" size={18} />
                </SidebarIconButton>
            </div>

            <nav aria-label="Primary" className="sidebar__nav">
                <SidebarLink
                    collapsed={isCollapsed}
                    icon={<Workflow aria-hidden="true" size={16} />}
                    label="Workflows"
                    to="/workflows"
                />
                <SidebarLink
                    collapsed={isCollapsed}
                    icon={<ListChecks aria-hidden="true" size={16} />}
                    label="Runs"
                    to="/runs"
                />
            </nav>

            <div className="sidebar__bottom">
                <SidebarButton
                    collapsed={isCollapsed}
                    icon={<Bot aria-hidden="true" size={16} />}
                    isActive={operatorOpen}
                    label="Operator"
                    onClick={onToggleOperator}
                />
            </div>

            {isCollapsed ? null : (
                <div
                    aria-hidden="true"
                    className="sidebar__resize"
                    onPointerDown={(event) => {
                        event.preventDefault();
                        startResize();
                    }}
                />
            )}
        </div>
    );
}

function SidebarIconButton({
    children,
    label,
    onClick,
    side,
}: {
    readonly children: ReactNode;
    readonly label: string;
    readonly onClick: () => void;
    readonly side: "right" | "bottom";
}) {
    return (
        <Tooltip label={label} side={side}>
            <button
                aria-label={label}
                className="sidebar__icon-button"
                onClick={onClick}
                type="button"
            >
                {children}
            </button>
        </Tooltip>
    );
}

function SidebarLink({
    collapsed,
    icon,
    label,
    to,
}: {
    readonly collapsed: boolean;
    readonly icon: ReactNode;
    readonly label: string;
    readonly to: string;
}) {
    const link = (
        <NavLink
            aria-label={collapsed ? label : undefined}
            className={({ isActive }) =>
                isActive ? "sidebar__item is-active" : "sidebar__item"
            }
            to={to}
        >
            <span className="sidebar__item-icon">{icon}</span>
            {collapsed ? null : (
                <span className="sidebar__item-text">{label}</span>
            )}
        </NavLink>
    );
    return collapsed ? (
        <Tooltip label={label} side="right">
            {link}
        </Tooltip>
    ) : (
        link
    );
}

function SidebarButton({
    collapsed,
    icon,
    isActive,
    label,
    onClick,
}: {
    readonly collapsed: boolean;
    readonly icon: ReactNode;
    readonly isActive: boolean;
    readonly label: string;
    readonly onClick: () => void;
}) {
    const button = (
        <button
            aria-label={collapsed ? label : undefined}
            aria-pressed={isActive}
            className={isActive ? "sidebar__item is-active" : "sidebar__item"}
            onClick={onClick}
            type="button"
        >
            <span className="sidebar__item-icon">{icon}</span>
            {collapsed ? null : (
                <span className="sidebar__item-text">{label}</span>
            )}
        </button>
    );
    return collapsed ? (
        <Tooltip label={label} side="right">
            {button}
        </Tooltip>
    ) : (
        button
    );
}
