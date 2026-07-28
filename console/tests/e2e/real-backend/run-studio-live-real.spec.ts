/// <reference types="node" />

import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import {
    expect,
    test,
    type APIRequestContext,
    type Page,
} from "@playwright/test";

import type {
    ProductAction,
    TaskStartReceipt,
    TaskView,
} from "../../../src/features/runs/run-api";

const TASK_PROMPT =
    "Inspect the current project and report one concise verification result.";
const REPO_ROOT = path.resolve(process.cwd(), "..");
const SCREENSHOT_ROOT = path.join(
    REPO_ROOT,
    "tmp/codex/execution/wp-13/run-sse",
);

test("reconnects to controller Run truth without manual refresh", async ({
    context,
    page,
    request,
}) => {
    const taskId = await startTask(request);
    const initial = await readTask(request, taskId);
    const pause = requireAction(initial, "pause");
    const streamOpened = page.waitForResponse(
        (response) =>
            response.status() === 200 &&
            new URL(response.url()).pathname.endsWith("/activities/stream"),
    );

    await page.goto(`/runs/${encodeURIComponent(taskId)}`);
    await expect(
        page.getByRole("heading", { level: 1, name: TASK_PROMPT }),
    ).toBeVisible();
    await streamOpened;

    await context.setOffline(true);
    await expect(
        page.getByText("Live updates are delayed.", { exact: false }),
    ).toBeVisible({ timeout: 8_000 });
    await captureScreenshot(page, "01-live-delayed-desktop.png");

    const paused = await request.post(pause.href, {
        data: { confirmed: true },
    });
    expect(paused.status()).toBe(200);
    await context.setOffline(false);

    await expect(page.locator(".run-status")).toHaveText("Paused", {
        timeout: 15_000,
    });
    await expect(
        page.getByText("Live updates are delayed.", { exact: false }),
    ).toHaveCount(0);
    await expect(page.getByText("Run paused", { exact: true })).toHaveCount(1);
    await expect(
        page.getByRole("button", { name: "Refresh Run" }),
    ).toBeVisible();
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations).toEqual([]);
    await captureScreenshot(page, "02-live-recovered-desktop.png");
});

async function startTask(request: APIRequestContext): Promise<string> {
    const response = await request.post("/api/tasks", {
        data: {
            workflow: "incident-investigation-and-recovery",
            prompt: TASK_PROMPT,
            workspace: REPO_ROOT,
        },
    });
    expect(response.status()).toBe(202);
    return ((await response.json()) as TaskStartReceipt).task_id;
}

async function readTask(
    request: APIRequestContext,
    taskId: string,
): Promise<TaskView> {
    const response = await request.get(
        `/api/tasks/${encodeURIComponent(taskId)}`,
    );
    expect(response.status()).toBe(200);
    return (await response.json()) as TaskView;
}

function requireAction(
    task: TaskView,
    kind: ProductAction["kind"],
): ProductAction {
    const action = task.actions.find((candidate) => candidate.kind === kind);
    if (action === undefined) {
        throw new Error(`Expected a ${kind} action for the active Run`);
    }
    return action;
}

async function captureScreenshot(page: Page, filename: string): Promise<void> {
    await mkdir(SCREENSHOT_ROOT, { recursive: true });
    await page.screenshot({
        fullPage: true,
        path: path.join(SCREENSHOT_ROOT, filename),
    });
}
