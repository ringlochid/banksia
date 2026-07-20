import { mkdirSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import type { ConsoleMockScenario } from "../../src/mocks/handlers";
import {
    TASK_DETAIL_TASK_ID,
    createLongTaskDetailEventRecords,
    createTaskDetailMockScenario,
} from "../fixtures/task-detail";

const SCREENSHOT_DIR =
    "/home/ubuntu/leo/projects/autoclaw/tmp/autoclaw-frontend/full-delivery-design-parity/02-task-detail/screenshots";

test("renders the API-backed Task Detail control room at desktop width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");

    await mockTaskDetail(page, createTaskDetailMockScenario());
    mkdirSync(SCREENSHOT_DIR, { recursive: true });

    await page.goto(`/tasks/${TASK_DETAIL_TASK_ID}`);

    await expect(
        page.getByRole("heading", { level: 1, name: "Refresh runtime route copy" }),
    ).toBeVisible();
    await expect(page.getByText("Execution graph")).toBeVisible();
    await expect(page.getByText("Events")).toBeVisible();
    await expect(page.getByText("Approve the last copy trim")).toHaveCount(0);
    await expect(page.getByText("Verify command-run runner behavior.")).toHaveCount(0);
    await expect(page.getByText("Task cancelled")).toBeVisible();
    await expect(page.getByText("Provider event normalized")).toHaveCount(0);
    await expect(page.getByText("Provider resolution recorded")).toHaveCount(0);
    await expect(page.getByText("Dispatch opened")).toBeVisible();
    await expectNoDocumentOverflow(page);

    const accessibilityScanResults = await new AxeBuilder({ page })
        .exclude('a[aria-label="Fixture gallery"]')
        .analyze();
    expect(accessibilityScanResults.violations).toEqual([]);

    await page.screenshot({
        fullPage: true,
        path: `${SCREENSHOT_DIR}/task-detail-desktop.png`,
    });

    const initialZoom = await readGraphZoom(page);
    expect(initialZoom).toBeGreaterThanOrEqual(340);
    expect(initialZoom).toBeLessThanOrEqual(500);
    await expectGraphWheelZoomWithoutPageScroll(page, initialZoom);
    await page.getByRole("button", { name: "Reset graph zoom" }).click();
    const resetZoom = await readGraphZoom(page);
    expect(resetZoom).toBeGreaterThanOrEqual(initialZoom);
    expect(resetZoom).toBeLessThanOrEqual(500);
    for (let index = 0; index < 16; index += 1) {
        await page.getByRole("button", { name: "Zoom in graph" }).click();
    }
    expect(await readGraphZoom(page)).toBe(500);
    await page.getByRole("button", { name: "Reset graph zoom" }).click();
    const refitZoom = await readGraphZoom(page);
    expect(refitZoom).toBeGreaterThanOrEqual(initialZoom);
    expect(refitZoom).toBeLessThanOrEqual(500);
    for (let index = 0; index < 18; index += 1) {
        await page.getByRole("button", { name: "Zoom out graph" }).click();
    }
    expect(await readGraphZoom(page)).toBeLessThan(100);
    const transformBeforeDrag = await readGraphTransform(page);
    const graphBox = await page.getByLabel("Execution graph").boundingBox();
    expect(graphBox).not.toBeNull();
    if (graphBox !== null) {
        await page.mouse.move(
            graphBox.x + graphBox.width * 0.24,
            graphBox.y + graphBox.height * 0.24,
        );
        await page.mouse.down();
        await page.mouse.move(
            graphBox.x + graphBox.width * 0.24 + 160,
            graphBox.y + graphBox.height * 0.24 + 80,
            {
                steps: 8,
            },
        );
        await page.mouse.up();
    }
    expect(await readGraphTransform(page)).not.toBe(transformBeforeDrag);
    await page.getByRole("button", { name: "Reset graph zoom" }).click();

    await page
        .getByRole("button", { name: /Checkpoint recorded/i })
        .first()
        .click();
    const openDetailButton = page.getByRole("button", { name: "Open detail" });
    await openDetailButton.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Close node detail" })).toBeFocused();
    await expect(
        dialog.getByRole("heading", { level: 2, name: "Runtime page contract" }),
    ).toBeVisible();
    await expect(dialog.getByText("Approval is needed for the last copy trim.")).toBeVisible();
    await expect(dialog.getByText("Verify command-run runner behavior.")).toBeVisible();
    await page.screenshot({
        fullPage: true,
        path: `${SCREENSHOT_DIR}/task-detail-modal-desktop.png`,
    });
    await dialog.getByRole("tab", { name: "Trace" }).click();
    await expect(dialog.getByRole("figure", { name: "Trace" }).getByLabel("Trace")).toContainText(
        "checkpoint_recorded",
    );

    await page.screenshot({
        fullPage: true,
        path: `${SCREENSHOT_DIR}/task-detail-modal-trace-desktop.png`,
    });

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(openDetailButton).toBeFocused();
});

test("keeps the Task Detail graph and event lane responsive at mobile width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-chrome", "mobile proof is captured once");

    await mockTaskDetail(
        page,
        createTaskDetailMockScenario({
            events: createLongTaskDetailEventRecords(),
        }),
    );
    mkdirSync(SCREENSHOT_DIR, { recursive: true });

    await page.goto(`/tasks/${TASK_DETAIL_TASK_ID}`);

    await expect(
        page.getByRole("heading", { level: 1, name: "Refresh runtime route copy" }),
    ).toBeVisible();
    await expect(page.getByLabel("Zoom in graph")).toBeVisible();
    await expect(page.getByRole("button", { name: /task_detail_build active/i })).toBeVisible();
    await expect(
        page.getByRole("button", { name: /Dispatch opened worker node 17/i }),
    ).toBeVisible();
    await expectNoDocumentOverflow(page);

    await page.screenshot({
        fullPage: true,
        path: `${SCREENSHOT_DIR}/task-detail-mobile.png`,
    });
});

async function mockTaskDetail(page: Page, scenario: ConsoleMockScenario): Promise<void> {
    await page.route("**/control/tasks/**", async (route) => {
        const request = route.request();
        const requestUrl = new URL(request.url());
        const path = requestUrl.pathname;

        if (request.method() !== "GET") {
            await fulfillJson(route, scenario.taskRead);
            return;
        }

        if (path.endsWith(`/control/tasks/${TASK_DETAIL_TASK_ID}`)) {
            await fulfillJson(route, scenario.taskRead);
            return;
        }

        if (path.endsWith(`/control/tasks/${TASK_DETAIL_TASK_ID}/snapshot`)) {
            await fulfillJson(route, scenario.snapshot);
            return;
        }

        if (path.endsWith(`/control/tasks/${TASK_DETAIL_TASK_ID}/trace`)) {
            await fulfillJson(route, scenario.trace);
            return;
        }

        if (path.endsWith(`/control/tasks/${TASK_DETAIL_TASK_ID}/events`)) {
            await fulfillJson(route, scenario.taskEvents);
            return;
        }

        if (path.endsWith(`/control/tasks/${TASK_DETAIL_TASK_ID}/events/stream`)) {
            await route.fulfill({
                body: streamBodyForCursor(scenario, requestUrl.searchParams.get("cursor")),
                contentType: "text/event-stream",
            });
            return;
        }

        if (path.endsWith(`/control/tasks/${TASK_DETAIL_TASK_ID}/human-requests`)) {
            await fulfillJson(route, scenario.humanRequestList);
            return;
        }

        if (path.endsWith(`/control/tasks/${TASK_DETAIL_TASK_ID}/command-runs`)) {
            await fulfillJson(route, scenario.commandRunList);
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

function streamBodyForCursor(scenario: ConsoleMockScenario, cursor: string | null): string {
    const chunks =
        cursor === null
            ? scenario.taskEventStream.chunks
            : (scenario.taskEventStream.chunksByCursor[cursor] ?? scenario.taskEventStream.chunks);

    return chunks.join("");
}

async function expectNoDocumentOverflow(page: Page): Promise<void> {
    const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );

    expect(overflow).toBeLessThanOrEqual(1);
}

async function readGraphZoom(page: Page): Promise<number> {
    const graphSectionText = await page
        .locator("section")
        .filter({ hasText: "Execution graph" })
        .first()
        .innerText();
    const zoomMatch = /(\d+)%/.exec(graphSectionText);
    expect(zoomMatch).not.toBeNull();
    return Number(zoomMatch?.[1] ?? 0);
}

async function expectGraphWheelZoomWithoutPageScroll(
    page: Page,
    initialZoom: number,
): Promise<void> {
    const graph = page.getByLabel("Execution graph");
    await graph.scrollIntoViewIfNeeded();
    await page.evaluate(() => {
        window.scrollBy(0, 64);
    });
    const graphBox = await graph.boundingBox();
    expect(graphBox).not.toBeNull();
    if (graphBox === null) {
        return;
    }

    const beforeScrollY = await page.evaluate(() => window.scrollY);
    await page.mouse.move(graphBox.x + graphBox.width / 2, graphBox.y + graphBox.height / 2);
    await page.mouse.wheel(0, 240);
    await expect.poll(async () => readGraphZoom(page)).not.toBe(initialZoom);
    const afterScrollY = await page.evaluate(() => window.scrollY);
    expect(afterScrollY).toBe(beforeScrollY);
}

async function readGraphTransform(page: Page): Promise<string | null> {
    return page
        .locator('svg[aria-label="Execution graph"] > g[transform]')
        .first()
        .getAttribute("transform");
}
