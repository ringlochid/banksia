import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
    Button,
    CodeBlock,
    Disclosure,
    FormField,
    IconButton,
    ListRow,
    PropertyGrid,
    SegmentedControl,
    StatePanel,
    StatusChip,
    Surface,
    Tabs,
} from "../../src/components/ui";
import type { TabOption } from "../../src/components/ui";

type DetailTabValue = "overview" | "checkpoint" | "trace";

const detailTabs: readonly TabOption<DetailTabValue>[] = [
    { label: "Overview", panelId: "overview-panel", value: "overview" },
    { label: "Checkpoint", panelId: "checkpoint-panel", value: "checkpoint" },
    { label: "Trace", panelId: "trace-panel", value: "trace" },
];

function StatefulTabs({
    initialValue = "overview",
    tabs = detailTabs,
}: {
    readonly initialValue?: DetailTabValue;
    readonly tabs?: readonly TabOption<DetailTabValue>[];
}) {
    const [value, setValue] = useState<DetailTabValue>(initialValue);

    return <Tabs label="Detail views" onChange={setValue} tabs={tabs} value={value} />;
}

describe("ui primitives", () => {
    it("keeps button type safe by default", () => {
        render(<Button>Pause</Button>);

        expect(screen.getByRole("button", { name: "Pause" })).toHaveAttribute("type", "button");
    });

    it("renders status chip content", () => {
        render(
            <StatusChip tone="active" withDot>
                running
            </StatusChip>,
        );

        expect(screen.getByText("running")).toBeVisible();
    });

    it("renders surface heading and body", () => {
        render(
            <Surface label="Contract" title="Backing surfaces">
                <p>GET /runtime/tasks</p>
            </Surface>,
        );

        expect(screen.getByRole("heading", { name: "Backing surfaces" })).toBeVisible();
        expect(screen.getByText("GET /runtime/tasks")).toBeVisible();
    });

    it("labels icon-only buttons", () => {
        render(<IconButton icon={<RefreshCw />} label="Refresh tasks" />);

        const button = screen.getByRole("button", { name: "Refresh tasks" });
        expect(button).toHaveAttribute("type", "button");
        expect(button).toHaveAttribute("title", "Refresh tasks");
    });

    it("keeps segmented options keyboard-visible and stateful", async () => {
        const user = userEvent.setup();
        const selected: string[] = [];

        render(
            <SegmentedControl
                label="Definition kind"
                onChange={(value) => {
                    selected.push(value);
                }}
                options={[
                    { label: "Roles", value: "roles" },
                    { label: "Policies", value: "policies" },
                ]}
                value="roles"
            />,
        );

        expect(screen.getByRole("button", { name: "Roles" })).toHaveAttribute(
            "aria-pressed",
            "true",
        );
        await user.click(screen.getByRole("button", { name: "Policies" }));
        expect(selected).toEqual(["policies"]);
    });

    it("renders tabs with selected tab semantics", async () => {
        const user = userEvent.setup();
        const selected: string[] = [];

        render(
            <Tabs
                label="Detail views"
                onChange={(value) => {
                    selected.push(value);
                }}
                tabs={[
                    { label: "Overview", panelId: "overview-panel", value: "overview" },
                    { label: "Trace", panelId: "trace-panel", value: "trace" },
                ]}
                value="overview"
            />,
        );

        const overviewTab = screen.getByRole("tab", { name: "Overview" });
        expect(overviewTab).toHaveAttribute("aria-selected", "true");
        expect(overviewTab).toHaveAttribute("aria-controls", "overview-panel");
        expect(overviewTab).toHaveAttribute("id", "overview-panel-tab");
        await user.click(screen.getByRole("tab", { name: "Trace" }));
        expect(selected).toEqual(["trace"]);
    });

    it("moves tab focus and selection with arrow, Home, and End keys", async () => {
        const user = userEvent.setup();

        const view = render(<StatefulTabs />);

        const tablist = within(view.container);
        const overview = tablist.getByRole("tab", { name: "Overview" });
        const checkpoint = tablist.getByRole("tab", { name: "Checkpoint" });
        const trace = tablist.getByRole("tab", { name: "Trace" });

        overview.focus();
        await user.keyboard("{ArrowRight}");
        expect(checkpoint).toHaveFocus();
        expect(checkpoint).toHaveAttribute("aria-selected", "true");
        expect(checkpoint).toHaveAttribute("tabindex", "0");
        expect(overview).toHaveAttribute("tabindex", "-1");

        await user.keyboard("{ArrowDown}");
        expect(trace).toHaveFocus();
        expect(trace).toHaveAttribute("aria-selected", "true");

        await user.keyboard("{ArrowLeft}");
        expect(checkpoint).toHaveFocus();
        expect(checkpoint).toHaveAttribute("aria-selected", "true");

        await user.keyboard("{Home}");
        expect(overview).toHaveFocus();
        expect(overview).toHaveAttribute("aria-selected", "true");

        await user.keyboard("{End}");
        expect(trace).toHaveFocus();
        expect(trace).toHaveAttribute("aria-selected", "true");
    });

    it("skips disabled tabs during keyboard navigation", async () => {
        const user = userEvent.setup();

        const view = render(
            <StatefulTabs
                tabs={[
                    { label: "Overview", panelId: "overview-panel", value: "overview" },
                    {
                        disabled: true,
                        label: "Checkpoint",
                        panelId: "checkpoint-panel",
                        value: "checkpoint",
                    },
                    { label: "Trace", panelId: "trace-panel", value: "trace" },
                ]}
            />,
        );

        const tablist = within(view.container);
        const overview = tablist.getByRole("tab", { name: "Overview" });
        const checkpoint = tablist.getByRole("tab", { name: "Checkpoint" });
        const trace = tablist.getByRole("tab", { name: "Trace" });

        overview.focus();
        await user.keyboard("{ArrowRight}");
        expect(trace).toHaveFocus();
        expect(trace).toHaveAttribute("aria-selected", "true");
        expect(checkpoint).toBeDisabled();
        expect(checkpoint).toHaveAttribute("aria-selected", "false");
        expect(checkpoint).toHaveAttribute("tabindex", "-1");

        await user.keyboard("{ArrowLeft}");
        expect(overview).toHaveFocus();
        expect(overview).toHaveAttribute("aria-selected", "true");
    });

    it("renders disclosure content behind a native details shell", async () => {
        const user = userEvent.setup();

        render(
            <Disclosure title="Command output">
                <p>latest summary</p>
            </Disclosure>,
        );

        const details = screen.getByText("Command output").closest("details");
        expect(details).not.toHaveAttribute("open");
        await user.click(screen.getByText("Command output"));
        expect(details).toHaveAttribute("open");
    });

    it("renders action state panels with alert semantics when needed", () => {
        render(
            <StatePanel
                summary="Reread current task truth before retrying."
                title="Stale action"
                tone="stale"
            />,
        );

        expect(screen.getByRole("alert")).toHaveTextContent("Stale action");
        expect(screen.getByText("Reread current task truth before retrying.")).toBeVisible();
    });

    it("connects form labels, hints, and errors to controls", () => {
        render(
            <FormField
                error="Workflow is required."
                hint="Use current stored workflow truth."
                id="workflow-key"
                label="Workflow key"
            >
                <input type="text" />
            </FormField>,
        );

        const input = screen.getByLabelText("Workflow key");
        expect(input).toHaveAttribute("id", "workflow-key");
        expect(input).toHaveAttribute("aria-invalid", "true");
        expect(input).toHaveAccessibleDescription(
            "Use current stored workflow truth. Workflow is required.",
        );
    });

    it("renders property grids, list rows, and code blocks", () => {
        render(
            <div>
                <PropertyGrid
                    items={[
                        { label: "Kind", value: "workflow" },
                        { label: "Revision", value: "current stored" },
                    ]}
                />
                <ListRow
                    description="Stored registry browser"
                    status={<StatusChip>quiet</StatusChip>}
                    title="Definitions"
                />
                <CodeBlock title="Route">GET /definitions/workflows</CodeBlock>
            </div>,
        );

        expect(screen.getByText("Kind")).toBeVisible();
        expect(screen.getByText("Definitions")).toBeVisible();
        expect(screen.getByLabelText("Route")).toHaveTextContent("GET /definitions/workflows");
    });

    it("renders single-item property grids without empty column dividers", () => {
        render(<PropertyGrid items={[{ label: "Budget", value: "No controller budget limit" }]} />);

        const budgetCell = screen.getByText("Budget").closest("div");
        expect(budgetCell).not.toBeNull();
        expect(budgetCell).toHaveClass("sm:col-span-2");
        expect(budgetCell).toHaveClass("lg:col-span-3");
        expect(budgetCell).not.toHaveClass("sm:border-r");
    });
});
