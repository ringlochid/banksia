/// <reference types="node" />

import { mkdirSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

import { createOperationFailureBody, createTaskStartResponse } from "../fixtures/console-api";
import { createDefinitionSummaryList } from "../fixtures/definitions";
import {
    TASK_START_SCREENSHOT_DIR,
    TASK_START_WORKFLOW_KEY,
    createTaskStartPreview,
    createTaskStartWorkflowDetail,
    createTaskStartWorkflowRows,
    createTaskStartWorkflowVersions,
} from "../fixtures/task-start";

test("starts a task from stored workflow truth at desktop width", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");

    await mockTaskStart(page);
    await page.goto("/task-start");

    await expect(page.getByRole("heading", { level: 1, name: "Task Start" })).toBeVisible();
    await expect(page.getByText(TASK_START_WORKFLOW_KEY).first()).toBeVisible();
    const selectedWorkflowSummary = page.getByRole("group", {
        name: "Selected workflow",
    });
    await expect(
        selectedWorkflowSummary.getByRole("heading", { name: TASK_START_WORKFLOW_KEY }),
    ).toBeVisible();
    await expect(selectedWorkflowSummary.getByText("Updated")).toBeVisible();
    await expectWorkflowActionClusterStacked(selectedWorkflowSummary);
    await expect(selectedWorkflowSummary.getByText(/Revision/)).toHaveCount(0);
    await expectNoDocumentOverflow(page);
    await expectTaskStartLaunchSectionReachable(page);

    await page.getByLabel("Search workflow").fill("normal");
    const workflowChoices = page.getByRole("list", { name: "Workflow choices" });
    await expect(workflowChoices).toBeVisible();
    await expect(workflowChoices.getByRole("button")).toHaveCount(1);
    await expect(workflowChoices.getByText(TASK_START_WORKFLOW_KEY).first()).toBeVisible();
    await expect(workflowChoices.getByText(/Revision/)).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Selected workflow" })).toHaveCount(0);
    await page.getByLabel("Search workflow").fill("");
    await expect(selectedWorkflowSummary).toBeVisible();
    await fillRequiredTaskFields(page);

    const previewButton = page.getByRole("button", { name: "Preview" });
    await previewButton.focus();
    await expect(previewButton).toBeFocused();
    await previewButton.click();
    const previewDialog = page.getByRole("dialog", { name: "Preview" });
    await expect(previewDialog).toBeVisible();
    await expect(previewDialog.getByRole("button", { name: "Back to edit" })).toBeFocused();
    await expect(previewDialog.getByText("Workflow", { exact: true })).toBeVisible();
    await expect(previewDialog.getByText(TASK_START_WORKFLOW_KEY)).toBeVisible();
    await expect(previewDialog.getByText("Task", { exact: true })).toBeVisible();
    await expect(previewDialog.getByText("Implement Task Start launch form")).toBeVisible();
    await expect(previewDialog.getByText("implement-task-start-launch-form")).toBeVisible();
    await expect(previewDialog.getByText("Summary", { exact: true })).toBeVisible();
    await expect(
        previewDialog.getByText(
            "Launch one bounded implementation task from stored workflow truth.",
        ),
    ).toBeVisible();
    await expect(previewDialog.getByText("Instruction", { exact: true })).toBeVisible();
    await expect(
        previewDialog.getByText(
            "Keep the work scoped to the current task-start UI and publish focused verification.",
        ),
    ).toBeVisible();
    await expect(previewDialog.getByText("Workspace", { exact: true })).toBeVisible();
    await expect(previewDialog.getByText(/does not reserve task or dispatch IDs/i)).toBeVisible();
    await expect(previewDialog.getByText("OpenClaw", { exact: true })).toBeVisible();
    await expect(previewDialog.getByText("experimental", { exact: true })).toBeVisible();
    await expect(previewDialog.getByText("Provider-native access").first()).toBeVisible();
    await expect(previewDialog.getByText("Network access").first()).toBeVisible();
    await expect(previewDialog.getByText(/Revision/)).toHaveCount(0);
    await expect(page.getByText("Task default").first()).toBeVisible();

    const accessibilityScanResults = await new AxeBuilder({ page })
        .exclude('a[aria-label="Fixture gallery"]')
        .analyze();
    expect(accessibilityScanResults.violations).toEqual([]);

    await previewDialog.getByRole("button", { name: "Start Task" }).click();
    await expect(page.getByText("Task launch committed")).toBeVisible();
    await expect(page.getByText(/Provider start follows asynchronously/i)).toBeVisible();
    const resultDialog = page.getByRole("dialog", { name: "Result" });
    await expect(resultDialog).toBeVisible();
    await expect(resultDialog.getByText("Flow status")).toBeVisible();
    await expect(resultDialog.getByText("Manifest", { exact: true })).toBeVisible();
    await expect(resultDialog.getByText("Running")).toBeVisible();
    await expect(resultDialog.getByText("task-console-fixture")).toBeVisible();
    await expect(resultDialog.getByText("compiled-plan-001")).toBeVisible();
    await expect(resultDialog.getByText("flow-revision-001")).toBeVisible();
    await expect(resultDialog.getByText("_runtime/workflow-manifest.md")).toBeVisible();

    mkdirSync(TASK_START_SCREENSHOT_DIR, { recursive: true });
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    await page.screenshot({
        fullPage: true,
        path: `${TASK_START_SCREENSHOT_DIR}/task-start-desktop.png`,
    });
});

test("opens the selected workflow detail from Task Start", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");

    await mockTaskStart(page);
    await page.goto("/task-start");

    const selectedWorkflowSummary = page.getByRole("group", {
        name: "Selected workflow",
    });
    const definitionDetailsLink = selectedWorkflowSummary.getByRole("link", {
        name: "Open definition details",
    });
    await expect(definitionDetailsLink).toHaveAttribute(
        "href",
        `/definitions?key=${TASK_START_WORKFLOW_KEY}&kind=workflow`,
    );

    await definitionDetailsLink.click();

    await expect(page).toHaveURL(
        new RegExp(`/definitions\\?key=${TASK_START_WORKFLOW_KEY}&kind=workflow`),
    );
    await expect(page.getByRole("heading", { level: 1, name: "Definitions" })).toBeVisible();
    await expect(definitionRow(page, TASK_START_WORKFLOW_KEY)).toHaveAttribute(
        "aria-pressed",
        "true",
    );
    await expect(
        page.getByRole("heading", { level: 2, name: TASK_START_WORKFLOW_KEY }),
    ).toBeVisible();
    await expect(page.getByText("Structure")).toBeVisible();
});

test("keeps Task Start root modes, validation, and layout usable at mobile width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-chrome", "mobile proof is captured once");

    await mockTaskStart(page, {
        startFailure: "The selected workspace is already held by a live task.",
    });
    await page.goto("/task-start");

    await expect(page.getByRole("heading", { level: 1, name: "Task Start" })).toBeVisible();
    await expect(page.getByText(TASK_START_WORKFLOW_KEY).first()).toBeVisible();
    const selectedWorkflowSummary = page.getByRole("group", {
        name: "Selected workflow",
    });
    await expect(
        selectedWorkflowSummary.getByRole("heading", { name: TASK_START_WORKFLOW_KEY }),
    ).toBeVisible();
    await expect(selectedWorkflowSummary.getByText("Updated")).toBeVisible();
    await expect(selectedWorkflowSummary.getByText(/Revision/)).toHaveCount(0);
    await expectNoDocumentOverflow(page);

    await page.getByLabel("Search workflow").fill("normal");
    const workflowChoices = page.getByRole("list", { name: "Workflow choices" });
    await expect(workflowChoices).toBeVisible();
    await expect(workflowChoices.getByRole("button")).toHaveCount(1);
    await expect(workflowChoices.getByText(TASK_START_WORKFLOW_KEY).first()).toBeVisible();
    await expect(workflowChoices.getByText(/Revision/)).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Selected workflow" })).toHaveCount(0);
    await page.getByLabel("Search workflow").fill("");
    await expect(selectedWorkflowSummary).toBeVisible();
    await fillRequiredTaskFields(page);

    const workspaceRoot = page.getByRole("region", { name: "Workspace root" });
    await workspaceRoot.getByRole("button", { name: "Create host path" }).click();
    await workspaceRoot.getByLabel("Host path").fill("/tmp/task-start-workspace");

    await page.getByLabel("Task key").fill("");
    await page.getByRole("button", { name: "Preview" }).click();
    await expect(page.getByText("Task key is required.")).toBeVisible();
    await page.getByLabel("Task key").fill("task-start-mobile-proof");
    await page.getByRole("button", { name: "Start Task" }).click();
    await expect(
        page.getByText("The selected workspace is already held by a live task."),
    ).toBeVisible();
    await expectNoDocumentOverflow(page);

    mkdirSync(TASK_START_SCREENSHOT_DIR, { recursive: true });
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    await page.screenshot({
        fullPage: true,
        path: `${TASK_START_SCREENSHOT_DIR}/task-start-mobile.png`,
    });
});

async function mockTaskStart(
    page: Page,
    options: { readonly startFailure?: string } = {},
): Promise<void> {
    await page.route("http://127.0.0.1:18125/definitions/**", async (route) => {
        const request = route.request();
        const requestUrl = new URL(request.url());
        const path = requestUrl.pathname;

        if (request.method() !== "GET") {
            await route.fulfill({ status: 404 });
            return;
        }

        if (path === "/definitions/workflows") {
            const query = (requestUrl.searchParams.get("q") ?? "").trim().toLowerCase();
            const limit = Number(requestUrl.searchParams.get("limit"));
            const rows = createTaskStartWorkflowRows().filter((workflow) =>
                taskStartWorkflowMatchesQuery(workflow, query),
            );
            const limitedRows = Number.isFinite(limit) && limit > 0 ? rows.slice(0, limit) : rows;

            await fulfillJson(route, createDefinitionSummaryList("workflow", limitedRows, null));
            return;
        }

        if (path.endsWith("/versions")) {
            const key = path.split("/").at(-2) ?? TASK_START_WORKFLOW_KEY;
            await fulfillJson(route, createTaskStartWorkflowVersions(key));
            return;
        }

        const key = path.split("/").at(-1) ?? TASK_START_WORKFLOW_KEY;
        await fulfillJson(route, createTaskStartWorkflowDetail(key));
    });

    await page.route("http://127.0.0.1:18125/tasks/start", async (route) => {
        if (options.startFailure !== undefined) {
            await route.fulfill({
                body: JSON.stringify(
                    createOperationFailureBody({
                        code: "conflicting_continuation",
                        retryable: false,
                        summary: options.startFailure,
                    }),
                ),
                contentType: "application/json",
                status: 409,
            });
            return;
        }

        await fulfillJson(route, createTaskStartResponse());
    });
    await page.route("http://127.0.0.1:18125/authoring/task-compose/preview", async (route) => {
        await fulfillJson(route, createTaskStartPreview());
    });
}

async function expectWorkflowActionClusterStacked(selectedWorkflowSummary: Locator): Promise<void> {
    const updatedPill = selectedWorkflowSummary.locator('[aria-label^="Updated "]');
    const definitionDetailsLink = selectedWorkflowSummary.getByRole("link", {
        name: "Open definition details",
    });

    await expect(updatedPill).toBeVisible();
    await expect(definitionDetailsLink).toBeVisible();

    const updatedPillBox = await updatedPill.boundingBox();
    const definitionDetailsLinkBox = await definitionDetailsLink.boundingBox();

    if (updatedPillBox === null || definitionDetailsLinkBox === null) {
        throw new Error("Workflow action cluster did not produce measurable boxes.");
    }

    expect(definitionDetailsLinkBox.y).toBeGreaterThan(updatedPillBox.y + updatedPillBox.height);
    expect(
        Math.abs(
            updatedPillBox.x +
                updatedPillBox.width -
                (definitionDetailsLinkBox.x + definitionDetailsLinkBox.width),
        ),
    ).toBeLessThanOrEqual(1);
    expect(definitionDetailsLinkBox.width).toBeLessThan(updatedPillBox.width);
}

function definitionRow(page: Page, key: string): Locator {
    return page.getByRole("button", { name: new RegExp(`^${key}\\b`) });
}

async function expectTaskStartLaunchSectionReachable(page: Page): Promise<void> {
    const metrics = await page.evaluate(() => {
        window.scrollTo(0, document.documentElement.scrollHeight);
        const shell = document.querySelector("main");
        if (shell !== null) {
            shell.scrollTop = shell.scrollHeight;
        }
        return {
            clientHeight: document.documentElement.clientHeight,
            scrollHeight: document.documentElement.scrollHeight,
            shellScrollTop: shell === null ? 0 : shell.scrollTop,
            scrollY: window.scrollY,
        };
    });

    expect(metrics.scrollHeight).toBeGreaterThan(metrics.clientHeight);
    expect(metrics.scrollY).toBeGreaterThan(0);
    expect(metrics.shellScrollTop).toBe(0);
    await expect(page.getByRole("button", { name: "Start Task" })).toBeVisible();
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
}

function taskStartWorkflowMatchesQuery(
    workflow: ReturnType<typeof createTaskStartWorkflowRows>[number],
    query: string,
): boolean {
    if (query.length === 0) {
        return true;
    }

    return [workflow.key, workflow.description ?? "", workflow.title ?? ""].some((field) =>
        field.toLowerCase().includes(query),
    );
}

async function fulfillJson(route: Route, body: unknown): Promise<void> {
    await route.fulfill({
        body: JSON.stringify(body),
        contentType: "application/json",
    });
}

async function fillRequiredTaskFields(page: Page): Promise<void> {
    await page.getByLabel("Task key").fill("implement-task-start-launch-form");
    await page.getByLabel("Title").fill("Implement Task Start launch form");
    await page
        .getByLabel("Summary")
        .fill("Launch one bounded implementation task from stored workflow truth.");
    await page
        .getByLabel("Instruction")
        .fill(
            "Keep the work scoped to the current task-start UI and publish focused verification.",
        );
}

async function expectNoDocumentOverflow(page: Page): Promise<void> {
    const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );

    expect(overflow).toBeLessThanOrEqual(1);
}
