import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Sidebar } from "../../src/components/layout/Sidebar";
import type { SidebarLayout } from "../../src/components/layout/useSidebarLayout";
import { TooltipProvider } from "../../src/components/ui";

describe("Sidebar", () => {
    it("keeps create explicit and does not imply a command search", async () => {
        const onCreateWorkflow = vi.fn();
        const user = userEvent.setup();

        render(
            <MemoryRouter>
                <TooltipProvider>
                    <Sidebar
                        layout={layout()}
                        onCreateWorkflow={onCreateWorkflow}
                        onToggleOperator={vi.fn()}
                        operatorOpen={false}
                    />
                </TooltipProvider>
            </MemoryRouter>,
        );

        expect(
            screen.queryByRole("button", { name: "Search" }),
        ).not.toBeInTheDocument();
        await user.click(
            screen.getByRole("button", { name: "Create workflow" }),
        );
        expect(onCreateWorkflow).toHaveBeenCalledOnce();
    });
});

function layout(): SidebarLayout {
    return {
        isCollapsed: true,
        isResizing: false,
        startResize: vi.fn(),
        toggleCollapse: vi.fn(),
        width: 42,
    };
}
