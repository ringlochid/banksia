/// <reference types="node" />

import { mkdirSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import type { components } from "../../src/api/generated/openapi";
import {
    DEFINITIONS_SCREENSHOT_DIR,
    POLICY_KEY,
    ROLE_KEY,
    SECOND_ROLE_KEY,
    WORKFLOW_KEY,
    createDefinitionDetailMap,
    createDefinitionSummaryList,
    createDefinitionVersions,
    createDefinitionVersionsMap,
    createPolicyDefinitionRows,
    createRoleDefinitionRows,
    createWorkflowDefinitionRows,
} from "../fixtures/definitions";

test("renders Definitions browse detail, versions, focus, and accessibility at desktop width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");
    await page.setViewportSize({ height: 720, width: 1280 });

    await mockDefinitions(page);

    await page.goto("/definitions");

    await expect(page.getByRole("heading", { level: 1, name: "Definitions" })).toBeVisible();
    await expect(definitionRow(page, ROLE_KEY)).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: ROLE_KEY })).toBeVisible();
    await expect(page.getByText("Revision 4").first()).toBeVisible();
    const definitionRows = page.getByRole("list", { name: "Definition rows" }).getByRole("button");
    await expect(definitionRows).toHaveCount(4);
    await expect(page.getByText("4 roles loaded.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Load more" })).toBeVisible();
    await expectNoDocumentOverflow(page);
    await expectDocumentOwnsVerticalOverflow(page);

    mkdirSync(DEFINITIONS_SCREENSHOT_DIR, { recursive: true });
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    await page.screenshot({
        fullPage: true,
        path: `${DEFINITIONS_SCREENSHOT_DIR}/definitions-desktop.png`,
    });

    const accessibilityScanResults = await new AxeBuilder({ page })
        .exclude('a[aria-label="Fixture gallery"]')
        .analyze();
    expect(accessibilityScanResults.violations).toEqual([]);

    await page.getByLabel("Allowed node kind").selectOption("worker");
    await expect(definitionRow(page, SECOND_ROLE_KEY)).toBeVisible();

    await page.getByRole("button", { name: "Workflows" }).click();
    await expect(definitionRow(page, WORKFLOW_KEY)).toBeVisible();
    await expect(page.getByText("Structure")).toBeVisible();
    await expect(page.getByText("First-level nodes")).toBeVisible();
    await expect(page.getByText("implementation_loop")).toBeVisible();
    await expect(page.getByText("Provider: machine default").first()).toBeVisible();
    await expect(page.getByText("Stored root role")).toHaveCount(0);
    await expect(page.getByText("Root tree")).toHaveCount(0);
    await expect(page.getByLabel("Allowed node kind")).toHaveCount(0);
    await expect(page.getByLabel("Applies to")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Task Start" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Create/update draft" })).toHaveCount(0);
    await expectDefinitionsUsesSingleDocumentScroll(page);
    const editDraftLink = page.getByRole("link", { name: "Edit in draft" });
    const editDraftHref = await editDraftLink.getAttribute("href");
    expect(editDraftHref).toContain("kind=workflow");
    expect(editDraftHref).toContain("key=staged-delivery-release");

    const revisionButton = page.getByRole("button", { name: "Revision 5" });
    await revisionButton.click();
    const versionsDialog = page.getByRole("dialog", { name: "Versions" });
    const versionsList = versionsDialog.getByRole("list", { name: "Definition versions" });
    await expect(versionsList.getByText("Revision 5")).toBeVisible();
    await expect(versionsList.getByText("Revision 4")).toBeVisible();
    await expect(versionsDialog.getByText("Current registry pointer: revision 5.")).toBeVisible();
    await expect(versionsList.getByText("Current")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(revisionButton).toBeFocused();

    await definitionRow(page, "bounded-change").click();
    await expect(page.getByText("Provider: OpenClaw (explicit)")).toBeVisible();
    await expect(page.getByText("experimental")).toBeVisible();
    await expect(page.getByText("Provider: Codex (explicit)")).toBeVisible();

    const editorLink = page.getByRole("link", { name: "Definition Editor" }).first();
    await editorLink.focus();
    await expect(editorLink).toBeFocused();
});

test("keeps Definitions kind switch, list, detail, and versions usable at mobile width", async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-chrome", "mobile proof is captured once");

    await mockDefinitions(page);

    await page.goto("/definitions");

    await expect(definitionRow(page, ROLE_KEY)).toBeVisible();
    mkdirSync(DEFINITIONS_SCREENSHOT_DIR, { recursive: true });
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    await page.screenshot({
        fullPage: true,
        path: `${DEFINITIONS_SCREENSHOT_DIR}/definitions-mobile.png`,
    });

    await page.getByRole("button", { name: "Policies" }).click();
    await expect(definitionRow(page, POLICY_KEY)).toBeVisible();
    await expect(page.getByText("Budget", { exact: true })).toBeVisible();
    await expect(page.getByText("No controller budget limit")).toBeVisible();
    await expect(page.getByText(/not reported/)).toHaveCount(0);
    await definitionRow(page, "standard-parent-planning").click();
    await expect(page.getByText("4 child assignments")).toBeVisible();
    await expect(page.getByText(/not reported/)).toHaveCount(0);
    await definitionRow(page, "standard-worker").click();
    await expect(page.getByText("1 retry")).toBeVisible();
    await expect(page.getByText(/not reported/)).toHaveCount(0);
    await expectNoDocumentOverflow(page);

    const revisionButton = page.getByRole("button", { name: "Revision 2" });
    await revisionButton.click();
    await expect(page.getByText("Single current revision recorded.")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(revisionButton).toBeFocused();
});

test("shows one compact Definitions loading state at 1280px", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop proof is captured once");
    await page.setViewportSize({ height: 720, width: 1280 });

    let releaseRoles!: () => void;
    const rolesDelay = new Promise<void>((resolve) => {
        releaseRoles = resolve;
    });

    await page.route("**/definitions/roles**", async (route) => {
        await rolesDelay;
        await fulfillJson(route, createDefinitionSummaryList("role", [], null));
    });

    await page.goto("/definitions", { waitUntil: "domcontentloaded" });

    const loadingStatus = page.getByRole("status");
    await expect(loadingStatus).toHaveCount(1);
    await expect(loadingStatus).toContainText("Loading roles");
    await expect(page.locator('section[aria-labelledby="definitions-list-heading"]')).toHaveCount(
        0,
    );
    await expect(page.locator(".definition-detail-shell")).toHaveCount(0);

    const loadingMetrics = await loadingStatus.evaluate((panel) => {
        const workspace = panel.parentElement;
        const panelBox = panel.getBoundingClientRect();
        const workspaceBox = workspace?.getBoundingClientRect();
        return {
            horizontalCenterOffset:
                workspaceBox === undefined
                    ? null
                    : Math.abs(
                          panelBox.left +
                              panelBox.width / 2 -
                              (workspaceBox.left + workspaceBox.width / 2),
                      ),
            panelWidth: Math.round(panelBox.width),
            verticalCenterOffset:
                workspaceBox === undefined
                    ? null
                    : Math.abs(
                          panelBox.top +
                              panelBox.height / 2 -
                              (workspaceBox.top + workspaceBox.height / 2),
                      ),
            workspaceWidth: Math.round(workspaceBox?.width ?? 0),
        };
    });

    expect(loadingMetrics.workspaceWidth).toBeGreaterThan(0);
    expect(loadingMetrics.panelWidth).toBeLessThanOrEqual(384);
    expect(loadingMetrics.panelWidth).toBeLessThan(loadingMetrics.workspaceWidth / 2);
    expect(loadingMetrics.horizontalCenterOffset).not.toBeNull();
    expect(loadingMetrics.horizontalCenterOffset ?? 999).toBeLessThanOrEqual(1);
    expect(loadingMetrics.verticalCenterOffset).not.toBeNull();
    expect(loadingMetrics.verticalCenterOffset ?? 999).toBeLessThanOrEqual(1);

    releaseRoles();
});

function definitionRow(page: Page, key: string) {
    return page.getByRole("button", { name: new RegExp(`^${key}\\b`) });
}

async function mockDefinitions(page: Page): Promise<void> {
    const details = createDefinitionDetailMap();
    const versions = createDefinitionVersionsMap();

    await page.route("http://127.0.0.1:18125/definitions/**", async (route) => {
        const request = route.request();
        const requestUrl = new URL(request.url());
        const path = requestUrl.pathname;

        if (request.method() !== "GET") {
            await route.fulfill({ status: 404 });
            return;
        }

        if (path.endsWith("/versions")) {
            const pathParts = path.split("/");
            const kind = (pathParts.at(-3) ?? "role") as components["schemas"]["DefinitionKind"];
            const key = pathParts.at(-2) ?? ROLE_KEY;
            const lookupKey = `${kind}:${key}`;
            await fulfillJson(route, versions[lookupKey] ?? createDefinitionVersions(kind, key));
            return;
        }

        if (path === "/definitions/roles") {
            const roleRowsForPage = createOverflowRoleDefinitionRows();
            const roleRows =
                requestUrl.searchParams.get("allowed_node_kind") === "worker"
                    ? roleRowsForPage.filter((row) => row.allowed_node_kinds?.includes("worker"))
                    : roleRowsForPage;
            await fulfillJson(route, definitionPage("role", roleRows, requestUrl));
            return;
        }

        if (path === "/definitions/policies") {
            await fulfillJson(
                route,
                createDefinitionSummaryList("policy", createPolicyDefinitionRows(), null),
            );
            return;
        }

        if (path === "/definitions/workflows") {
            await fulfillJson(
                route,
                createDefinitionSummaryList("workflow", createWorkflowDefinitionRows(), null),
            );
            return;
        }

        const pathParts = path.split("/");
        const kind = pathParts.at(-2) ?? "role";
        const key = pathParts.at(-1) ?? ROLE_KEY;
        await fulfillJson(route, details[`${kind}:${key}`] ?? details[`role:${ROLE_KEY}`]);
    });
}

function createOverflowRoleDefinitionRows(): readonly components["schemas"]["DefinitionSummaryRead"][] {
    return [
        ...createRoleDefinitionRows(),
        {
            allowed_node_kinds: ["worker"],
            applies_to: null,
            budget_spec: null,
            current_revision_no: 2,
            description: "Ordinary bounded release worker.",
            key: "release_operator",
            labels: ["authoring"],
            title: "release_operator",
            updated_at: "2026-06-05T18:54:00Z",
        },
        {
            allowed_node_kinds: ["worker"],
            applies_to: null,
            budget_spec: null,
            current_revision_no: 1,
            description: "Worker for one bounded product review.",
            key: "product_reviewer",
            labels: ["authoring"],
            title: "product_reviewer",
            updated_at: "2026-06-04T18:54:00Z",
        },
    ];
}

function definitionPage(
    kind: components["schemas"]["DefinitionKind"],
    rows: readonly components["schemas"]["DefinitionSummaryRead"][],
    requestUrl: URL,
): components["schemas"]["DefinitionSummaryListResponse"] {
    const limit = Number(requestUrl.searchParams.get("limit"));
    const pageLimit = Number.isFinite(limit) && limit > 0 ? limit : rows.length;
    const cursor = Number(requestUrl.searchParams.get("cursor") ?? "0");
    const offset = Number.isInteger(cursor) && cursor >= 0 ? cursor : 0;
    const selectedRows = rows.slice(offset, offset + pageLimit + 1);
    return createDefinitionSummaryList(
        kind,
        selectedRows.slice(0, pageLimit),
        selectedRows.length > pageLimit ? String(offset + pageLimit) : null,
    );
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

async function expectDocumentOwnsVerticalOverflow(page: Page): Promise<void> {
    const shellScroll = await page.evaluate(() => {
        const shell = document.querySelector("main");
        const rootStyle = window.getComputedStyle(document.documentElement);
        const bodyStyle = window.getComputedStyle(document.body);
        const shellStyle = shell === null ? null : window.getComputedStyle(shell);
        if (shell !== null) {
            shell.scrollTop = shell.scrollHeight;
        }
        return {
            bodyOverflowY: bodyStyle.overflowY,
            rootOverflowY: rootStyle.overflowY,
            shellOverflowY: shellStyle?.overflowY ?? null,
            shellScrollTop: shell === null ? 0 : shell.scrollTop,
        };
    });

    expect(shellScroll.rootOverflowY).not.toBe("hidden");
    expect(shellScroll.bodyOverflowY).not.toBe("hidden");
    expect(shellScroll.shellOverflowY).toBe("visible");
    expect(shellScroll.shellScrollTop).toBe(0);
}

async function expectDefinitionsUsesSingleDocumentScroll(page: Page): Promise<void> {
    const metrics = await page.locator(".definitions-workspace").evaluate((workspace) => {
        const listShell = workspace.querySelector(".definition-list-shell");
        const listBody = workspace.querySelector(".definition-list-body");
        const detailShell = workspace.querySelector(".definition-detail-shell");
        const nestedScrollOwners = Array.from(workspace.querySelectorAll("*")).filter((element) => {
            const style = window.getComputedStyle(element);
            return (
                ["auto", "scroll"].includes(style.overflowY) &&
                element.scrollHeight > element.clientHeight + 1
            );
        });

        return {
            detailClientHeight: detailShell?.clientHeight ?? null,
            detailMaxHeight:
                detailShell === null ? null : window.getComputedStyle(detailShell).maxHeight,
            detailOverflowY:
                detailShell === null ? null : window.getComputedStyle(detailShell).overflowY,
            detailScrollHeight: detailShell?.scrollHeight ?? null,
            documentClientHeight: document.documentElement.clientHeight,
            documentScrollHeight: document.documentElement.scrollHeight,
            listBodyOverflowY:
                listBody === null ? null : window.getComputedStyle(listBody).overflowY,
            listClientHeight: listShell?.clientHeight ?? null,
            listMaxHeight: listShell === null ? null : window.getComputedStyle(listShell).maxHeight,
            listScrollHeight: listShell?.scrollHeight ?? null,
            nestedScrollOwnerCount: nestedScrollOwners.length,
            workspaceAlignItems: window.getComputedStyle(workspace).alignItems,
        };
    });

    expect(metrics).toMatchObject({
        detailMaxHeight: "none",
        detailOverflowY: "visible",
        listBodyOverflowY: "visible",
        listMaxHeight: "none",
        nestedScrollOwnerCount: 0,
        workspaceAlignItems: "flex-start",
    });
    expect(metrics.detailClientHeight).toBe(metrics.detailScrollHeight);
    expect(metrics.listClientHeight).toBe(metrics.listScrollHeight);
    expect(metrics.documentScrollHeight).toBeGreaterThan(metrics.documentClientHeight);
}
