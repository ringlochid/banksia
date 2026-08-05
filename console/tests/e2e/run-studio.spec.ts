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
        page.getByText(".banksia/t_7m4k2d9x/artifacts/review.md"),
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
