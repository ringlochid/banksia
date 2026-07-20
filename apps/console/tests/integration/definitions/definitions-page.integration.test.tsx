import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../src/api/generated/openapi";
import { DefinitionsPage } from "../../../src/features/definitions/DefinitionsPage";
import { createOperationFailureBody, TEST_API_BASE_URL } from "../../fixtures/console-api";
import {
    POLICY_KEY,
    ROLE_KEY,
    WORKFLOW_KEY,
    createDefinitionDetailMap,
    createDefinitionSummaryList,
    createDefinitionVersions,
    createDefinitionVersionsMap,
    createPolicyDefinitionRows,
    createRoleDefinitionRows,
    createWorkflowDefinitionRows,
} from "../../fixtures/definitions";
import { installTestConsoleConfig } from "../../fixtures/console-config";

const server = setupServer();

beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
    vi.stubEnv("VITE_AUTOCLAW_API_BASE_URL", TEST_API_BASE_URL);
    installTestConsoleConfig();
});

afterEach(() => {
    cleanup();
    server.resetHandlers();
    installTestConsoleConfig();
    vi.unstubAllEnvs();
});

afterAll(() => {
    server.close();
});

describe("DefinitionsPage", () => {
    it("uses kind-scoped routes, filters, cursor loading, detail, and compact versions", async () => {
        const user = userEvent.setup();
        const seenRequests: URL[] = [];
        installDefinitionsHandlers(seenRequests);

        renderDefinitionsPage();

        const definitionRows = within(await screen.findByRole("list", { name: "Definition rows" }));
        const planningLeadRow = await definitionRows.findByRole("button", {
            name: new RegExp(`^${ROLE_KEY}\\b`),
        });
        expect(planningLeadRow.textContent.trim().startsWith(ROLE_KEY)).toBe(true);
        expect(
            screen.getAllByText("Parent/root coordinator for one owned subtree.").length,
        ).toBeGreaterThan(0);
        expect(seenRequests[0]?.pathname).toBe("/definitions/roles");
        expect(seenRequests[0]?.searchParams.get("limit")).toBe("4");
        expect(seenRequests[0]?.searchParams.get("sort")).toBe("updated_at_desc");
        expect(screen.getByText("4 roles loaded.")).toBeVisible();

        await user.selectOptions(screen.getByLabelText("Allowed node kind"), "worker");
        await waitFor(() => {
            expect(
                lastPathRequest(seenRequests, "/definitions/roles")?.searchParams.get(
                    "allowed_node_kind",
                ),
            ).toBe("worker");
        });

        await user.type(screen.getByLabelText("Search"), "frontend");
        await waitFor(() => {
            expect(hasRequestParam(seenRequests, "/definitions/roles", "q", "frontend")).toBe(true);
        });

        await user.selectOptions(screen.getByLabelText("Sort"), "key_asc");
        await waitFor(() => {
            expect(hasRequestParam(seenRequests, "/definitions/roles", "sort", "key_asc")).toBe(
                true,
            );
        });

        await user.click(screen.getByRole("button", { name: "Load more" }));
        expect((await screen.findAllByText("release_operator")).length).toBeGreaterThan(0);
        expect(screen.getByText("5 roles loaded.")).toBeVisible();
        expect(
            lastPathRequest(seenRequests, "/definitions/roles")?.searchParams.get("cursor"),
        ).toBe("roles-page-2");

        await user.click(screen.getByRole("button", { name: "Revision 4" }));
        const versionsDialog = within(screen.getByRole("dialog", { name: "Versions" }));
        const versionsList = within(
            versionsDialog.getByRole("list", { name: "Definition versions" }),
        );
        expect(versionsList.getByText("Revision 4")).toBeVisible();
        expect(versionsList.getByText("Revision 3")).toBeVisible();
        expect(versionsDialog.getByText("Current registry pointer: revision 4.")).toBeVisible();
        expect(versionsList.getByText("Current")).toBeVisible();
        expect(versionsDialog.queryByText(/Recorded by:/)).not.toBeInTheDocument();
        await user.click(versionsDialog.getByRole("button", { name: "Close versions" }));

        await user.click(screen.getByRole("button", { name: "Policies" }));
        const policyRows = within(await screen.findByRole("list", { name: "Definition rows" }));
        const policyRow = await policyRows.findByRole("button", {
            name: new RegExp(`^${POLICY_KEY}\\b`),
        });
        expect(policyRow.textContent.trim().startsWith(POLICY_KEY)).toBe(true);
        expect(screen.getByLabelText("Applies to")).toBeVisible();
        expect(screen.queryByLabelText("Allowed node kind")).not.toBeInTheDocument();
        expect(screen.getByText("Budget")).toBeVisible();
        expect(screen.getByText("No controller budget limit")).toBeVisible();
        expect(screen.getByText("Policy capability values")).toBeVisible();
        expect(screen.getByText("restricted")).toBeVisible();
        expect(screen.getAllByText("deny").length).toBeGreaterThan(0);
        expect(screen.getAllByText("· authored").length).toBeGreaterThan(0);
        expect(screen.queryByText(/not reported/)).not.toBeInTheDocument();

        await user.click(policyRows.getByRole("button", { name: /^standard-parent-planning\b/ }));
        expect(screen.getByText("4 child assignments")).toBeVisible();
        expect(screen.getAllByText("· omitted default").length).toBeGreaterThan(0);
        expect(screen.queryByText(/not reported/)).not.toBeInTheDocument();

        await user.click(policyRows.getByRole("button", { name: /^standard-worker\b/ }));
        expect(screen.getByText("1 retry")).toBeVisible();
        expect(screen.queryByText(/not reported/)).not.toBeInTheDocument();

        await user.selectOptions(screen.getByLabelText("Applies to"), "worker");
        await waitFor(() => {
            expect(
                lastPathRequest(seenRequests, "/definitions/policies")?.searchParams.get(
                    "applies_to",
                ),
            ).toBe("worker");
        });

        await user.click(screen.getByRole("button", { name: "Workflows" }));
        expect((await screen.findAllByText(WORKFLOW_KEY)).length).toBeGreaterThan(0);
        expect(screen.queryByLabelText("Allowed node kind")).not.toBeInTheDocument();
        expect(screen.queryByLabelText("Applies to")).not.toBeInTheDocument();
        const workflowRequest = lastPathRequest(seenRequests, "/definitions/workflows");
        expect(workflowRequest?.searchParams.get("allowed_node_kind")).toBeNull();
        expect(workflowRequest?.searchParams.get("applies_to")).toBeNull();
        expect(await screen.findByText("Structure")).toBeVisible();
        expect(await screen.findByText("First-level nodes")).toBeVisible();
        expect(await screen.findByText("implementation_loop")).toBeVisible();
        expect(screen.getAllByText("Provider: machine default").length).toBeGreaterThan(0);
        expect(screen.queryByText("Stored root role")).not.toBeInTheDocument();
        expect(screen.queryByText("Root tree")).not.toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Create/update draft" })).not.toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Edit in draft" })).toHaveAttribute(
            "href",
            "/definitions/editor?key=staged-delivery-release&kind=workflow",
        );
        const workflowRows = within(screen.getByRole("list", { name: "Definition rows" }));
        await user.click(workflowRows.getByRole("button", { name: /^bounded-change\b/ }));
        expect(await screen.findByText("Provider: OpenClaw (explicit)")).toBeVisible();
        expect(screen.getByText("experimental")).toBeVisible();
        expect(screen.getByText("Provider: Codex (explicit)")).toBeVisible();
        const taskStartLinks = screen.getAllByRole("link", { name: "Task Start" });
        expect(taskStartLinks[taskStartLinks.length - 1]).toHaveAttribute("href", "/task-start");
    });

    it("renders empty, no-results, stale-selection, detail-error, and history-error states", async () => {
        const user = userEvent.setup();
        const seenRequests: URL[] = [];
        const roleRows = createRoleDefinitionRows();
        server.use(
            http.get("*/definitions/roles", ({ request }) => {
                const requestUrl = new URL(request.url);
                seenRequests.push(requestUrl);
                if (requestUrl.searchParams.get("q") === "missing") {
                    return HttpResponse.json(createDefinitionSummaryList("role", [], null));
                }
                return HttpResponse.json(createDefinitionSummaryList("role", roleRows, null));
            }),
            http.get("*/definitions/:kind/:key/versions", () =>
                HttpResponse.json(createDefinitionVersions("role", ROLE_KEY)),
            ),
            http.get("*/definitions/:kind/:key", () =>
                HttpResponse.text("Detail read failed.", { status: 500 }),
            ),
        );

        renderDefinitionsPage();

        expect(await screen.findByText("Definition detail could not load")).toBeVisible();

        cleanup();
        server.resetHandlers();
        server.use(
            http.get("*/definitions/roles", ({ request }) => {
                const requestUrl = new URL(request.url);
                seenRequests.push(requestUrl);
                if (requestUrl.searchParams.get("q") === "missing") {
                    return HttpResponse.json(createDefinitionSummaryList("role", [], null));
                }
                return HttpResponse.json(createDefinitionSummaryList("role", roleRows, null));
            }),
            http.get("*/definitions/:kind/:key/versions", () =>
                HttpResponse.text("History read failed.", { status: 500 }),
            ),
            http.get("*/definitions/:kind/:key", () =>
                HttpResponse.json(createDefinitionDetailMap()[`role:${ROLE_KEY}`]),
            ),
        );

        renderDefinitionsPage();
        expect((await screen.findAllByText("planning_lead")).length).toBeGreaterThan(0);
        expect(await screen.findByText(/Coordinate only the current owned subtree/)).toBeVisible();
        await user.click(screen.getByRole("button", { name: "Revision 4" }));
        expect(await screen.findByText("Version history could not load")).toBeVisible();

        await user.type(screen.getByLabelText("Search"), "missing");
        expect(await screen.findByText("No matching roles")).toBeVisible();
        expect(await screen.findByText("Selected definition is stale")).toBeVisible();
        expect(hasRequestParam(seenRequests, "/definitions/roles", "q", "missing")).toBe(true);
    });

    it("renders empty, auth, and single-revision history states honestly", async () => {
        const user = userEvent.setup();
        server.use(
            http.get("*/definitions/roles", () =>
                HttpResponse.json(createDefinitionSummaryList("role", [], null)),
            ),
        );

        const { unmount } = renderDefinitionsPage();
        expect((await screen.findAllByText("No stored roles")).length).toBeGreaterThan(0);

        unmount();
        cleanup();
        server.resetHandlers();
        server.use(
            http.get("*/definitions/roles", () =>
                HttpResponse.json(
                    createOperationFailureBody({
                        code: "local_admission_denied",
                        retryable: false,
                        summary: "The request was not admitted by the loopback control plane.",
                    }),
                    { status: 403 },
                ),
            ),
        );

        renderDefinitionsPage();
        expect(await screen.findByText("Access to Definitions failed")).toBeVisible();
        expect(
            screen.getByText("The request was not admitted by the loopback control plane."),
        ).toBeVisible();

        cleanup();
        server.resetHandlers();
        installDefinitionsHandlers([]);
        renderDefinitionsPage();
        expect((await screen.findAllByText(ROLE_KEY)).length).toBeGreaterThan(0);
        await user.click(screen.getByRole("button", { name: /planner/ }));
        expect(await screen.findByText(/Plan only the assigned scope/)).toBeVisible();
        await user.click(screen.getByRole("button", { name: "Revision 3" }));
        expect(await screen.findByText("Single current revision recorded.")).toBeVisible();
        const singleRevisionVersions = within(
            screen.getByRole("list", { name: "Definition versions" }),
        );
        expect(singleRevisionVersions.getByText("Revision 3")).toBeVisible();
        expect(singleRevisionVersions.getByText("Current")).toBeVisible();
    });
});

function renderDefinitionsPage() {
    return render(
        <MemoryRouter initialEntries={["/definitions"]}>
            <Routes>
                <Route element={<DefinitionsPage />} path="/definitions" />
                <Route element={<div>Definition Editor target</div>} path="/definitions/editor" />
                <Route element={<div>Task Start target</div>} path="/task-start" />
            </Routes>
        </MemoryRouter>,
    );
}

function installDefinitionsHandlers(seenRequests: URL[]): void {
    const details = createDefinitionDetailMap();
    const versions = createDefinitionVersionsMap();
    server.use(
        http.get("*/definitions/roles", ({ request }) => {
            const requestUrl = new URL(request.url);
            seenRequests.push(requestUrl);
            if (requestUrl.searchParams.get("cursor") === "roles-page-2") {
                return HttpResponse.json(
                    createDefinitionSummaryList(
                        "role",
                        [
                            {
                                allowed_node_kinds: ["worker"],
                                applies_to: null,
                                budget_spec: null,
                                current_revision_no: 1,
                                description: "Ordinary bounded release worker.",
                                key: "release_operator",
                                labels: ["authoring"],
                                title: "release_operator",
                                updated_at: "2026-06-29T12:00:00Z",
                            },
                        ],
                        null,
                    ),
                );
            }

            return HttpResponse.json(
                createDefinitionSummaryList("role", createRoleDefinitionRows(), "roles-page-2"),
            );
        }),
        http.get("*/definitions/policies", ({ request }) => {
            const requestUrl = new URL(request.url);
            seenRequests.push(requestUrl);
            return HttpResponse.json(
                createDefinitionSummaryList("policy", createPolicyDefinitionRows(), null),
            );
        }),
        http.get("*/definitions/workflows", ({ request }) => {
            const requestUrl = new URL(request.url);
            seenRequests.push(requestUrl);
            return HttpResponse.json(
                createDefinitionSummaryList("workflow", createWorkflowDefinitionRows(), null),
            );
        }),
        http.get("*/definitions/:kind/:key/versions", ({ params }) => {
            const lookupKey = `${String(params.kind)}:${String(params.key)}`;
            return HttpResponse.json(
                versions[lookupKey] ??
                    createDefinitionVersions(
                        String(params.kind) as components["schemas"]["DefinitionKind"],
                        String(params.key),
                    ),
            );
        }),
        http.get("*/definitions/:kind/:key", ({ params }) => {
            const lookupKey = `${String(params.kind)}:${String(params.key)}`;
            return HttpResponse.json(details[lookupKey] ?? details[`role:${ROLE_KEY}`]);
        }),
    );
}

function lastPathRequest(requests: readonly URL[], pathname: string): URL | null {
    return requests.filter((requestUrl) => requestUrl.pathname === pathname).at(-1) ?? null;
}

function hasRequestParam(
    requests: readonly URL[],
    pathname: string,
    name: string,
    value: string,
): boolean {
    return requests.some(
        (requestUrl) =>
            requestUrl.pathname === pathname && requestUrl.searchParams.get(name) === value,
    );
}
