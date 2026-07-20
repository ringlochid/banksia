import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";

import type { components } from "../../src/api/generated/openapi";
import { createRuntimeFlowRead } from "../fixtures/console-api";
import {
    HUMAN_REQUEST_TASK_ID,
    createHumanRequestPageList,
    createHumanRequestResolveResponse,
} from "../fixtures/human-requests";

const SCREENSHOT_DIR =
    "/home/ubuntu/leo/projects/autoclaw/tmp/autoclaw-frontend/full-delivery-design-parity/03-human-requests/screenshots";

test("renders and resolves the Human Requests page at desktop width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");

    const requestBodies = await mockHumanRequests(page);
    await page.setViewportSize({ height: 1000, width: 1440 });

    await page.goto(`/tasks/${HUMAN_REQUEST_TASK_ID}/human-requests`);

    await expect(
        page.getByRole("heading", { level: 1, name: "Refresh runtime route copy" }),
    ).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(
        "Refresh runtime route copy",
    );
    await expect(page.getByText("Human Requests").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Choose due handling" }).last()).toBeVisible();
    await expect(page.getByText("Approve generated file writes")).toBeVisible();
    await expect(page.getByText("Provide handoff fields")).toBeVisible();
    await expect(page.getByText("Review validation result")).toBeVisible();
    await expect(page.getByText("Validation evidence accepted")).toBeVisible();
    await expectNoDocumentOverflow(page);

    const accessibilityScanResults = await new AxeBuilder({ page })
        .exclude('a[aria-label="Fixture gallery"]')
        .analyze();
    expect(accessibilityScanResults.violations).toEqual([]);

    await page.getByLabel(/Use due fallback/).check();
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel(/Current request only/).check();
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel(/Answer only/).check();
    await page.getByRole("button", { name: "Previous" }).click();
    await page.getByRole("button", { name: "Previous" }).click();

    await expect(page.getByLabel(/Use due fallback/)).toBeChecked();
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByLabel(/Current request only/)).toBeChecked();
    await page.getByRole("button", { name: "Previous" }).click();
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    await page.screenshot({
        fullPage: true,
        path: `${SCREENSHOT_DIR}/app-desktop-default.png`,
        scale: "css",
    });

    await page.getByRole("button", { exact: true, name: "Resolve" }).click();
    await expect(page.getByText("Resolved request")).toBeVisible();
    await expect.poll(() => requestBodies.length).toBe(1);
    expect(Object.keys(requestBodies[0]?.item_responses ?? {})).toEqual([
        "due_handling",
        "next_scope",
        "next_context",
    ]);

    await page.getByText("Approve generated file writes").click();
    await expect(page.getByLabel("Reject for now")).toBeVisible();
    await page.getByText("Provide handoff fields").click();
    await page.getByRole("button", { exact: true, name: "Resolve" }).click();
    await expect(page.getByText("Target node is required.")).toBeVisible();
    await page.getByLabel("Target node").fill("release_gate");
    await page.getByLabel("Expected output").fill("validated artifact list");
    await page.getByLabel("Constraint").fill("Use controller-owned request data only.");
    await page.getByRole("button", { exact: true, name: "Resolve" }).click();
    await expect.poll(() => requestBodies.length).toBe(2);
    expect(requestBodies[1]?.item_responses.handoff_payload).toEqual({
        constraint: "Use controller-owned request data only.",
        expected_output: "validated artifact list",
        target_node: "release_gate",
    });
    await expect(page.getByText(/"target_node": "release_gate"/)).toBeVisible();
    await expect(page.getByText(/"expected_output": "validated artifact list"/)).toBeVisible();

    await page.getByText("Due window elapsed").click();
    await expect(page.getByText("Timed out request")).toBeVisible();
    await page.getByText("Write approval withdrawn").click();
    await expect(page.getByText("Cancelled request")).toBeVisible();

    const openTaskDetail = page.getByRole("link", { name: "Open task detail" });
    await openTaskDetail.focus();
    await expect(openTaskDetail).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/tasks/${HUMAN_REQUEST_TASK_ID}$`));
});

test("keeps Human Requests responsive at mobile width", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-chrome", "mobile proof is captured once");

    await mockHumanRequests(page);
    await page.setViewportSize({ height: 900, width: 390 });

    await page.goto(`/tasks/${HUMAN_REQUEST_TASK_ID}/human-requests`);

    await expect(page.getByRole("heading", { name: "Choose due handling" }).last()).toBeVisible();
    await expect(page.getByRole("button", { name: "Next" })).toBeVisible();
    await page.getByLabel(/Use due fallback/).check();
    await page.getByRole("button", { name: "Next" }).focus();
    await expect(page.getByRole("button", { name: "Next" })).toBeFocused();
    const responseOptions = page.getByRole("group", { name: "Response options" });
    await expectTopAfter(responseOptions, page.getByRole("link", { name: "Open task detail" }));
    await expectTopAfter(
        responseOptions,
        page.getByRole("button", { exact: true, name: "Resolve" }),
    );
    await expectTopAfter(
        page.getByRole("button", { exact: true, name: "Resolve" }),
        page.getByText("Other requests"),
    );
    await expectNoDocumentOverflow(page);

    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    await page.screenshot({
        fullPage: true,
        path: `${SCREENSHOT_DIR}/app-narrow-default.png`,
        scale: "css",
    });
});

type HumanRequestResolveRequest = components["schemas"]["HumanRequestResolveRequest"];

async function mockHumanRequests(page: Page): Promise<HumanRequestResolveRequest[]> {
    const list = createHumanRequestPageList();
    const requestBodies: HumanRequestResolveRequest[] = [];
    mkdirSync(SCREENSHOT_DIR, { recursive: true });

    await page.route("**/control/tasks/**", async (route) => {
        const request = route.request();
        const requestUrl = new URL(request.url());
        const path = requestUrl.pathname;

        if (
            request.method() === "GET" &&
            path.endsWith(`/${HUMAN_REQUEST_TASK_ID}/human-requests`)
        ) {
            await fulfillJson(route, list);
            return;
        }

        if (request.method() === "GET" && path.endsWith(`/${HUMAN_REQUEST_TASK_ID}/snapshot`)) {
            await fulfillJson(route, {
                current_paths: [],
                flow: createRuntimeFlowRead({
                    task_id: HUMAN_REQUEST_TASK_ID,
                    task_title: "Refresh runtime route copy",
                }),
                stream_head_event_id: null,
                top_actionable_items: [],
            } satisfies components["schemas"]["OperatorFlowSnapshotResponse"]);
            return;
        }

        if (request.method() === "GET" && path.endsWith(`/${HUMAN_REQUEST_TASK_ID}`)) {
            await fulfillJson(
                route,
                createRuntimeFlowRead({
                    task_id: HUMAN_REQUEST_TASK_ID,
                    task_title: "Refresh runtime route copy",
                }),
            );
            return;
        }

        if (request.method() === "POST" && path.includes("/human-requests/")) {
            const requestBody = JSON.parse(
                request.postData() ?? '{"item_responses":{}}',
            ) as (typeof requestBodies)[number];
            requestBodies.push(requestBody);
            const requestId = path.split("/").at(-2);
            const requestRead = list.items.find((item) => item.request.request_id === requestId);
            await fulfillJson(
                route,
                createHumanRequestResolveResponse(
                    requestRead?.request ?? list.items[0].request,
                    requestBody.item_responses,
                ),
            );
            return;
        }

        await route.fulfill({ status: 404 });
    });

    return requestBodies;
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

async function expectTopAfter(previous: Locator, next: Locator): Promise<void> {
    const previousBox = await previous.boundingBox();
    const nextBox = await next.boundingBox();

    expect(previousBox).not.toBeNull();
    expect(nextBox).not.toBeNull();

    if (previousBox === null || nextBox === null) {
        return;
    }

    expect(nextBox.y).toBeGreaterThanOrEqual(previousBox.y + previousBox.height - 1);
}
