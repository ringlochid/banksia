import {
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import {
    createMemoryRouter,
    RouterProvider,
    type RouteObject,
} from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import {
    ApiNetworkError,
    ApiResponseError,
    type WorkflowApi,
} from "../../src/api/client";
import type { DraftOperation, WorkflowGetResponse } from "../../src/api/types";
import { WorkflowStudioPage } from "../../src/features/workflow-studio/WorkflowStudioPage";
import {
    catalogFixture,
    draftFixture,
    response,
    TEST_WORKFLOW_ID,
    workflowApiStub,
} from "../fixtures/workflows";

describe("Workflow Studio page", () => {
    it("does not invent Edit when the controller omits that legal action", async () => {
        const catalog: WorkflowGetResponse = {
            ...catalogFixture({ draft: null, published: true }),
            available_actions: ["start_run"],
        };
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalog)),
            getAuthoringOptions: () =>
                Promise.reject(new Error("Not needed in published view.")),
        });

        renderStudio(api);

        expect(
            await screen.findByRole("heading", { name: TEST_WORKFLOW_ID }),
        ).toBeVisible();
        expect(
            screen.queryByRole("button", { name: "Edit Workflow" }),
        ).not.toBeInTheDocument();
    });

    it("shows passive local validation without stealing typing focus", async () => {
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalogFixture())),
            getAuthoringOptions: () =>
                Promise.reject(new Error("Authoring options unavailable.")),
        });
        const user = userEvent.setup();

        renderStudio(api);

        const purpose = await openWorkflowPurpose(user);
        await user.clear(purpose);

        expect(purpose).toHaveFocus();
        const heading = screen.getByText("Check these fields");
        expect(heading).toBeVisible();

        await user.click(screen.getByRole("button", { name: "Publish" }));
        await waitFor(() => {
            expect(heading.closest(".studio-validation")).toHaveFocus();
        });
    });

    it("requires an explicit choice before in-app navigation loses local values", async () => {
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalogFixture())),
            getAuthoringOptions: () =>
                Promise.reject(new Error("Authoring options unavailable.")),
        });
        const user = userEvent.setup();

        renderStudio(api);

        const purpose = await openWorkflowPurpose(user);
        await user.clear(purpose);
        await user.click(screen.getByRole("link", { name: "Workflows" }));

        const warning = screen.getByRole("dialog", {
            name: "Discard unsaved changes?",
        });
        expect(warning).toBeVisible();

        await user.click(
            screen.getByRole("button", { name: "Continue editing" }),
        );
        expect(warning).not.toBeInTheDocument();
        expect(purpose).toBeVisible();

        await user.click(screen.getByRole("link", { name: "Workflows" }));
        await user.click(
            screen.getByRole("button", { name: "Discard changes and leave" }),
        );

        expect(await screen.findByText("Workflow library route")).toBeVisible();
    });

    it("restarts its load lease under root Strict Mode", async () => {
        let reads = 0;
        const api = workflowApiStub({
            getWorkflow: (_workflowId, signal) => {
                reads += 1;
                if (reads > 1) {
                    return Promise.resolve(response(catalogFixture()));
                }
                return new Promise((_, reject) => {
                    signal?.addEventListener("abort", () => {
                        reject(new DOMException("Aborted", "AbortError"));
                    });
                });
            },
            getAuthoringOptions: () =>
                Promise.resolve(
                    response({
                        workflow_fields: ["description", "note"],
                        member_fields: [],
                        provider_kinds: [],
                        codex_efforts: [],
                        claude_efforts: [],
                        managed_sandbox_options: [],
                        human_request_kinds: [],
                        command_run_values: [],
                        default_provider: null,
                    }),
                ),
        });

        renderStudio(api, true);

        const user = userEvent.setup();
        expect(await openWorkflowPurpose(user)).toBeVisible();
        expect(reads).toBe(2);
        expect(screen.queryByText("Opening Workflow…")).not.toBeInTheDocument();
    });

    it("opens a controller-created draft from a published-only Workflow", async () => {
        const openWorkflow = vi.fn(() =>
            Promise.resolve(
                response({ draft: draftFixture(), is_created: false }),
            ),
        );
        const api = workflowApiStub({
            getWorkflow: () =>
                Promise.resolve(
                    response(catalogFixture({ draft: null, published: true })),
                ),
            openWorkflow,
            getAuthoringOptions: () =>
                Promise.reject(new Error("Choices are unavailable.")),
        });
        const user = userEvent.setup();

        renderStudio(api);

        expect(await openWorkflowPurpose(user)).toHaveValue(
            "Research a question with independent evidence review.",
        );
        expect(openWorkflow).toHaveBeenCalledWith(TEST_WORKFLOW_ID);
    });

    it("disables authoring while publish validation is exclusive", async () => {
        let releaseValidation: (() => void) | undefined;
        const gate = new Promise<void>((resolve) => {
            releaseValidation = resolve;
        });
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalogFixture())),
            getAuthoringOptions: () =>
                Promise.reject(new Error("Choices are unavailable.")),
            validateDraft: async () => {
                await gate;
                return response({
                    is_valid: false,
                    issues: [],
                    draft: draftFixture(),
                });
            },
        });
        const user = userEvent.setup();

        renderStudio(api);
        const purpose = await openWorkflowPurpose(user);
        await user.click(screen.getByRole("button", { name: "Publish" }));

        await waitFor(() => expect(purpose).toBeDisabled());
        expect(
            screen.getByRole("button", { name: "Add member" }),
        ).toBeDisabled();
        expect(
            screen.getByRole("button", { name: "Discard draft" }),
        ).toBeDisabled();

        releaseValidation?.();
        await waitFor(() => expect(purpose).toBeEnabled());
    });

    it("retries a failed authoring-options read without reloading the page", async () => {
        let optionReads = 0;
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalogFixture())),
            getAuthoringOptions: () => {
                optionReads += 1;
                return optionReads === 1
                    ? Promise.reject(new Error("Choices are unavailable."))
                    : Promise.resolve(
                          response({
                              workflow_fields: ["description", "note"],
                              member_fields: ["provider", "capabilities"],
                              provider_kinds: ["codex"],
                              codex_efforts: ["high"],
                              claude_efforts: [],
                              managed_sandbox_options: [],
                              human_request_kinds: ["approval"],
                              command_run_values: ["allow"],
                              default_provider: null,
                          }),
                      );
            },
        });
        const user = userEvent.setup();

        renderStudio(api);
        await openMemberDetails(user);
        await user.click(await screen.findByText("Provider and access"));
        await user.click(
            await screen.findByRole("button", {
                name: "Try again",
            }),
        );

        await waitFor(() => {
            expect(screen.getByLabelText("Provider")).toBeEnabled();
        });
        await user.click(screen.getByLabelText("Provider"));
        expect(
            screen.getByRole("option", { name: "Codex" }),
        ).toBeInTheDocument();
        expect(optionReads).toBe(2);
    });

    it("shows a rejected capability once at the field instead of as a page error wall", async () => {
        const message = "The request contains an unsupported or invalid field.";
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalogFixture())),
            getAuthoringOptions: () =>
                Promise.resolve(
                    response({
                        workflow_fields: ["description", "note"],
                        member_fields: ["provider", "capabilities"],
                        provider_kinds: ["codex"],
                        codex_efforts: ["high"],
                        claude_efforts: [],
                        managed_sandbox_options: [],
                        human_request_kinds: ["approval"],
                        command_run_values: [],
                        default_provider: null,
                    }),
                ),
            mutateDraft: () =>
                Promise.reject(
                    new ApiResponseError(422, {
                        code: "invalid_request",
                        field_path: "patch.capabilities.human_request",
                        summary: message,
                    }),
                ),
        });
        const user = userEvent.setup();

        renderStudio(api);
        await openMemberDetails(user);
        await user.click(await screen.findByText("Provider and access"));
        await user.click(
            screen.getByLabelText(
                "Allow this teammate to ask you for approval",
            ),
        );

        const capabilities = await screen.findByRole("group", {
            name: "Allowed actions",
        });
        await waitFor(() => {
            expect(capabilities).toHaveAttribute("aria-invalid", "true");
        });
        expect(capabilities).toHaveAccessibleDescription(message);
        expect(screen.getAllByText(message)).toHaveLength(1);
        expect(screen.queryByText("Check these fields")).toBeNull();
        expect(
            screen.queryByRole("button", { name: "Try saving again" }),
        ).toBeNull();
        expect(screen.getByText("Not saved")).toBeVisible();
    });

    it("keeps one desktop overlay open and returns Details focus to the selected card", async () => {
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalogFixture())),
            getAuthoringOptions: () =>
                Promise.reject(new Error("Choices are unavailable.")),
        });
        const user = userEvent.setup();

        renderStudio(api);
        const outlineSummary = await screen.findByText("Team outline", {
            selector: "summary",
        });
        await user.click(outlineSummary);
        await user.click(
            screen.getByRole("treeitem", {
                name: "Independent reviewer",
            }),
        );
        await user.click(screen.getByRole("button", { name: "Edit" }));
        expect(
            screen.getByRole("complementary", {
                name: "Independent reviewer",
            }),
        ).toBeVisible();

        expect(outlineSummary.closest("details")).not.toHaveAttribute("open");
        await user.click(outlineSummary);

        expect(
            screen.queryByRole("complementary", {
                name: "Independent reviewer",
            }),
        ).not.toBeInTheDocument();
        const selectedOutlineItem = screen.getByRole("treeitem", {
            name: "Independent reviewer",
        });
        await waitFor(() => expect(selectedOutlineItem).toHaveFocus());
        expect(selectedOutlineItem).toHaveAttribute("aria-selected", "true");
        expect(selectedOutlineItem).toHaveAttribute("tabindex", "0");
        expect(
            screen
                .getAllByRole("treeitem")
                .filter((item) => item.tabIndex === 0),
        ).toEqual([selectedOutlineItem]);

        await user.click(screen.getByRole("button", { name: "Edit" }));
        expect(outlineSummary.closest("details")).not.toHaveAttribute("open");
        await user.click(
            screen.getByRole("button", {
                name: "Close member details",
            }),
        );
        const childCard = document.querySelector<HTMLElement>(
            '[data-focus-surface="canvas"][data-member-focus="member-2"]',
        );
        expect(childCard).not.toBeNull();
        await waitFor(() => expect(childCard).toHaveFocus());
    });

    it("collapses a selected descendant under Strict Mode with one pure state transition", async () => {
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalogFixture())),
            getAuthoringOptions: () =>
                Promise.reject(new Error("Choices are unavailable.")),
        });
        const user = userEvent.setup();

        renderStudio(api, true);
        await user.click(
            await screen.findByText("Team outline", { selector: "summary" }),
        );
        await user.click(
            screen.getByRole("treeitem", {
                name: "Independent reviewer",
            }),
        );
        await user.click(screen.getByRole("button", { name: "Edit" }));
        await user.click(
            screen.getByRole("button", {
                name: "Close member details",
            }),
        );
        const collapse = document.querySelector<HTMLButtonElement>(
            '[aria-label="Collapse team under Research lead"]',
        );
        expect(collapse).not.toBeNull();
        fireEvent.click(collapse!);

        expect(
            document.querySelector('[data-member-card="member-2"]'),
        ).not.toBeInTheDocument();
        const leadCard = document.querySelector<HTMLElement>(
            '[data-focus-surface="canvas"][data-member-focus="member-1"]',
        );
        expect(leadCard).not.toBeNull();
        expect(leadCard).toHaveAttribute("aria-pressed", "true");
        await waitFor(() => expect(leadCard).toHaveFocus());
    });

    it("focuses the surviving parent and synchronizes the open outline after removal", async () => {
        const accepted = {
            ...draftFixture('"wd-removed"'),
            workflow: {
                ...draftFixture().workflow,
                lead: {
                    ...draftFixture().workflow.lead,
                    children: [],
                },
            },
        };
        const api = workflowApiStub({
            getWorkflow: () => Promise.resolve(response(catalogFixture())),
            getAuthoringOptions: () =>
                Promise.reject(new Error("Choices are unavailable.")),
            mutateDraft: (_draftId, _etag, operation: DraftOperation) => {
                expect(operation).toEqual({
                    kind: "remove_member",
                    member_id: "member-2",
                });
                return Promise.resolve(
                    response({
                        draft: accepted,
                        undo_receipt: "receipt-remove",
                    }),
                );
            },
        });
        const user = userEvent.setup();

        renderStudio(api);
        await user.click(
            await screen.findByText("Team outline", { selector: "summary" }),
        );
        await user.click(
            screen.getByRole("treeitem", {
                name: "Independent reviewer",
            }),
        );
        await user.click(screen.getByRole("button", { name: "Remove" }));
        await user.click(
            within(
                screen.getByRole("dialog", {
                    name: "Remove Independent reviewer?",
                }),
            ).getByRole("button", { name: "Remove member" }),
        );

        const leadOutlineItem = await screen.findByRole("treeitem", {
            name: "Research lead",
        });
        await waitFor(() => expect(leadOutlineItem).toHaveFocus());
        expect(leadOutlineItem).toHaveAttribute("aria-selected", "true");
        expect(leadOutlineItem).toHaveAttribute("tabindex", "0");
        expect(
            screen
                .getAllByRole("treeitem")
                .filter((item) => item.tabIndex === 0),
        ).toEqual([leadOutlineItem]);
        expect(
            screen.queryByRole("treeitem", {
                name: /Independent reviewer/,
            }),
        ).not.toBeInTheDocument();
    });

    it("closes an ambiguous discard and keeps Check current plus leave protection actionable", async () => {
        const draftOnly = { ...draftFixture(), base_revision_no: null };
        const draftOnlyCatalog = catalogFixture({
            draft: draftOnly,
            published: false,
        });
        let reads = 0;
        const discardDraft = vi.fn(() =>
            Promise.reject(new ApiNetworkError(new Error("Connection lost."))),
        );
        const api = workflowApiStub({
            getWorkflow: () => {
                reads += 1;
                return reads === 2
                    ? Promise.reject(
                          new ApiNetworkError(new Error("Connection lost.")),
                      )
                    : Promise.resolve(response(draftOnlyCatalog));
            },
            getAuthoringOptions: () =>
                Promise.reject(new Error("Choices are unavailable.")),
            discardDraft,
        });
        const user = userEvent.setup();

        renderStudio(api);
        const purpose = await openWorkflowPurpose(user);
        await user.click(screen.getByRole("button", { name: "Discard draft" }));
        const discardDialog = screen.getByRole("dialog", {
            name: "Discard this draft?",
        });
        await user.click(
            within(discardDialog).getByRole("button", {
                name: "Discard draft",
            }),
        );

        await waitFor(() => {
            expect(discardDialog).not.toBeInTheDocument();
        });
        const checkCurrent = await screen.findByRole("button", {
            name: "Check current",
        });
        expect(screen.queryByText(/try discarding again/i)).toBeNull();
        expect(discardDraft).toHaveBeenCalledOnce();

        await user.click(checkCurrent);
        await waitFor(() => expect(reads).toBe(2));
        expect(purpose).toBeVisible();
        expect(purpose).toHaveValue(draftOnly.workflow.description);
        expect(
            screen.getByRole("button", { name: "Check current" }),
        ).toBeVisible();

        await user.click(screen.getByRole("link", { name: "Workflows" }));
        const warning = screen.getByRole("dialog", {
            name: "Discard unsaved changes?",
        });
        expect(warning).toBeVisible();
        await user.click(
            within(warning).getByRole("button", { name: "Continue editing" }),
        );
        await user.click(screen.getByRole("button", { name: "Check current" }));

        await waitFor(() => expect(reads).toBe(3));
        expect(
            screen.queryByRole("button", { name: "Check current" }),
        ).toBeNull();
        expect(discardDraft).toHaveBeenCalledOnce();
    });
});

function renderStudio(api: WorkflowApi, strict = false) {
    const routes: RouteObject[] = [
        {
            element: <WorkflowStudioPage api={api} />,
            path: "/workflows/:workflowId",
        },
        {
            element: <p>Workflow library route</p>,
            path: "/workflows",
        },
    ];
    const router = createMemoryRouter(routes, {
        initialEntries: [`/workflows/${TEST_WORKFLOW_ID}`],
    });

    const content = <RouterProvider router={router} />;
    return render(strict ? <StrictMode>{content}</StrictMode> : content);
}

async function openMemberDetails(user: ReturnType<typeof userEvent.setup>) {
    await user.click(
        await screen.findByText("Team outline", { selector: "summary" }),
    );
    await user.click(screen.getByRole("treeitem", { name: "Research lead" }));
    await user.click(screen.getByRole("button", { name: "Edit" }));
    return screen.getByRole("heading", { name: "Research lead" });
}

async function openWorkflowPurpose(
    user: ReturnType<typeof userEvent.setup>,
): Promise<HTMLElement> {
    await user.click(
        await screen.findByRole("button", { name: "Workflow settings" }),
    );
    return screen.getByLabelText("Purpose");
}
