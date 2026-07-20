import { expect, test, type Page } from "@playwright/test";

test("routes root traffic into the task shell", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/tasks$/);
    await expect(page.getByRole("main", { name: "AutoClaw Console" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Tasks" })).toBeVisible();
});

test("keeps primary navigation on real product routes", async ({ page }) => {
    await page.goto("/tasks");
    const primaryNav = page.getByRole("navigation", { name: "Primary" });

    await primaryNav.getByRole("link", { name: "Definitions" }).click();
    await expect(page).toHaveURL(/\/definitions$/);
    await expect(page.getByRole("heading", { level: 1, name: "Definitions" })).toBeVisible();

    await primaryNav.getByRole("link", { name: "Definition Editor" }).click();
    await expect(page).toHaveURL(/\/definitions\/editor$/);
    await expect(page.getByRole("heading", { level: 1, name: "Definition Editor" })).toBeVisible();

    await primaryNav.getByRole("link", { name: "Task Start" }).click();
    await expect(page).toHaveURL(/\/task-start$/);
    await expect(page.getByRole("heading", { level: 1, name: "Task Start" })).toBeVisible();
});

test("keeps task-scoped breadcrumbs below Tasks", async ({ page }) => {
    await page.goto("/tasks/runtime-copy-refresh/human-requests");

    const breadcrumb = page.getByRole("navigation", { name: "Breadcrumb" });
    await expect(breadcrumb).toContainText("Tasks");
    await expect(breadcrumb).toContainText("runtime-copy-refresh");
    await expect(breadcrumb).toContainText("Human Requests");
    await expect(breadcrumb.getByText("\u203a")).toHaveCount(2);
    await expect(
        page.getByRole("heading", { level: 1, name: "runtime-copy-refresh" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { exact: true, name: "Task Detail" })).toBeVisible();
    await expect(page.getByRole("link", { exact: true, name: "Human Requests" })).toBeVisible();
    await expect(page.getByRole("link", { exact: true, name: "Command Runs" })).toBeVisible();
});

test("keeps authoring breadcrumbs separate from selected task routes", async ({ page }) => {
    await page.goto("/definitions/editor");

    const breadcrumb = page.getByRole("navigation", { name: "Breadcrumb" });
    await expect(breadcrumb).toContainText("Definitions");
    await expect(breadcrumb).toContainText("Definition Editor");
    await expect(page.getByText("Draft editing")).toBeVisible();
    await expect(page.getByText("Task Control Suite")).toHaveCount(0);
});

test("keeps the shell keyboard path visible", async ({ page }) => {
    await page.goto("/tasks");

    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: "Skip to main content" });
    await expect(skipLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main", { name: "AutoClaw Console" })).toBeFocused();

    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Search")).toBeFocused();
});

test("honors the reduced-motion preference in the shared shell", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/tasks");

    const motionDurations = await page.getByRole("link", { name: "Tasks" }).evaluate((element) => {
        const style = window.getComputedStyle(element);
        return {
            animation: Number.parseFloat(style.animationDuration),
            transition: Number.parseFloat(style.transitionDuration),
        };
    });

    expect(motionDurations.animation).toBeLessThanOrEqual(0.001);
    expect(motionDurations.transition).toBeLessThanOrEqual(0.001);
});

test("avoids document-level horizontal overflow on narrow shell routes", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });

    for (const route of [
        "/tasks",
        "/tasks/runtime-copy-refresh",
        "/tasks/runtime-copy-refresh/human-requests",
        "/definitions",
        "/definitions/editor",
        "/task-start",
        "/fixtures",
    ]) {
        await page.goto(route);
        await expect(page.getByRole("main", { name: "AutoClaw Console" })).toBeVisible();

        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );

        expect(overflow).toBeLessThanOrEqual(1);
    }
});

test("keeps release page frames aligned to the same shell width", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1600 });

    const routes = [
        "/tasks",
        "/tasks/runtime-copy-refresh",
        "/tasks/runtime-copy-refresh/command-runs",
        "/definitions",
        "/definitions/editor",
        "/task-start",
    ] as const;

    const widths: number[] = [];
    for (const route of routes) {
        await page.goto(route);
        await expect(page.getByRole("main", { name: "AutoClaw Console" })).toBeVisible();
        widths.push(await pageFrameWidth(page));
    }

    expect(Math.max(...widths) - Math.min(...widths)).toBeLessThanOrEqual(1);
    expect(widths[0]).toBeGreaterThan(900);
});

test("lets release pages grow in document flow instead of clipping the shell", async ({ page }) => {
    await page.setViewportSize({ height: 720, width: 1280 });

    for (const route of [
        "/tasks",
        "/tasks/runtime-copy-refresh",
        "/tasks/runtime-copy-refresh/human-requests",
        "/tasks/runtime-copy-refresh/command-runs",
        "/definitions",
        "/definitions/editor",
        "/task-start",
    ]) {
        await page.goto(route);
        await expect(page.getByRole("main", { name: "AutoClaw Console" })).toBeVisible();

        const metrics = await documentFlowMetrics(page);
        expect(metrics.rootOverflowY).not.toBe("hidden");
        expect(metrics.bodyOverflowY).not.toBe("hidden");
        expect(metrics.mainOverflowY).toBe("visible");
        expect(metrics.mainScrollTop).toBe(0);
        expect(metrics.horizontalOverflow).toBeLessThanOrEqual(1);
    }

    await page.goto("/task-start");
    await expect(page.getByRole("heading", { level: 1, name: "Task Start" })).toBeVisible();
    const taskStartMetrics = await documentFlowMetrics(page);
    expect(taskStartMetrics.frameBottom).toBeGreaterThan(taskStartMetrics.viewportHeight);
    expect(taskStartMetrics.documentScrollHeight).toBeGreaterThan(
        taskStartMetrics.documentClientHeight,
    );
});

test("does not expose internal fixture gallery chrome on release shell routes", async ({
    page,
}) => {
    for (const route of [
        "/tasks",
        "/tasks/runtime-copy-refresh",
        "/tasks/runtime-copy-refresh/human-requests",
        "/tasks/runtime-copy-refresh/command-runs",
        "/definitions",
        "/definitions/editor",
        "/task-start",
    ]) {
        await page.goto(route);
        await expect(page.getByRole("main", { name: "AutoClaw Console" })).toBeVisible();
        await expect(page.getByRole("link", { name: "Fixture gallery" })).toHaveCount(0);
    }
});

test("renders the internal fixture gallery route", async ({ page }) => {
    await page.goto("/fixtures");

    await expect(page.getByRole("heading", { name: "Fixture Gallery" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Primary" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
    const overviewTab = page.getByRole("tab", { name: "Overview" });
    await expect(overviewTab).toBeVisible();

    await overviewTab.focus();
    await page.keyboard.press("ArrowRight");

    const checkpointTab = page.getByRole("tab", { name: "Checkpoint" });
    await expect(checkpointTab).toBeFocused();
    await expect(checkpointTab).toHaveAttribute("aria-selected", "true");
});

async function pageFrameWidth(page: Page): Promise<number> {
    const frame = page.locator("main > section").first();
    await expect(frame).toBeVisible();
    const box = await frame.boundingBox();
    expect(box).not.toBeNull();
    return Math.round(box?.width ?? 0);
}

async function documentFlowMetrics(page: Page): Promise<{
    readonly bodyOverflowY: string;
    readonly documentClientHeight: number;
    readonly documentScrollHeight: number;
    readonly frameBottom: number;
    readonly horizontalOverflow: number;
    readonly mainOverflowY: string | null;
    readonly mainScrollTop: number;
    readonly rootOverflowY: string;
    readonly viewportHeight: number;
}> {
    return page.evaluate(() => {
        const root = document.documentElement;
        const main = document.querySelector("main");
        const frame = document.querySelector("main > section");
        const bodyStyle = window.getComputedStyle(document.body);
        const rootStyle = window.getComputedStyle(root);
        const mainStyle = main === null ? null : window.getComputedStyle(main);
        if (main !== null) {
            main.scrollTop = main.scrollHeight;
        }

        return {
            bodyOverflowY: bodyStyle.overflowY,
            documentClientHeight: root.clientHeight,
            documentScrollHeight: root.scrollHeight,
            frameBottom: frame?.getBoundingClientRect().bottom ?? 0,
            horizontalOverflow: root.scrollWidth - root.clientWidth,
            mainOverflowY: mainStyle?.overflowY ?? null,
            mainScrollTop: main?.scrollTop ?? 0,
            rootOverflowY: rootStyle.overflowY,
            viewportHeight: window.innerHeight,
        };
    });
}
