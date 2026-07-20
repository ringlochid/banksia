import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { AppShell } from "../../src/components/layout";

afterEach(() => {
    cleanup();
});

describe("app shell", () => {
    it("keeps task-scoped runtime breadcrumbs under Tasks", () => {
        renderShell("/tasks/task-123/human-requests");

        const breadcrumb = within(screen.getByRole("navigation", { name: "Breadcrumb" }));
        expect(breadcrumb.getByText("Tasks")).toBeVisible();
        expect(breadcrumb.getByText("task-123")).not.toHaveAttribute("aria-current");
        expect(breadcrumb.getByText("Human Requests")).toHaveAttribute("aria-current", "page");
        expect(breadcrumb.getAllByText("\u203a")).toHaveLength(2);
        expect(breadcrumb.queryByText("/")).not.toBeInTheDocument();
        expect(screen.getAllByText("Runtime").length).toBeGreaterThan(0);
        expect(screen.queryByText("Live")).not.toBeInTheDocument();
        expect(screen.queryByLabelText("Shell state")).not.toBeInTheDocument();
    });

    it("keeps authoring breadcrumbs separate from selected task routes", () => {
        renderShell("/definitions/editor");

        const breadcrumb = within(screen.getByRole("navigation", { name: "Breadcrumb" }));
        expect(breadcrumb.getByText("Definitions")).toBeVisible();
        expect(breadcrumb.getByText("Definition Editor")).toHaveAttribute("aria-current", "page");
        expect(screen.getAllByText("Authoring").length).toBeGreaterThan(0);
        expect(screen.getByText("Draft editing")).toBeVisible();
    });

    it("shows selected task sibling navigation only when a task is selected", () => {
        renderShell("/tasks/task-123/command-runs");

        const primaryLabels = screen.getAllByRole("link").map((link) => link.textContent.trim());

        expect(primaryLabels).toContain("Tasks");
        expect(primaryLabels).toContain("Task Detail");
        expect(primaryLabels).toContain("Human Requests");
        expect(primaryLabels).toContain("Command Runs");
        expect(primaryLabels).toContain("Definitions");
        expect(primaryLabels).toContain("Definition Editor");
        expect(primaryLabels).toContain("Task Start");
    });

    it("omits selected task navigation on the task list route", () => {
        renderShell("/tasks");

        const primaryLabels = screen.getAllByRole("link").map((link) => link.textContent.trim());

        expect(primaryLabels).toContain("Tasks");
        expect(primaryLabels).not.toContain("Task Detail");
        expect(primaryLabels).not.toContain("Human Requests");
        expect(primaryLabels).not.toContain("Command Runs");
    });

    it("does not expose the internal fixture gallery as release shell chrome", () => {
        renderShell("/tasks/task-123/command-runs");

        expect(screen.queryByRole("link", { name: "Fixture gallery" })).not.toBeInTheDocument();
    });

    it("offers a keyboard bypass link to the main content", () => {
        renderShell("/tasks");

        expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute(
            "href",
            "#autoclaw-main-content",
        );
        expect(screen.getByRole("main", { name: "AutoClaw Console" })).toHaveAttribute(
            "id",
            "autoclaw-main-content",
        );
    });
});

function renderShell(initialPath: string) {
    render(
        <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
                <Route element={<AppShell />} path="/*">
                    <Route element={<p>Page content</p>} path="*" />
                </Route>
            </Routes>
        </MemoryRouter>,
    );
}
