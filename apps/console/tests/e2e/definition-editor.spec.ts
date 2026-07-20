/// <reference types="node" />

import { mkdirSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import {
    DEFINITION_EDITOR_SCREENSHOT_DIR,
    DEFINITION_EDITOR_ROLE_KEY,
    DEFINITION_EDITOR_WORKFLOW_KEY,
    bodyForKind,
    createCleanDefinitionEditorDraft,
    createDefinitionEditorDraftDetail,
    createDefinitionEditorDraftList,
    createDefinitionEditorDraftResponse,
    createDefinitionEditorPublish,
    createDefinitionEditorValidation,
} from "../fixtures/definition-editor";

test("renders flat Definition Editor draft workflow at desktop width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");

    await mockDefinitionEditor(page);
    await page.setViewportSize({ height: 1000, width: 1440 });
    await page.goto("/definitions/editor");

    await expect(page.getByRole("heading", { level: 1, name: "Definition Editor" })).toBeVisible();
    await expect(
        page.getByRole("button", { name: new RegExp(DEFINITION_EDITOR_WORKFLOW_KEY) }),
    ).toBeVisible();
    await expect(
        page.getByRole("button", { name: new RegExp(DEFINITION_EDITOR_ROLE_KEY) }),
    ).toBeVisible();
    await expect(page.getByLabel("Draft body")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save draft" })).toBeDisabled();
    await expectDraftRowsStayStacked(page);

    await page.getByRole("button", { name: "Reset draft" }).click();
    const resetDialog = page.getByRole("dialog", { name: "Reset draft" });
    await expect(resetDialog).toBeVisible();
    await expect(
        resetDialog.getByText(/restores the selected file to its captured draft baseline/i),
    ).toBeVisible();
    await resetDialog.getByRole("button", { name: "Cancel" }).click();

    await page.getByRole("button", { name: "Replace with current stored revision" }).click();
    const replaceDialog = page.getByRole("dialog", {
        name: "Replace with current stored revision",
    });
    await expect(replaceDialog).toBeVisible();
    await expect(
        replaceDialog.getByText(/reads the current stored registry revision/i),
    ).toBeVisible();
    await replaceDialog.getByRole("button", { name: "Cancel" }).click();

    await page.getByRole("button", { name: "Discard saved draft" }).click();
    const discardDialog = page.getByRole("dialog", { name: "Discard saved draft" });
    await expect(discardDialog).toBeVisible();
    await expect(
        discardDialog.getByText(/permanently removes the saved draft file/i),
    ).toBeVisible();
    await discardDialog.getByRole("button", { name: "Cancel" }).click();

    const validateButton = page.getByRole("button", { name: "Validate" });
    await validateButton.focus();
    await expect(validateButton).toBeFocused();

    const accessibilityScanResults = await new AxeBuilder({ page })
        .exclude('a[aria-label="Fixture gallery"]')
        .analyze();
    expect(accessibilityScanResults.violations).toEqual([]);

    await page.getByLabel("Draft body").fill("kind: workflow\nid: definition-editor-page\n");
    await expect(page.getByText("local edits")).toBeVisible();
    await page.getByRole("button", { name: new RegExp(DEFINITION_EDITOR_ROLE_KEY) }).click();
    const unsavedDialog = page.getByRole("dialog", { name: "Discard local draft edits?" });
    await expect(unsavedDialog).toBeVisible();
    await expect(unsavedDialog.getByText(/exist only in this browser tab/i)).toBeVisible();
    await unsavedDialog.getByRole("button", { name: "Keep editing" }).click();
    await expect(page.getByLabel("Draft body")).toHaveValue(
        "kind: workflow\nid: definition-editor-page\n",
    );
    await page.getByRole("button", { name: "Validate" }).click();
    const validationDialog = page.getByRole("dialog", { name: "Validation valid" });
    await expect(validationDialog).toBeVisible();
    await expect(validationDialog.getByText("No validation issues returned.")).toBeVisible();
    await validationDialog.getByRole("button", { exact: true, name: "Close" }).click();
    await expect(validationDialog).toBeHidden();

    await page.getByRole("button", { name: "Publish" }).click();
    const publishDialog = page.getByRole("dialog", { name: "Publish published" });
    await expect(publishDialog).toBeVisible();
    await expect(
        publishDialog.getByText(/Workflow definition-editor-page revision 14/),
    ).toBeVisible();
    await expect(publishDialog.getByText(/Reread the published registry/i)).toBeVisible();
    await publishDialog.getByRole("button", { exact: true, name: "Close" }).click();

    await expectNoDocumentOverflow(page);

    mkdirSync(DEFINITION_EDITOR_SCREENSHOT_DIR, { recursive: true });
    await page.evaluate(() => {
        if (document.activeElement instanceof HTMLElement) {
            document.activeElement.blur();
        }
        window.scrollTo(0, 0);
    });
    await page.screenshot({
        fullPage: true,
        path: `${DEFINITION_EDITOR_SCREENSHOT_DIR}/definition-editor-desktop.png`,
    });
});

test("keeps flat Definition Editor usable at mobile width", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-chrome", "mobile proof is captured once");

    await mockDefinitionEditor(page);
    await page.goto("/definitions/editor");

    await expect(page.getByRole("heading", { level: 1, name: "Definition Editor" })).toBeVisible();
    await expect(page.getByLabel("Draft body")).toBeVisible();
    await page.getByRole("button", { name: "New draft" }).first().click();
    await expect(page.getByRole("dialog", { name: "New draft" })).toBeVisible();
    await expectNoDocumentOverflow(page);

    mkdirSync(DEFINITION_EDITOR_SCREENSHOT_DIR, { recursive: true });
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    await page.screenshot({
        fullPage: true,
        path: `${DEFINITION_EDITOR_SCREENSHOT_DIR}/definition-editor-mobile.png`,
    });
});

test("keeps the Definition Editor workbench stable with no saved drafts", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");

    await mockEmptyDefinitionEditor(page);
    await page.setViewportSize({ height: 1000, width: 1440 });
    await page.goto("/definitions/editor");

    await expect(page.getByRole("heading", { level: 1, name: "Definition Editor" })).toBeVisible();
    await expect(page.getByText("No saved drafts")).toBeVisible();
    await expect(page.getByText("Select a draft")).toBeVisible();

    const metrics = await page.evaluate(() => {
        const frame = document.querySelector("main > section");
        const emptyPanel = [...document.querySelectorAll("section")].find((element) =>
            element.textContent.includes("Select a draft"),
        );
        const box = (element: Element) => {
            const rect = element.getBoundingClientRect();
            return {
                height: Math.round(rect.height),
                width: Math.round(rect.width),
            };
        };
        return {
            emptyPanel: emptyPanel === undefined ? null : box(emptyPanel),
            frame: frame === null ? null : box(frame),
        };
    });

    expect(metrics.frame?.width).toBeGreaterThan(900);
    expect(metrics.frame?.height).toBeGreaterThan(700);
    expect(metrics.emptyPanel?.height).toBeGreaterThan(600);
    await expectNoDocumentOverflow(page);

    mkdirSync(DEFINITION_EDITOR_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({
        fullPage: true,
        path: `${DEFINITION_EDITOR_SCREENSHOT_DIR}/definition-editor-empty-desktop.png`,
    });
});

async function mockDefinitionEditor(page: Page): Promise<void> {
    let detail = createDefinitionEditorDraftDetail();
    const roleDraft = createDefinitionEditorDraftDetail({
        body: bodyForKind("role", DEFINITION_EDITOR_ROLE_KEY),
        key: DEFINITION_EDITOR_ROLE_KEY,
        kind: "role",
        status: "clean",
    });
    await page.route("**/authoring/definition-drafts**", async (route) => {
        const request = route.request();
        if (request.method() === "GET") {
            await fulfillJson(route, createDefinitionEditorDraftList(detail, roleDraft));
            return;
        }
        await fulfillJson(route, createDefinitionEditorDraftResponse(detail));
    });
    await page.route("**/authoring/definitions/**/draft", async (route) => {
        const request = route.request();
        if (request.method() === "PUT") {
            const body = (await request.postDataJSON()) as { readonly body: string };
            detail = createCleanDefinitionEditorDraft(body.body);
            await fulfillJson(route, createDefinitionEditorDraftResponse(detail));
            return;
        }
        if (request.method() === "DELETE") {
            await route.fulfill({ status: 204 });
            return;
        }
        await fulfillJson(route, createDefinitionEditorDraftResponse(detail));
    });
    await page.route("**/authoring/definitions/**/draft/validate", async (route) => {
        await fulfillJson(route, createDefinitionEditorValidation("valid"));
    });
    await page.route("**/authoring/definitions/**/draft/publish", async (route) => {
        await fulfillJson(route, createDefinitionEditorPublish("published"));
    });
}

async function mockEmptyDefinitionEditor(page: Page): Promise<void> {
    await page.route("**/authoring/definition-drafts**", async (route) => {
        if (route.request().method() === "GET") {
            await fulfillJson(route, {
                items: [],
                next_cursor: null,
            });
            return;
        }

        await route.fulfill({ status: 404 });
    });
}

async function fulfillJson(route: Route, body: unknown): Promise<void> {
    await route.fulfill({
        body: JSON.stringify(body),
        contentType: "application/json",
    });
}

async function expectNoDocumentOverflow(page: Page): Promise<void> {
    const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );

    expect(overflow).toBeLessThanOrEqual(1);
}

async function expectDraftRowsStayStacked(page: Page): Promise<void> {
    const workflowDraft = page.getByRole("button", {
        name: new RegExp(DEFINITION_EDITOR_WORKFLOW_KEY),
    });
    const roleDraft = page.getByRole("button", { name: new RegExp(DEFINITION_EDITOR_ROLE_KEY) });
    const workflowBox = await workflowDraft.boundingBox();
    const roleBox = await roleDraft.boundingBox();

    expect(workflowBox).not.toBeNull();
    expect(roleBox).not.toBeNull();
    if (workflowBox === null || roleBox === null) {
        return;
    }

    expect(roleBox.y - workflowBox.y - workflowBox.height).toBeLessThanOrEqual(16);
}
