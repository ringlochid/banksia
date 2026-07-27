import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { NormalizedMember } from "../../src/api/types";
import { MemberDetailsSurface } from "../../src/features/workflow-studio/MemberDetailsSurface";
import { TeamOutline } from "../../src/features/workflow-studio/canvas/TeamOutline";
import { workflowFixture } from "../fixtures/workflows";

describe("team authoring surfaces", () => {
    it("offers roving hierarchy navigation, collapse, selection, and actions", async () => {
        const user = userEvent.setup();
        const addChild = vi.fn();
        const edit = vi.fn();
        const remove = vi.fn();

        render(
            <OutlineHarness
                onAddChild={addChild}
                onEdit={edit}
                onRemove={remove}
            />,
        );

        const lead = screen.getByRole("treeitem", {
            name: "Research lead",
        });
        lead.focus();
        await user.keyboard("{ArrowDown}");

        const manager = screen.getByRole("treeitem", {
            name: "Evidence manager",
        });
        await waitFor(() => expect(manager).toHaveFocus());
        await user.keyboard("{Enter}");
        expect(manager).toHaveAttribute("aria-selected", "true");

        await user.keyboard("{ArrowLeft}");
        expect(manager).toHaveAttribute("aria-expanded", "false");
        expect(
            screen.queryByRole("treeitem", { name: /Source specialist/ }),
        ).not.toBeInTheDocument();

        await user.keyboard("{ArrowRight}");
        await waitFor(() =>
            expect(manager).toHaveAttribute("aria-expanded", "true"),
        );
        await user.keyboard("{ArrowRight}");
        await waitFor(() =>
            expect(
                screen.getByRole("treeitem", { name: /Source specialist/ }),
            ).toHaveFocus(),
        );

        await user.keyboard("p");
        await waitFor(() =>
            expect(
                screen.getByRole("treeitem", { name: /Publishing reviewer/ }),
            ).toHaveFocus(),
        );

        await user.click(screen.getByRole("button", { name: "Add member" }));
        await user.click(screen.getByRole("button", { name: "Edit" }));
        await user.click(screen.getByRole("button", { name: "Remove" }));

        expect(addChild).toHaveBeenCalledWith("manager");
        expect(edit).toHaveBeenCalledWith("manager");
        expect(remove).toHaveBeenCalledWith("manager");
        expect(
            screen
                .getAllByRole("treeitem")
                .filter((item) => item.tabIndex === 0),
        ).toHaveLength(1);
    });

    it("uses a modal, inert, focus-contained sheet on narrow screens", async () => {
        vi.stubGlobal("matchMedia", narrowMatchMedia);
        const user = userEvent.setup();
        const workflow = workflowFixture();
        const root = document.createElement("div");
        root.id = "root";
        document.body.append(root);

        render(<DetailsHarness />, { container: root });

        const dialog = screen.getByRole("dialog", { name: "Research lead" });
        expect(dialog).toHaveAttribute("aria-modal", "true");
        expect(root).toHaveAttribute("inert");
        expect(document.body.style.overflow).toBe("hidden");
        const nameField = dialog.querySelector<HTMLInputElement>(
            '[data-field-path="$.members.member-1.title"]',
        );
        expect(nameField).not.toBeNull();
        await waitFor(() => {
            expect(nameField).toHaveFocus();
        });

        await user.keyboard("{Escape}");

        expect(
            screen.queryByRole("dialog", { name: "Research lead" }),
        ).toBeNull();
        expect(root).not.toHaveAttribute("inert");
        expect(document.body.style.overflow).toBe("");

        function DetailsHarness() {
            const [open, setOpen] = useState(true);
            return (
                <MemberDetailsSurface
                    disabled={false}
                    focusRequest={1}
                    issues={[]}
                    member={workflow.lead}
                    onClose={() => setOpen(false)}
                    onEditMember={() => undefined}
                    onRetryOptions={() => undefined}
                    open={open}
                    options={{ kind: "loading" }}
                    workflow={workflow}
                />
            );
        }
    });
});

interface OutlineHarnessProps {
    readonly onAddChild: (memberId: string) => void;
    readonly onEdit: (memberId: string) => void;
    readonly onRemove: (memberId: string) => void;
}

function OutlineHarness({ onAddChild, onEdit, onRemove }: OutlineHarnessProps) {
    const [selectedMemberId, setSelectedMemberId] = useState("lead");
    const [collapsedMemberIds, setCollapsedMemberIds] = useState<
        ReadonlySet<string>
    >(() => new Set());
    return (
        <TeamOutline
            collapsedMemberIds={collapsedMemberIds}
            disabled={false}
            lead={outlineTeam()}
            onAddChild={onAddChild}
            onEdit={onEdit}
            onRemove={onRemove}
            onSelect={setSelectedMemberId}
            onToggleCollapse={(memberId) => {
                setCollapsedMemberIds((current) => {
                    const next = new Set(current);
                    if (next.has(memberId)) {
                        next.delete(memberId);
                    } else {
                        next.add(memberId);
                    }
                    return next;
                });
            }}
            requestedFocus={null}
            selectedMemberId={selectedMemberId}
        />
    );
}

function outlineTeam(): NormalizedMember {
    return {
        id: "lead",
        title: "Research lead",
        children: [
            {
                id: "manager",
                title: "Evidence manager",
                children: [
                    {
                        id: "specialist",
                        title: "Source specialist",
                    },
                ],
            },
            {
                id: "reviewer",
                title: "Publishing reviewer",
            },
        ],
    };
}

function narrowMatchMedia(query: string): MediaQueryList {
    return {
        addEventListener: () => undefined,
        addListener: () => undefined,
        dispatchEvent: () => true,
        matches: query === "(max-width: 48rem)",
        media: query,
        onchange: null,
        removeEventListener: () => undefined,
        removeListener: () => undefined,
    };
}
