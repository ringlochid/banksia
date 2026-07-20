import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";

import type { components } from "../../src/api/generated/openapi";
import {
    COMMAND_RUN_LOG_CONTENT,
    COMMAND_RUN_TASK_ID,
    createCommandRunDetail,
    createCommandRunDetailMap,
    createCommandRunLogRead,
    createCommandRunPageList,
} from "../fixtures/command-runs";
import { createOperationFailureBody, createRuntimeFlowRead } from "../fixtures/console-api";

const SCREENSHOT_DIR =
    "/home/ubuntu/leo/projects/autoclaw/tmp/autoclaw-frontend/full-delivery-design-parity/04-command-runs/screenshots";

test("renders command-run detail, logs, cancel errors, and accessibility at desktop width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");

    await mockCommandRuns(page);

    await page.goto(`/tasks/${COMMAND_RUN_TASK_ID}/command-runs`);

    await expect(
        page.getByRole("heading", { level: 1, name: "Refresh runtime route copy" }),
    ).toBeVisible();
    await expect(page.getByLabel("AutoClaw Console").getByText("Command Runs")).toBeVisible();
    await expect(page.getByText("Run focused runtime route tests.")).toBeVisible();
    await expect(page.getByText("Verify command-run runner behavior.")).toBeVisible();
    await expect(page.getByText("Cancel request accepted.")).toBeVisible();
    await expect(page.getByText("Check prompt continuation rendering.")).toBeVisible();
    await expectNoDocumentOverflow(page);

    const accessibilityScanResults = await new AxeBuilder({ page })
        .exclude('a[aria-label="Fixture gallery"]')
        .analyze();
    expect(accessibilityScanResults.violations).toEqual([]);

    await page.getByText("Check prompt continuation rendering.").click();
    await expect(page.getByText("Result")).toBeVisible();
    await expect(page.getByText("Log access")).toBeVisible();
    await expect(page.getByText(COMMAND_RUN_LOG_CONTENT)).toHaveCount(0);

    await page.getByRole("button", { name: "View logs" }).click();
    await expect(page.getByText(COMMAND_RUN_LOG_CONTENT)).toBeVisible();
    await expect(page.getByRole("button", { name: "Hide logs" })).toBeVisible();

    const taskDetailLink = page.getByRole("link", { name: "Open task detail" }).first();
    await taskDetailLink.focus();
    await expect(taskDetailLink).toBeFocused();
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({
        fullPage: true,
        path: `${SCREENSHOT_DIR}/app-desktop-default.png`,
    });

    await page.getByRole("button", { name: "Cancel" }).first().click();
    await expect(page.getByText("Cancel state changed")).toBeVisible();
    await expect(page.getByText("Reread command-run truth before retrying cancel.")).toBeVisible();
});

test("keeps command-run rows and expanded detail usable at mobile width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-chrome", "mobile proof is captured once");

    await mockCommandRuns(page, { cancelSucceeds: true });

    await page.goto(`/tasks/${COMMAND_RUN_TASK_ID}/command-runs`);

    await expect(page.getByText("Check prompt continuation rendering.")).toBeVisible();
    await page.getByText("Check prompt continuation rendering.").click();
    await expect(page.getByText("Result")).toBeVisible();
    await expect(page.getByRole("button", { name: "View logs" })).toBeVisible();
    await expectNoDocumentOverflow(page);

    await page.getByRole("button", { name: "View logs" }).focus();
    await expect(page.getByRole("button", { name: "View logs" })).toBeFocused();
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({
        fullPage: true,
        path: `${SCREENSHOT_DIR}/app-narrow-default.png`,
    });
});

async function mockCommandRuns(
    page: Page,
    options: { readonly cancelSucceeds?: boolean } = {},
): Promise<void> {
    const details = createCommandRunDetailMap();

    await page.route("**/control/tasks/**", async (route) => {
        const request = route.request();
        const requestUrl = new URL(request.url());
        const path = requestUrl.pathname;
        const runId = path.split("/").at(-1);

        if (request.method() === "GET" && path.endsWith(`/${COMMAND_RUN_TASK_ID}/command-runs`)) {
            await fulfillJson(route, createCommandRunPageList({ next_cursor: null }));
            return;
        }

        if (request.method() === "GET" && path.endsWith(`/${COMMAND_RUN_TASK_ID}/snapshot`)) {
            await fulfillJson(route, {
                current_paths: [],
                flow: createRuntimeFlowRead({
                    task_id: COMMAND_RUN_TASK_ID,
                    task_title: "Refresh runtime route copy",
                }),
                stream_head_event_id: null,
                top_actionable_items: [],
            } satisfies components["schemas"]["OperatorFlowSnapshotResponse"]);
            return;
        }

        if (request.method() === "GET" && path.endsWith(`/control/tasks/${COMMAND_RUN_TASK_ID}`)) {
            await fulfillJson(
                route,
                createRuntimeFlowRead({
                    task_id: COMMAND_RUN_TASK_ID,
                    task_title: "Refresh runtime route copy",
                }),
            );
            return;
        }

        if (request.method() === "GET" && path.endsWith("/log")) {
            const logRunId = path.split("/").at(-2) ?? "run-failed";
            await fulfillJson(route, createCommandRunLogRead(logRunId));
            return;
        }

        if (request.method() === "GET" && path.includes("/command-runs/")) {
            await fulfillJson(
                route,
                details[runId ?? "run-failed"] ?? createCommandRunDetail(runId ?? "run-failed"),
            );
            return;
        }

        if (request.method() === "POST" && path.includes("/command-runs/")) {
            if (options.cancelSucceeds === true) {
                await fulfillJson(route, {
                    run: {
                        ...createCommandRunPageList().items[0],
                        run_id: runId ?? "run-queued",
                        state: "cancellation_requested",
                        summary: "Cancel request accepted.",
                    },
                    task_id: COMMAND_RUN_TASK_ID,
                } satisfies components["schemas"]["CommandRunCancelResponse"]);
                return;
            }

            await route.fulfill({
                body: JSON.stringify(
                    createOperationFailureBody({
                        code: "illegal_state",
                        retryable: true,
                        summary: "The command run was already updated by the controller.",
                        suggested_next_step: "Reread command-run truth before retrying cancel.",
                    }),
                ),
                contentType: "application/json",
                status: 409,
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
