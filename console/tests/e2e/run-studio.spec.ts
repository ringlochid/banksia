import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { taskFixture } from "../fixtures/runs";

test("a teammate can be selected to inspect their current work", async ({
    page,
}, testInfo) => {
    const task = taskFixture();
    await page.route(`**/api/tasks/${task.id}`, async (route) => {
        await route.fulfill({ json: task });
    });
    await page.route(
        `**/api/tasks/${task.id}/activities/stream*`,
        async (route) => {
            await route.fulfill({ body: "", contentType: "text/event-stream" });
        },
    );

    await page.goto(`/runs/${task.id}`);

    const lead = page.getByRole("button", { name: /Delivery lead.*Waiting/ });
    const reviewer = page.getByRole("button", {
        name: /Independent reviewer.*Done/,
    });
    await expect(lead).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Compare candidates")).toBeVisible();

    await reviewer.click();

    await expect(reviewer).toHaveAttribute("aria-pressed", "true");
    await expect(
        page.getByText("Independent review is complete."),
    ).toBeVisible();
    await expect(
        page.getByText("Inspect the supporting evidence"),
    ).toBeVisible();
    await expect(
        page.getByText(".oms/t_7m4k2d9x/artifacts/review.md"),
    ).toBeVisible();
    const accessibility = await new AxeBuilder({ page })
        .include(".run-studio__sidebar")
        .analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({
        fullPage: true,
        path: testInfo.outputPath("run-studio-member-context.png"),
    });
});

test("a working Member can be steered from the context panel", async ({
    page,
}, testInfo) => {
    const initial = taskFixture();
    const message = "Re-read AGENTS.md, then keep the repair narrowly scoped.";
    const task = taskFixture({
        status: "working",
        human_requests: [],
        human_request_count: 0,
        attention: [],
        team: {
            ...initial.team,
            state: "working",
            latest_update: {
                summary: "The implementation is in progress.",
                occurred_at: "2026-08-09T01:55:00Z",
                files: [],
            },
            steer_action: {
                id: "action-steer-lead",
                kind: "steer",
                label: "Steer",
                href: `/api/tasks/${initial.id}/members/${initial.team.id}/steers`,
                input_schema: null,
                confirmation: {
                    required: false,
                    title: "Steer this Member",
                    consequence: "The message updates current work.",
                },
            },
        },
    });
    await page.route(`**/api/tasks/${task.id}`, async (route) => {
        await route.fulfill({ json: task });
    });
    await page.route(
        `**/api/tasks/${task.id}/members/${task.team.id}/steers`,
        async (route) => {
            await route.fulfill({
                json: {
                    receipt_id: "receipt-steer",
                    status: "delivered",
                    status_message: "The Member was steered.",
                    task: {
                        ...task,
                        activities: [
                            ...task.activities,
                            {
                                id: "activity-steered",
                                kind: "member_steered",
                                occurred_at: "2026-08-09T02:00:00Z",
                                title: "Member steered",
                                summary: message,
                                member: {
                                    id: task.team.id,
                                    name: task.team.name,
                                },
                                outcome: null,
                                files: [],
                                action: null,
                            },
                        ],
                    },
                },
            });
        },
    );
    await page.route(
        `**/api/tasks/${task.id}/activities/stream*`,
        async (route) => {
            await route.fulfill({ body: "", contentType: "text/event-stream" });
        },
    );

    await page.goto(`/runs/${task.id}`);

    const button = page.getByRole("button", { name: "Steer" });
    await expect(button).toBeVisible();
    const buttonBox = await button.boundingBox();
    const updateBox = await page.getByText("Latest update").boundingBox();
    expect(buttonBox?.y).toBeLessThan(updateBox?.y ?? 0);
    await button.click();

    const dialog = page.getByRole("dialog", { name: "Steer Delivery lead" });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Message").fill(message);
    const accessibility = await new AxeBuilder({ page })
        .include(".ui-dialog__content")
        .analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({
        fullPage: true,
        path: testInfo.outputPath("run-studio-steer-modal.png"),
    });
    await dialog.getByRole("button", { name: "Steer" }).click();

    await expect(page.getByText("Member steered")).toBeVisible();
    await expect(page.getByText(message)).toBeVisible();
});
