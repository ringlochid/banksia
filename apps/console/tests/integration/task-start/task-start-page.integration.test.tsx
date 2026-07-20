import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../src/api/generated/openapi";
import { TaskStartPage } from "../../../src/features/task-start/TaskStartPage";
import {
    createOperationFailureBody,
    createTaskStartResponse,
    TEST_API_BASE_URL,
    TEST_TASK_ID,
} from "../../fixtures/console-api";
import {
    SECOND_TASK_START_WORKFLOW_KEY,
    TASK_START_WORKFLOW_KEY,
    createTaskStartPreview,
    createTaskStartWorkflowDetail,
    createTaskStartWorkflowRows,
    createTaskStartWorkflowVersions,
} from "../../fixtures/task-start";
import { createDefinitionSummaryList } from "../../fixtures/definitions";
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

describe("TaskStartPage", () => {
    it("previews through current controller truth and starts with a fresh exact request", async () => {
        const user = userEvent.setup();
        const seenRequests: URL[] = [];
        let startBody: components["schemas"]["TaskStartRequest"] | null = null;
        let previewBody: components["schemas"]["TaskStartRequest"] | null = null;
        installTaskComposeHandlers({
            onRequest: (requestUrl) => {
                seenRequests.push(requestUrl);
            },
            onStart: async (request) => {
                startBody = (await request.json()) as components["schemas"]["TaskStartRequest"];
            },
            onPreview: async (request) => {
                previewBody = (await request.json()) as components["schemas"]["TaskStartRequest"];
            },
        });

        renderTaskStartPage();

        expect(await screen.findByRole("heading", { name: "Task Start" })).toBeVisible();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);
        const selectedWorkflowSummary = await screen.findByRole("group", {
            name: "Selected workflow",
        });
        expect(
            within(selectedWorkflowSummary).getByRole("heading", {
                level: 2,
                name: TASK_START_WORKFLOW_KEY,
            }),
        ).toBeVisible();
        expect(within(selectedWorkflowSummary).queryByText("Updated")).not.toBeInTheDocument();
        expect(within(selectedWorkflowSummary).queryByText(/Revision/)).not.toBeInTheDocument();
        expect(screen.getByText("3 required inputs still need attention.")).toBeVisible();
        expect(seenRequests[0]?.pathname).toBe("/definitions/workflows");
        expect(seenRequests[0]?.searchParams.get("limit")).toBe("8");
        expect(seenRequests[0]?.searchParams.get("sort")).toBe("updated_at_desc");

        await searchWorkflow(user, "normal");
        const workflowChoices = await screen.findByRole("list", { name: "Workflow choices" });
        expect(
            within(workflowChoices).getAllByText(TASK_START_WORKFLOW_KEY).length,
        ).toBeGreaterThan(0);
        expect(within(workflowChoices).queryByText(/Revision/)).not.toBeInTheDocument();
        await user.clear(screen.getByLabelText("Search workflow"));

        fillRequiredTaskFields();
        expect(screen.getByText("Ready to start from the selected workflow.")).toBeVisible();

        await user.click(screen.getByRole("button", { name: "Preview" }));
        const previewDialog = screen.getByRole("dialog", { name: "Preview" });
        const preview = within(previewDialog);
        expect(await preview.findByText("Current controller resolution")).toBeVisible();
        expect(preview.getByText("Workflow")).toBeVisible();
        expect(preview.getByText(TASK_START_WORKFLOW_KEY)).toBeVisible();
        expect(preview.getByText("Task")).toBeVisible();
        expect(preview.getByText("Implement Task Start launch form")).toBeVisible();
        expect(preview.getByText("implement-task-start-launch-form")).toBeVisible();
        expect(preview.getByText("Summary")).toBeVisible();
        expect(
            preview.getByText("Launch one bounded implementation task from stored workflow truth."),
        ).toBeVisible();
        expect(preview.getByText("Instruction")).toBeVisible();
        expect(
            preview.getByText(
                "Keep the work scoped to the current task-start UI and publish focused verification.",
            ),
        ).toBeVisible();
        expect(preview.getByText("Workspace")).toBeVisible();
        expect(preview.getByText("Task default")).toBeVisible();
        expect(preview.queryByText(/Revision/)).not.toBeInTheDocument();
        expect(preview.getByText(/does not reserve task or dispatch IDs/i)).toBeVisible();
        expect(preview.getByText("OpenClaw")).toBeVisible();
        expect(preview.getByText("experimental")).toBeVisible();
        expect(preview.getAllByText("Provider-native access").length).toBeGreaterThan(0);
        expect(preview.getAllByText("Network access").length).toBeGreaterThan(0);
        expect(preview.getAllByText("restricted").length).toBeGreaterThan(0);
        expect(preview.getAllByText(/policy definition/).length).toBeGreaterThan(0);
        expect(startBody).toBeNull();

        await user.click(preview.getByRole("button", { name: "Start Task" }));
        expect(await screen.findByText("Task launch committed")).toBeVisible();
        expect(screen.getByText(/Provider start follows asynchronously/i)).toBeVisible();
        expect(screen.getByRole("dialog", { name: "Result" })).toBeVisible();
        expect(screen.getByText("Flow status")).toBeVisible();
        expect(screen.getByText("Manifest")).toBeVisible();
        expect(screen.getByText("Running")).toBeVisible();
        expect(screen.getByText(TEST_TASK_ID)).toBeVisible();
        expect(screen.getByText("compiled-plan-001")).toBeVisible();
        expect(screen.getByText("flow-revision-001")).toBeVisible();
        expect(startBody).toEqual({
            task: {
                instruction:
                    "Keep the work scoped to the current task-start UI and publish focused verification.",
                key: "implement-task-start-launch-form",
                summary: "Launch one bounded implementation task from stored workflow truth.",
                title: "Implement Task Start launch form",
            },
            workflow: {
                key: TASK_START_WORKFLOW_KEY,
            },
        });
        expect(previewBody).toEqual(startBody);
    });

    it("validates required fields and the explicit workspace host mode before start", async () => {
        const user = userEvent.setup();
        let startBody: components["schemas"]["TaskStartRequest"] | null = null;
        installTaskComposeHandlers({
            onStart: async (request) => {
                startBody = (await request.json()) as components["schemas"]["TaskStartRequest"];
            },
        });

        renderTaskStartPage();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);

        await user.type(screen.getByLabelText("Title"), "Implement Task Start launch form");
        await user.type(
            screen.getByLabelText("Summary"),
            "Launch one bounded implementation task from stored workflow truth.",
        );
        await user.click(
            within(screen.getByRole("region", { name: "Workspace root" })).getByRole("button", {
                name: "Create host path",
            }),
        );
        await user.click(screen.getByRole("button", { name: "Preview" }));

        expect(await screen.findByText("Task key is required.")).toBeVisible();
        expect(screen.getByText("Workspace host path is required.")).toBeVisible();
        expect(startBody).toBeNull();

        await user.type(screen.getByLabelText("Task key"), "task-start-with-host-roots");
        const workspaceRoot = within(screen.getByRole("region", { name: "Workspace root" }));
        await user.type(workspaceRoot.getByLabelText("Host path"), "/tmp/autoclaw-workspace");
        await user.click(screen.getByRole("button", { name: "Start Task" }));

        await waitFor(() => {
            expect(startBody?.roots).toEqual({
                workspace: {
                    host_path: "/tmp/autoclaw-workspace",
                    mode: "ensure_host_path",
                },
            });
        });
    });

    it("renders workflow empty, workflow-missing, auth, and validation failures without clearing inputs", async () => {
        const user = userEvent.setup();
        server.use(
            http.get("*/definitions/workflows", ({ request }) => {
                const requestUrl = new URL(request.url);
                if (requestUrl.searchParams.get("q") === "missing") {
                    return HttpResponse.json(createDefinitionSummaryList("workflow", [], null));
                }
                return HttpResponse.json(
                    createDefinitionSummaryList("workflow", createTaskStartWorkflowRows(), null),
                );
            }),
            http.get("*/definitions/workflow/:key", ({ params }) => {
                if (params.key === SECOND_TASK_START_WORKFLOW_KEY) {
                    return HttpResponse.json(
                        createOperationFailureBody({
                            code: "missing_resource",
                            retryable: false,
                            summary: "The selected workflow no longer exists.",
                        }),
                        { status: 404 },
                    );
                }
                return HttpResponse.json(createTaskStartWorkflowDetail(String(params.key)));
            }),
            http.get("*/definitions/workflow/:key/versions", ({ params }) =>
                HttpResponse.json(createTaskStartWorkflowVersions(String(params.key))),
            ),
            http.post("*/tasks/start", () =>
                HttpResponse.json(
                    createOperationFailureBody({
                        code: "invalid_request_shape",
                        field_path: "task.key",
                        retryable: false,
                        summary: "Task key must contain at least one character.",
                    }),
                    { status: 400 },
                ),
            ),
        );

        renderTaskStartPage();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);
        await searchWorkflow(user, "missing");
        expect(await screen.findByText("No matching workflows")).toBeVisible();

        await searchWorkflow(user, "maximal");
        await user.click(
            await screen.findByRole("button", { name: new RegExp(SECOND_TASK_START_WORKFLOW_KEY) }),
        );
        expect(await screen.findByText("Selected workflow could not load")).toBeVisible();

        await user.click(screen.getByRole("button", { name: "Preview" }));
        expect(
            await screen.findByText(
                "Selected workflow could not be confirmed from stored registry truth.",
            ),
        ).toBeVisible();
        expect(screen.getByLabelText("Task key")).toHaveValue("");

        cleanup();
        server.resetHandlers();
        server.use(
            http.get("*/definitions/workflows", () =>
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

        renderTaskStartPage();
        expect(await screen.findByText("Access to workflows failed")).toBeVisible();

        cleanup();
        server.resetHandlers();
        installTaskComposeHandlers({
            startResponse: HttpResponse.json(
                createOperationFailureBody({
                    code: "invalid_request_shape",
                    field_path: "task.key",
                    retryable: false,
                    summary: "Task key must contain at least one character.",
                }),
                { status: 400 },
            ),
        });
        renderTaskStartPage();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);
        fillRequiredTaskFields();
        await user.click(screen.getByRole("button", { name: "Start Task" }));
        const validationDialog = await screen.findByRole("dialog", {
            name: "Task Start validation failed",
        });
        expect(validationDialog).toBeVisible();
        expect(screen.getByLabelText("Task key")).toHaveValue("implement-task-start-launch-form");
    });

    it("preserves inputs when invalid host path, occupied workspace, or permission failures return from start", async () => {
        const user = userEvent.setup();
        installTaskComposeHandlers({
            startResponse: HttpResponse.json(
                createOperationFailureBody({
                    code: "invalid_request_shape",
                    field_path: "roots.workspace.host_path",
                    retryable: false,
                    summary: "Workspace host path does not exist.",
                }),
                { status: 422 },
            ),
        });

        renderTaskStartPage();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);
        fillRequiredTaskFields();
        await user.click(
            within(screen.getByRole("region", { name: "Workspace root" })).getByRole("button", {
                name: "Use existing host",
            }),
        );
        await user.type(
            within(screen.getByRole("region", { name: "Workspace root" })).getByLabelText(
                "Host path",
            ),
            "/missing/workspace",
        );
        await user.click(screen.getByRole("button", { name: "Start Task" }));
        expect(await screen.findByText("Workspace host path does not exist.")).toBeVisible();
        expect(screen.getByRole("dialog", { name: "Task could not start" })).toBeVisible();
        expect(screen.getByLabelText("Task key")).toHaveValue("implement-task-start-launch-form");

        cleanup();
        server.resetHandlers();
        installTaskComposeHandlers({
            startResponse: HttpResponse.json(
                createOperationFailureBody({
                    code: "conflicting_continuation",
                    retryable: false,
                    summary: "The selected workspace is already held by a live task.",
                }),
                { status: 409 },
            ),
        });
        renderTaskStartPage();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);
        fillRequiredTaskFields();
        await user.click(screen.getByRole("button", { name: "Start Task" }));
        expect(
            await screen.findByText("The selected workspace is already held by a live task."),
        ).toBeVisible();

        cleanup();
        server.resetHandlers();
        installTaskComposeHandlers({
            startResponse: HttpResponse.json(
                createOperationFailureBody({
                    code: "local_admission_denied",
                    retryable: false,
                    summary: "The request was not admitted by the loopback control plane.",
                }),
                { status: 403 },
            ),
        });
        renderTaskStartPage();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);
        fillRequiredTaskFields();
        await user.click(screen.getByRole("button", { name: "Start Task" }));
        const accessDialog = await screen.findByRole("dialog", {
            name: "Access to Task Start failed",
        });
        expect(accessDialog).toBeVisible();
        expect(
            within(accessDialog).getByText(
                "The request was not admitted by the loopback control plane.",
            ),
        ).toBeVisible();
    });

    it("renders invalid server preview and keeps start-time revalidation independent", async () => {
        const user = userEvent.setup();
        installTaskComposeHandlers({
            previewResponse: HttpResponse.json(createTaskStartPreview("invalid")),
            startResponse: HttpResponse.json(
                createOperationFailureBody({
                    code: "conflict",
                    retryable: false,
                    summary: "Provider routing changed before task start.",
                }),
                { status: 409 },
            ),
        });

        renderTaskStartPage();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);
        fillRequiredTaskFields();
        await user.click(screen.getByRole("button", { name: "Preview" }));

        const previewDialog = await screen.findByRole("dialog", { name: "Preview" });
        expect(
            await within(previewDialog).findByText(
                "The selected provider route is not configured on this machine.",
            ),
        ).toBeVisible();
        expect(within(previewDialog).getByText("invalid")).toBeVisible();
        expect(within(previewDialog).getByRole("button", { name: "Start Task" })).toBeDisabled();

        await user.click(within(previewDialog).getByRole("button", { name: "Back to edit" }));
        await user.click(screen.getByRole("button", { name: "Start Task" }));
        expect(
            await screen.findByText("Provider routing changed before task start."),
        ).toBeVisible();
        expect(screen.getByLabelText("Task key")).toHaveValue("implement-task-start-launch-form");
    });

    it("keeps preview and result dialogs focused, closes with Escape, and restores focus", async () => {
        const user = userEvent.setup();
        installTaskComposeHandlers();

        renderTaskStartPage();
        expect((await screen.findAllByText(TASK_START_WORKFLOW_KEY)).length).toBeGreaterThan(0);
        fillRequiredTaskFields();

        const previewButton = screen.getByRole("button", { name: "Preview" });
        previewButton.focus();
        await user.click(previewButton);
        const previewDialog = await screen.findByRole("dialog", { name: "Preview" });
        expect(within(previewDialog).getByRole("button", { name: "Back to edit" })).toHaveFocus();

        await user.keyboard("{Escape}");
        await waitFor(() => {
            expect(screen.queryByRole("dialog", { name: "Preview" })).not.toBeInTheDocument();
        });
        expect(previewButton).toHaveFocus();

        const startButton = screen.getByRole("button", { name: "Start Task" });
        startButton.focus();
        await user.click(startButton);
        const resultDialog = await screen.findByRole("dialog", { name: "Result" });
        expect(within(resultDialog).getByRole("button", { name: "Back to edit" })).toHaveFocus();

        await user.keyboard("{Escape}");
        await waitFor(() => {
            expect(screen.queryByRole("dialog", { name: "Result" })).not.toBeInTheDocument();
        });
        expect(startButton).toHaveFocus();
    });
});

function renderTaskStartPage() {
    return render(
        <MemoryRouter initialEntries={["/task-start"]}>
            <Routes>
                <Route element={<TaskStartPage />} path="/task-start" />
            </Routes>
        </MemoryRouter>,
    );
}

function fillRequiredTaskFields(): void {
    fireEvent.change(screen.getByLabelText("Task key"), {
        target: { value: "implement-task-start-launch-form" },
    });
    fireEvent.change(screen.getByLabelText("Title"), {
        target: { value: "Implement Task Start launch form" },
    });
    fireEvent.change(screen.getByLabelText("Summary"), {
        target: { value: "Launch one bounded implementation task from stored workflow truth." },
    });
    fireEvent.change(screen.getByLabelText("Instruction"), {
        target: {
            value: "Keep the work scoped to the current task-start UI and publish focused verification.",
        },
    });
}

async function searchWorkflow(user: ReturnType<typeof userEvent.setup>, value: string) {
    const searchInput = screen.getByLabelText("Search workflow");
    await user.clear(searchInput);
    await user.type(searchInput, value);
}

function installTaskComposeHandlers({
    onRequest,
    onPreview,
    onStart,
    previewResponse,
    startResponse,
}: {
    readonly onRequest?: (requestUrl: URL) => void;
    readonly onPreview?: (request: Request) => Promise<void>;
    readonly onStart?: (request: Request) => Promise<void>;
    readonly previewResponse?: Response;
    readonly startResponse?: Response;
} = {}): void {
    server.use(
        http.get("*/definitions/workflows", ({ request }) => {
            const requestUrl = new URL(request.url);
            onRequest?.(requestUrl);
            return HttpResponse.json(
                createDefinitionSummaryList("workflow", createTaskStartWorkflowRows(), null),
            );
        }),
        http.get("*/definitions/workflow/:key", ({ params }) =>
            HttpResponse.json(createTaskStartWorkflowDetail(String(params.key))),
        ),
        http.get("*/definitions/workflow/:key/versions", ({ params }) =>
            HttpResponse.json(createTaskStartWorkflowVersions(String(params.key))),
        ),
        http.post("*/authoring/task-compose/preview", async ({ request }) => {
            await onPreview?.(request);
            return previewResponse ?? HttpResponse.json(createTaskStartPreview());
        }),
        http.post("*/tasks/start", async ({ request }) => {
            await onStart?.(request);
            return startResponse ?? HttpResponse.json(createTaskStartResponse());
        }),
    );
}
