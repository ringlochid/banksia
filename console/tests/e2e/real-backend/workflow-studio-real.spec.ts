import AxeBuilder from "@axe-core/playwright";
import {
    expect,
    test,
    type APIRequestContext,
    type Page,
} from "@playwright/test";

import type {
    WorkflowDraftReadback,
    WorkflowGetResponse,
    WorkflowSearchResponse,
} from "../../../src/api/types";

const WORKFLOW_ID = "browser-research-team";
const STARTER_WORKFLOW_IDS = [
    "bounded-maintenance-batch",
    "cross-layer-feature",
    "debug-and-verify",
    "evidence-synthesis",
    "reproducible-study",
    "reviewed-code-change",
    "technical-decision",
] as const;
const INITIAL_PURPOSE =
    "Investigate a complex question with accountable evidence review.";
const FINAL_PURPOSE =
    "Investigate complex questions with accountable evidence review.";

test("authors and publishes a Workflow against disposable controller truth", async ({
    page,
    request,
}, testInfo) => {
    await proveSeededLibraryReadback(page, request);
    await createWorkflowThroughBrowser(page);
    await editLeadAndWorkflow(page, request);
    const childId = await addAndEditChild(page, request);
    await proveAcceptedReload(page, childId);
    await proveConflictAndRecovery(page, request);
    const published = await publishThroughBrowser(page, request);
    await provePublishedReopen(page, request, published);

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({
        fullPage: true,
        path: testInfo.outputPath("workflow-studio-real-controller.png"),
    });
});

async function proveSeededLibraryReadback(
    page: Page,
    request: APIRequestContext,
): Promise<void> {
    const response = await request.get("/api/workflows");
    expect(response.status()).toBe(200);
    const library = (await response.json()) as WorkflowSearchResponse;
    expect(library.items.map((item) => item.workflow_id)).toEqual(
        STARTER_WORKFLOW_IDS,
    );

    await page.goto("/workflows");
    await expect(
        page.getByRole("heading", { name: "Workflows", exact: true }),
    ).toBeVisible();
    for (const workflowId of STARTER_WORKFLOW_IDS) {
        await expect(
            page.getByRole("heading", { name: workflowId }),
        ).toBeVisible();
    }
}

async function createWorkflowThroughBrowser(page: Page): Promise<void> {
    await page.getByRole("button", { name: "Create Workflow" }).click();
    const dialog = page.getByRole("dialog", { name: "Create a Workflow" });
    await dialog.getByLabel("Workflow ID").fill(WORKFLOW_ID);
    await dialog.getByLabel("Use this team when…").fill(INITIAL_PURPOSE);
    const createResponse = page.waitForResponse(
        (response) =>
            response.request().method() === "POST" &&
            new URL(response.url()).pathname === "/api/workflow-drafts",
    );
    await dialog.getByRole("button", { name: "Create Workflow" }).click();
    expect((await createResponse).status()).toBe(201);

    await expect(page).toHaveURL(
        `/workflows/${encodeURIComponent(WORKFLOW_ID)}`,
    );
    await expect(
        page.getByRole("heading", { level: 1, name: WORKFLOW_ID }),
    ).toBeVisible();
}

async function editLeadAndWorkflow(
    page: Page,
    request: APIRequestContext,
): Promise<void> {
    await page
        .getByRole("button", { name: /Untitled teammate.*Contributor/ })
        .click();
    const details = page.getByRole("complementary", { name: "Details" });
    await details.getByRole("textbox", { name: /Name/ }).fill("Research lead");
    await details
        .getByRole("textbox", { name: /Responsibility/ })
        .fill("Own the final answer and delegate bounded evidence work.");
    await details
        .getByRole("textbox", { name: /Instruction/ })
        .fill("Synthesize findings, resolve conflicts, and verify the result.");
    await details.getByText("Workflow purpose and shared note").click();
    await details.getByLabel("Use this team when…").fill(FINAL_PURPOSE);
    await details.getByText("Shared note", { exact: true }).click();
    await details
        .getByLabel("Note")
        .fill("Prefer primary sources and record material uncertainty.");

    await expect
        .poll(async () => {
            const workflow = await getWorkflow(request);
            return {
                description: workflow.active_draft?.workflow.description,
                leadTitle: workflow.active_draft?.workflow.lead.title,
                note: workflow.active_draft?.workflow.note,
            };
        })
        .toEqual({
            description: FINAL_PURPOSE,
            leadTitle: "Research lead",
            note: "Prefer primary sources and record material uncertainty.",
        });
    await details
        .getByRole("button", { name: "Close teammate details" })
        .click();
}

async function addAndEditChild(
    page: Page,
    request: APIRequestContext,
): Promise<string> {
    const addResponse = page.waitForResponse(
        (response) =>
            response.request().method() === "PATCH" &&
            new URL(response.url()).pathname.startsWith(
                "/api/workflow-drafts/",
            ),
    );
    await page
        .getByRole("button", { name: "Add child to Research lead" })
        .click();
    const accepted = (await (await addResponse).json()) as {
        readonly draft: WorkflowDraftReadback;
    };
    const child = accepted.draft.workflow.lead.children?.[0];
    expect(child?.id).toBeTruthy();
    expect(child?.id).not.toBe(accepted.draft.workflow.lead.id);

    await page
        .getByRole("button", { name: /Untitled teammate.*Contributor/ })
        .click();
    const details = page.getByRole("complementary", { name: "Details" });
    await details
        .getByRole("textbox", { name: /Name/ })
        .fill("Evidence reviewer");
    await details
        .getByRole("textbox", { name: /Responsibility/ })
        .fill("Challenge evidence quality and identify unsupported claims.");
    await details
        .getByRole("textbox", { name: /Instruction/ })
        .fill("Review independently and rank findings by impact.");

    await expect
        .poll(async () => {
            const workflow = await getWorkflow(request);
            const currentChild =
                workflow.active_draft?.workflow.lead.children?.find(
                    (member) => member.id === child!.id,
                );
            return {
                childId: currentChild?.id,
                childTitle: currentChild?.title,
            };
        })
        .toEqual({
            childId: child!.id,
            childTitle: "Evidence reviewer",
        });
    return child!.id;
}

async function proveAcceptedReload(page: Page, childId: string): Promise<void> {
    await page.reload();
    await expect(
        page.getByRole("button", { name: /Research lead.*Manager/ }),
    ).toBeVisible();
    await expect(
        page.getByRole("button", { name: /Evidence reviewer.*Contributor/ }),
    ).toBeVisible();
    await expect(
        page.getByRole("button", { name: /^Add child to / }),
    ).toHaveCount(1);
    expect(
        await page
            .getByRole("button", { name: /Evidence reviewer.*Contributor/ })
            .getAttribute("data-member-focus"),
    ).toBe(childId);
}

async function proveConflictAndRecovery(
    page: Page,
    request: APIRequestContext,
): Promise<void> {
    const beforeExternalChange = await getWorkflow(request);
    const draft = requireDraft(beforeExternalChange);
    const externalResponse = await request.patch(
        `/api/workflow-drafts/${encodeURIComponent(draft.draft_id)}`,
        {
            data: {
                kind: "update_workflow",
                patch: {
                    note: "External reviewer added this durable context.",
                },
            },
            headers: {
                "Content-Type": "application/json",
                "If-Match": draft.etag,
            },
        },
    );
    expect(externalResponse.status()).toBe(200);

    await page.getByRole("button", { name: /Research lead.*Manager/ }).click();
    const details = page.getByRole("complementary", { name: "Details" });
    const staleResponse = page.waitForResponse(
        (response) =>
            response.status() === 412 &&
            response.request().method() === "PATCH",
    );
    await details
        .getByRole("textbox", { name: /Responsibility/ })
        .fill("Lead owns the verified answer and its final handoff.");
    await staleResponse;

    await expect(
        page.getByRole("heading", {
            name: "This draft changed elsewhere",
        }),
    ).toBeFocused();
    await page.getByRole("button", { name: "Reload current" }).click();
    await expect(
        page.getByRole("heading", {
            name: "This draft changed elsewhere",
        }),
    ).toHaveCount(0);

    const recoveredDetails = page.getByRole("complementary", {
        name: "Details",
    });
    await expect(
        page.getByRole("button", { name: /Research lead.*Manager/ }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(recoveredDetails.getByLabel("Name")).toBeFocused();
    await recoveredDetails
        .getByRole("textbox", { name: /Responsibility/ })
        .fill("Lead owns the verified answer and its final handoff.");
    await expect
        .poll(async () => {
            const current = await getWorkflow(request);
            return {
                note: current.active_draft?.workflow.note,
                responsibility: current.active_draft?.workflow.lead.description,
            };
        })
        .toEqual({
            note: "External reviewer added this durable context.",
            responsibility:
                "Lead owns the verified answer and its final handoff.",
        });
}

async function publishThroughBrowser(page: Page, request: APIRequestContext) {
    const publishResponse = page.waitForResponse(
        (response) =>
            response.request().method() === "POST" &&
            /\/api\/workflow-drafts\/[^/]+\/publish$/.test(
                new URL(response.url()).pathname,
            ),
    );
    await page.getByRole("button", { name: "Publish" }).click();
    expect((await publishResponse).status()).toBe(200);
    await expect(
        page.getByText("Published Workflow", { exact: true }),
    ).toBeVisible();

    const current = await getWorkflow(request);
    expect(current.active_draft).toBeNull();
    expect(current.state).toBe("published");
    expect(current.published?.workflow.lead.children?.[0]?.title).toBe(
        "Evidence reviewer",
    );
    return current.published!;
}

async function provePublishedReopen(
    page: Page,
    request: APIRequestContext,
    published: NonNullable<WorkflowGetResponse["published"]>,
): Promise<void> {
    await page.reload();
    await expect(
        page.getByText("Published Workflow", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Edit Workflow" }).click();
    await expect(
        page.getByRole("region", { name: "Team hierarchy canvas" }),
    ).toBeVisible();

    const reopened = await getWorkflow(request);
    expect(reopened.published).toEqual(published);
    expect(reopened.active_draft?.base_revision_no).toBe(published.revision_no);
    expect(reopened.active_draft?.workflow).toEqual(published.workflow);
}

async function getWorkflow(
    request: APIRequestContext,
): Promise<WorkflowGetResponse> {
    const response = await request.get(
        `/api/workflows/${encodeURIComponent(WORKFLOW_ID)}`,
    );
    expect(response.status()).toBe(200);
    return (await response.json()) as WorkflowGetResponse;
}

function requireDraft(workflow: WorkflowGetResponse): WorkflowDraftReadback {
    const draft = workflow.active_draft;
    if (draft === null || draft === undefined) {
        throw new Error("Expected an active Workflow draft");
    }
    return draft;
}
