import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import type { WorkflowDraftReadback } from "../../src/api/types";

const workflowLibrary = {
    items: [
        {
            workflow_id: "evidence-synthesis",
            description:
                "Research a question with independent evidence review.",
            state: "published",
            updated_at: "2026-07-25T05:00:00Z",
            provenance: "starter_seed",
            published_revision_no: 1,
            available_actions: ["edit", "start_run"],
        },
    ],
    next_cursor: null,
};
const draft: WorkflowDraftReadback = {
    draft_id: "workflow-draft.test",
    workflow_id: "evidence-synthesis",
    base_revision_no: 1,
    etag: '"wd-one"',
    workflow: {
        kind: "workflow",
        id: "evidence-synthesis",
        description: "Research a question with independent evidence review.",
        lead: {
            id: "member-1",
            title: "Research lead",
            children: [
                {
                    id: "member-2",
                    title: "Independent reviewer",
                },
            ],
        },
    },
};
const workflowDetail = {
    ...workflowLibrary.items[0],
    published: {
        workflow_id: "evidence-synthesis",
        revision_no: 1,
        workflow: draft.workflow,
    },
    revisions: [
        {
            workflow_id: "evidence-synthesis",
            revision_no: 1,
            provenance: "starter_seed",
        },
    ],
    active_draft: draft,
};
const authoringOptions = {
    workflow_fields: ["description", "note"],
    member_fields: [
        "title",
        "description",
        "instruction",
        "provider",
        "capabilities",
    ],
    provider_kinds: ["codex", "claude", "openclaw"],
    codex_efforts: ["low", "medium", "high"],
    claude_efforts: ["low", "medium", "high", "max"],
    managed_sandbox_options: [],
    human_request_kinds: ["input", "direction", "approval", "review"],
    command_run_values: ["allow"],
    default_provider: null,
};

test.beforeEach(async ({ page }) => {
    await page.route("**/api/workflows", async (route) => {
        await route.fulfill({ json: workflowLibrary });
    });
    await page.route("**/api/workflows/authoring-options", async (route) => {
        await route.fulfill({ json: authoringOptions });
    });
    await page.route("**/api/workflows/evidence-synthesis", async (route) => {
        await route.fulfill({ json: workflowDetail });
    });
});

test("the Workflow library is operable and accessible at page level", async ({
    page,
}, testInfo) => {
    await page.goto("/workflows");

    await expect(
        page.getByRole("heading", { name: "Workflows", exact: true }),
    ).toBeVisible();
    await expect(
        page.getByRole("heading", { name: "evidence-synthesis" }),
    ).toBeVisible();
    await expect(page.getByText("Starter")).toBeVisible();
    await expect(page.getByText("Published", { exact: true })).toBeVisible();
    await expect(
        page.getByRole("link", { name: "Open evidence-synthesis" }),
    ).toBeVisible();

    const createButton = page.getByRole("button", {
        name: "Create Workflow",
    });
    await createButton.click();
    const dialog = page.getByRole("dialog", { name: "Create a Workflow" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("Workflow ID")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(createButton).toBeFocused();

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({
        fullPage: true,
        path: testInfo.outputPath("workflow-library.png"),
    });
});

test("the library and Studio reflow at 320 CSS px with usable targets", async ({
    page,
}, testInfo) => {
    await page.setViewportSize({ width: 320, height: 900 });
    await page.goto("/workflows");
    await expect(
        page.getByRole("heading", { name: "Workflows", exact: true }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(page);
    const searchBox = await page
        .getByRole("searchbox", { name: "Search Workflows" })
        .boundingBox();
    expect(searchBox).not.toBeNull();
    expect(searchBox?.height ?? 0).toBeGreaterThanOrEqual(44);

    await page.goto("/workflows/evidence-synthesis");
    await expect(
        page.getByRole("region", { name: "Team hierarchy canvas" }),
    ).toBeVisible();
    await page.getByText("Team outline", { exact: true }).first().click();
    await page
        .getByRole("treeitem", { name: /Research lead.*Manager/ })
        .click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const details = page.getByRole("dialog", { name: "Details" });
    await expect(details).toBeVisible();
    await expect(details.getByLabel("Name")).toBeFocused();
    await expectNoHorizontalOverflow(page);
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({
        path: testInfo.outputPath("workflow-studio-reflow-320.png"),
    });
});

test("the Studio exposes one moving add control and an accessible hierarchy", async ({
    page,
}, testInfo) => {
    test.skip(
        testInfo.project.name === "mobile-chrome",
        "The dedicated 320px scenario owns the narrow-screen proof.",
    );

    const reviewer = draft.workflow.lead.children?.[0];
    if (reviewer === undefined) {
        throw new Error("Expected the reviewer fixture");
    }
    const deepDraft: WorkflowDraftReadback = {
        ...draft,
        workflow: {
            ...draft.workflow,
            lead: {
                ...draft.workflow.lead,
                children: [
                    {
                        ...reviewer,
                        children: [
                            {
                                id: "member-3",
                                title: "Source specialist",
                            },
                        ],
                    },
                ],
            },
        },
    };
    await page.route("**/api/workflows/evidence-synthesis", async (route) => {
        await route.fulfill({
            json: {
                ...workflowDetail,
                active_draft: deepDraft,
            },
        });
    });
    await page.goto("/workflows/evidence-synthesis");
    const addControl = page.getByRole("button", {
        name: /^Add child to /,
    });
    await expect(addControl).toHaveCount(1);
    await expect(addControl).toHaveAccessibleName("Add child to Research lead");
    await expect(
        page.getByText("Lines show responsibility, not task order."),
    ).toBeVisible();

    await page.getByRole("button", { name: "Tidy team" }).click();
    await page.getByRole("button", { name: "Fit team" }).click();
    await page.getByText("Team outline", { exact: true }).first().click();
    const tree = page.getByRole("tree", {
        name: "Workflow team hierarchy",
    });
    const lead = tree.getByRole("treeitem", {
        name: /Research lead.*Manager/,
    });
    await lead.focus();
    await page.keyboard.press("ArrowDown");
    const reviewerItem = tree.getByRole("treeitem", {
        name: /Independent reviewer.*Manager/,
    });
    await expect(reviewerItem).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(
        tree.getByRole("treeitem", {
            name: /Source specialist.*Contributor/,
        }),
    ).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(reviewerItem).toBeFocused();
    await page.keyboard.press("Enter");

    await expect(addControl).toHaveCount(1);
    await expect(addControl).toHaveAccessibleName(
        "Add child to Independent reviewer",
    );
    const outline = page.locator("[data-team-outline]");
    await expect(outline).toHaveAttribute("open", "");
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await expect(outline).not.toHaveAttribute("open", "");
    const details = page.locator("[data-details-surface]");
    await expect(details).toBeVisible();
    await expectNonOverlapping(
        page.locator('[data-member-card="member-2"]'),
        details,
    );
    await details
        .getByRole("button", { name: "Close teammate details" })
        .click();
    await expect(
        page.locator(
            '[data-focus-surface="canvas"][data-member-focus="member-2"]',
        ),
    ).toBeFocused();
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({
        fullPage: true,
        path: testInfo.outputPath("workflow-studio-hierarchy.png"),
    });
});

test("accepted add, edit, and subtree removal update the one Workflow team", async ({
    page,
}, testInfo) => {
    test.skip(
        testInfo.project.name === "mobile-chrome",
        "The serialized desktop scenario owns mutation semantics.",
    );
    let currentDraft: WorkflowDraftReadback = structuredClone(draft);
    let nextEtag = 2;
    await page.route("**/api/workflows/evidence-synthesis", async (route) => {
        await route.fulfill({
            json: {
                ...workflowDetail,
                active_draft: currentDraft,
                description: currentDraft.workflow.description,
            },
        });
    });
    await page.route(
        "**/api/workflow-drafts/workflow-draft.test",
        async (route) => {
            if (route.request().method() !== "PATCH") {
                await route.fallback();
                return;
            }
            const operation = route.request().postDataJSON() as {
                readonly kind: string;
                readonly member_id?: string;
                readonly parent_member_id?: string;
                readonly patch?: { readonly title?: string | null };
            };
            currentDraft = applyDraftOperation(
                currentDraft,
                operation,
                `"wd-${String(nextEtag)}"`,
            );
            nextEtag += 1;
            await route.fulfill({
                headers: { ETag: currentDraft.etag },
                json: {
                    draft: currentDraft,
                    undo_receipt: `receipt-${String(nextEtag)}`,
                },
            });
        },
    );

    await page.goto("/workflows/evidence-synthesis");
    await page
        .getByRole("button", { name: "Add child to Research lead" })
        .click();
    const newMember = page.getByRole("button", {
        name: /Untitled teammate.*Contributor/,
    });
    await expect(newMember).toBeVisible();
    await expect(
        page.getByRole("button", { name: /^Add child to / }),
    ).toHaveCount(1);
    await expectInsideCanvas(
        page,
        page.locator('[data-member-card="member-3"]'),
    );

    await newMember.click();
    const details = page.locator("[data-details-surface]");
    const memberUpdate = page.waitForResponse(
        (response) =>
            response.request().method() === "PATCH" &&
            new URL(response.url()).pathname ===
                "/api/workflow-drafts/workflow-draft.test",
    );
    await details
        .getByRole("textbox", { name: /Name/ })
        .fill("Source specialist");
    await memberUpdate;
    await expect(page.getByText("Saved. Undo is available.")).toBeVisible();
    await expect(
        page.getByRole("button", {
            name: /Source specialist.*Contributor/,
        }),
    ).toBeVisible();
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({
        path: testInfo.outputPath("workflow-studio-details-desktop.png"),
    });
    await details
        .getByRole("button", { name: "Close teammate details" })
        .click();
    await expect(
        page.locator(
            '[data-focus-surface="canvas"][data-member-focus="member-3"]',
        ),
    ).toBeFocused();

    await page.getByText("Team outline", { exact: true }).first().click();
    await page
        .getByRole("treeitem", { name: /Source specialist.*Contributor/ })
        .click();
    await page.getByRole("button", { name: "Remove branch" }).click();
    const removeDialog = page.getByRole("dialog", {
        name: "Remove Source specialist?",
    });
    await expect(removeDialog).toContainText("every teammate below it");
    await removeDialog.getByRole("button", { name: "Remove branch" }).click();

    await expect(
        page.getByRole("button", {
            name: /Source specialist.*Contributor/,
        }),
    ).toHaveCount(0);
    await expect(
        page.getByRole("button", { name: "Add child to Research lead" }),
    ).toBeVisible();
    const survivingParent = page.getByRole("treeitem", {
        name: /Research lead.*Manager/,
    });
    await expect(survivingParent).toHaveAttribute("aria-selected", "true");
    await expect(survivingParent).toHaveAttribute("tabindex", "0");
    await expect(survivingParent).toBeFocused();
    expect(
        await page
            .getByRole("treeitem")
            .evaluateAll(
                (items) =>
                    items.filter(
                        (item) => item.getAttribute("tabindex") === "0",
                    ).length,
            ),
    ).toBe(1);
    expect(await viewportZoom(page)).toBeGreaterThanOrEqual(0.67);
    await expectInsideUnobstructedCanvas(
        page,
        page.locator('[data-member-card="member-1"]'),
    );
});

test("the moving add control avoids every card in mixed deep peer branches", async ({
    page,
}, testInfo) => {
    test.skip(
        testInfo.project.name === "mobile-chrome",
        "The desktop hierarchy owns geometric layout proof.",
    );
    const mixedDraft = mixedDeepPeerDraft();
    await page.route("**/api/workflows/evidence-synthesis", async (route) => {
        await route.fulfill({
            json: { ...workflowDetail, active_draft: mixedDraft },
        });
    });

    await page.goto("/workflows/evidence-synthesis");
    await page.getByText("Team outline", { exact: true }).first().click();
    await page
        .getByRole("treeitem", { name: /Evidence manager A.*Manager/ })
        .click();
    const addControl = page.getByRole("button", {
        name: "Add child to Evidence manager A",
    });
    await expect(addControl).toHaveCount(1);
    const addBounds = await addControl.boundingBox();
    expect(addBounds).not.toBeNull();
    const cardBounds = await page
        .locator("[data-member-card]")
        .evaluateAll((cards) =>
            cards.map((card) => {
                const bounds = card.getBoundingClientRect();
                return {
                    bottom: bounds.bottom,
                    left: bounds.left,
                    right: bounds.right,
                    top: bounds.top,
                };
            }),
        );
    expect(
        cardBounds.every(
            (card) =>
                addBounds === null ||
                !rectanglesOverlap(
                    {
                        bottom: addBounds.y + addBounds.height,
                        left: addBounds.x,
                        right: addBounds.x + addBounds.width,
                        top: addBounds.y,
                    },
                    card,
                ),
        ),
    ).toBe(true);
    await page.screenshot({
        path: testInfo.outputPath("workflow-studio-mixed-deep-peer.png"),
    });
});

test("discarding a draft-only Workflow returns to a library without it", async ({
    page,
}) => {
    let discarded = false;
    const draftOnlyDetail = {
        ...workflowDetail,
        state: "draft",
        published_revision_no: null,
        published: null,
        revisions: [],
        active_draft: { ...draft, base_revision_no: null },
    };
    await page.route("**/api/workflows", async (route) => {
        await route.fulfill({
            json: discarded
                ? { items: [], next_cursor: null }
                : {
                      items: [
                          {
                              ...workflowLibrary.items[0],
                              state: "draft",
                              published_revision_no: null,
                              provenance: "user_authored",
                          },
                      ],
                      next_cursor: null,
                  },
        });
    });
    await page.route("**/api/workflows/evidence-synthesis", async (route) => {
        await route.fulfill({ json: draftOnlyDetail });
    });
    await page.route(
        "**/api/workflow-drafts/workflow-draft.test",
        async (route) => {
            if (route.request().method() !== "DELETE") {
                await route.fallback();
                return;
            }
            discarded = true;
            await route.fulfill({
                json: {
                    is_discarded: true,
                    draft_id: "workflow-draft.test",
                },
            });
        },
    );

    await page.goto("/workflows/evidence-synthesis");
    await page.getByRole("button", { name: "Discard draft" }).click();
    const dialog = page.getByRole("dialog", {
        name: "Discard this draft?",
    });
    await expect(dialog).toContainText("This Workflow exists only as a draft.");
    await dialog.getByRole("button", { name: "Discard draft" }).click();

    await expect(page).toHaveURL(/\/workflows$/);
    await expect(
        page.getByRole("heading", { name: "No Workflows yet" }),
    ).toBeVisible();
    expect(discarded).toBe(true);
});

test("an uncommitted discard is reconciled with one safe truth read", async ({
    page,
}) => {
    const draftOnlyDetail = {
        ...workflowDetail,
        state: "draft",
        published_revision_no: null,
        published: null,
        revisions: [],
        active_draft: { ...draft, base_revision_no: null },
    };
    let discardAttempted = false;
    let reconciliationReads = 0;
    let deletes = 0;
    await page.route("**/api/workflows/evidence-synthesis", async (route) => {
        if (discardAttempted) {
            reconciliationReads += 1;
        }
        await route.fulfill({ json: draftOnlyDetail });
    });
    await page.route(
        "**/api/workflow-drafts/workflow-draft.test",
        async (route) => {
            if (route.request().method() !== "DELETE") {
                await route.fallback();
                return;
            }
            deletes += 1;
            discardAttempted = true;
            await route.abort("failed");
        },
    );

    await page.goto("/workflows/evidence-synthesis");
    await page.getByRole("button", { name: "Discard draft" }).click();
    const dialog = page.getByRole("dialog", {
        name: "Discard this draft?",
    });
    await dialog.getByRole("button", { name: "Discard draft" }).click();

    await expect(dialog).toBeHidden();
    await expect(
        page.getByRole("button", { name: "Check current" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Check current" }).click();

    await page.getByText("Team outline", { exact: true }).first().click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const details = page.locator("[data-details-surface]");
    await details.getByText("Workflow purpose and shared note").click();
    await expect(details.getByLabel("Use this team when…")).toBeVisible();
    await expect
        .poll(() => ({ deletes, reconciliationReads }))
        .toEqual({
            deletes: 1,
            reconciliationReads: 1,
        });
});

test("a lost accepted discard response resolves from absence without replay", async ({
    page,
}) => {
    const draftOnlyDetail = {
        ...workflowDetail,
        state: "draft",
        published_revision_no: null,
        published: null,
        revisions: [],
        active_draft: { ...draft, base_revision_no: null },
    };
    let isRemoved = false;
    let reconciliationReads = 0;
    let deletes = 0;
    await page.route("**/api/workflows", async (route) => {
        await route.fulfill({
            json: isRemoved
                ? { items: [], next_cursor: null }
                : workflowLibrary,
        });
    });
    await page.route("**/api/workflows/evidence-synthesis", async (route) => {
        if (isRemoved) {
            reconciliationReads += 1;
            await route.fulfill({
                json: { detail: "Workflow not found." },
                status: 404,
            });
            return;
        }
        await route.fulfill({ json: draftOnlyDetail });
    });
    await page.route(
        "**/api/workflow-drafts/workflow-draft.test",
        async (route) => {
            if (route.request().method() !== "DELETE") {
                await route.fallback();
                return;
            }
            deletes += 1;
            isRemoved = true;
            await route.abort("failed");
        },
    );

    await page.goto("/workflows/evidence-synthesis");
    await page.getByRole("button", { name: "Discard draft" }).click();
    const dialog = page.getByRole("dialog", {
        name: "Discard this draft?",
    });
    await dialog.getByRole("button", { name: "Discard draft" }).click();

    await expect(dialog).toBeHidden();
    await page.getByRole("button", { name: "Check current" }).click();

    await expect(page).toHaveURL(/\/workflows$/);
    await expect(
        page.getByRole("heading", { name: "No Workflows yet" }),
    ).toBeVisible();
    expect({ deletes, reconciliationReads }).toEqual({
        deletes: 1,
        reconciliationReads: 1,
    });
});

async function expectNoHorizontalOverflow(page: Page) {
    const dimensions = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

async function expectNonOverlapping(
    left: Locator,
    right: Locator,
): Promise<void> {
    await expect
        .poll(async () => {
            const [leftBounds, rightBounds] = await Promise.all([
                left.boundingBox(),
                right.boundingBox(),
            ]);
            return (
                leftBounds !== null &&
                rightBounds !== null &&
                leftBounds.x + leftBounds.width <= rightBounds.x
            );
        })
        .toBe(true);
}

async function expectInsideCanvas(page: Page, member: Locator): Promise<void> {
    const canvas = page.locator("[data-team-canvas]");
    await expect
        .poll(async () => {
            const [canvasBounds, memberBounds] = await Promise.all([
                canvas.boundingBox(),
                member.boundingBox(),
            ]);
            return (
                canvasBounds !== null &&
                memberBounds !== null &&
                memberBounds.x >= canvasBounds.x &&
                memberBounds.x + memberBounds.width <=
                    canvasBounds.x + canvasBounds.width &&
                memberBounds.y >= canvasBounds.y &&
                memberBounds.y + memberBounds.height <=
                    canvasBounds.y + canvasBounds.height
            );
        })
        .toBe(true);
}

async function expectInsideUnobstructedCanvas(
    page: Page,
    member: Locator,
): Promise<void> {
    const canvas = page.locator("[data-team-canvas]");
    const outline = page.locator("[data-team-outline][open]");
    await expect
        .poll(async () => {
            const [canvasBounds, outlineBounds, memberBounds] =
                await Promise.all([
                    canvas.boundingBox(),
                    outline.boundingBox(),
                    member.boundingBox(),
                ]);
            return (
                canvasBounds !== null &&
                outlineBounds !== null &&
                memberBounds !== null &&
                memberBounds.x >= outlineBounds.x + outlineBounds.width &&
                memberBounds.x + memberBounds.width <=
                    canvasBounds.x + canvasBounds.width &&
                memberBounds.y >= canvasBounds.y &&
                memberBounds.y + memberBounds.height <=
                    canvasBounds.y + canvasBounds.height
            );
        })
        .toBe(true);
}

async function viewportZoom(page: Page): Promise<number> {
    return page.locator(".react-flow__viewport").evaluate((viewport) => {
        const match = /scale\(([^)]+)\)/.exec(
            (viewport as HTMLElement).style.transform,
        );
        return Number(match?.[1] ?? 0);
    });
}

function rectanglesOverlap(
    left: {
        readonly bottom: number;
        readonly left: number;
        readonly right: number;
        readonly top: number;
    },
    right: {
        readonly bottom: number;
        readonly left: number;
        readonly right: number;
        readonly top: number;
    },
): boolean {
    return (
        left.left < right.right &&
        left.right > right.left &&
        left.top < right.bottom &&
        left.bottom > right.top
    );
}

function mixedDeepPeerDraft(): WorkflowDraftReadback {
    return {
        ...draft,
        workflow: {
            ...draft.workflow,
            lead: {
                ...draft.workflow.lead,
                children: [
                    {
                        id: "member-a",
                        title: "Evidence manager A",
                        description:
                            "Own a tall evidence lane with localized context.",
                        children: [
                            {
                                id: "member-a1",
                                title: "Source specialist A",
                                description:
                                    "Collect primary evidence and explain limitations in detail.",
                            },
                        ],
                    },
                    {
                        id: "member-b",
                        title: "Evidence manager B",
                        children: [
                            {
                                id: "member-b1",
                                title: "Source specialist B",
                                description:
                                    "Challenge the neighboring branch with an independent review.",
                            },
                        ],
                    },
                ],
            },
        },
    };
}

function applyDraftOperation(
    current: WorkflowDraftReadback,
    operation: {
        readonly kind: string;
        readonly member_id?: string;
        readonly parent_member_id?: string;
        readonly patch?: { readonly title?: string | null };
    },
    etag: string,
): WorkflowDraftReadback {
    const next = structuredClone(current);
    next.etag = etag;
    if (operation.kind === "add_member") {
        next.workflow.lead.children = [
            ...(next.workflow.lead.children ?? []),
            { id: "member-3" },
        ];
    } else if (
        operation.kind === "update_member" &&
        operation.member_id === "member-3"
    ) {
        const member = (next.workflow.lead.children ?? []).find(
            (candidate) => candidate.id === "member-3",
        );
        const title = operation.patch?.title;
        if (member !== undefined && title !== undefined) {
            member.title = title;
        }
    } else if (
        operation.kind === "remove_member" &&
        operation.member_id === "member-3"
    ) {
        next.workflow.lead.children = (
            next.workflow.lead.children ?? []
        ).filter((member) => member.id !== "member-3");
    }
    return next;
}
