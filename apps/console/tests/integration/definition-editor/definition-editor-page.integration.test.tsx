import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../src/api/generated/openapi";
import { DefinitionEditorPage } from "../../../src/features/definition-editor/DefinitionEditorPage";
import { TEST_API_BASE_URL, createOperationFailureBody } from "../../fixtures/console-api";
import { installTestConsoleConfig } from "../../fixtures/console-config";
import {
    DEFINITION_EDITOR_NEW_DRAFT_KEY,
    DEFINITION_EDITOR_ROLE_KEY,
    DEFINITION_EDITOR_UPDATED_BODY,
    DEFINITION_EDITOR_WORKFLOW_KEY,
    bodyForKind,
    createCleanDefinitionEditorDraft,
    createDefinitionEditorDraftDetail,
    createDefinitionEditorDraftList,
    createDefinitionEditorDraftResponse,
    createDefinitionEditorPublish,
    createDefinitionEditorValidation,
    createNewRoleDraft,
    createUnsavedCurrentDefinitionDraft,
} from "../../fixtures/definition-editor";

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

describe("DefinitionEditorPage", () => {
    it(
        "loads one flat saved draft, saves before validate, and publishes one revision",
        { timeout: 15_000 },
        async () => {
            const user = userEvent.setup();
            let savedBody = "";
            installDefinitionEditorHandlers({
                onWrite: async (request) => {
                    const body =
                        (await request.json()) as components["schemas"]["DefinitionDraftWriteRequest"];
                    savedBody = body.body;
                    return createDefinitionEditorDraftResponse(
                        createCleanDefinitionEditorDraft(body.body),
                    );
                },
            });

            renderDefinitionEditorPage();

            expect(await screen.findByRole("heading", { name: "Definition Editor" })).toBeVisible();
            expect(
                await screen.findByRole("button", {
                    name: new RegExp(DEFINITION_EDITOR_WORKFLOW_KEY),
                }),
            ).toBeVisible();
            expect(await screen.findByLabelText("Draft body")).toHaveValue(
                bodyForKind("workflow", DEFINITION_EDITOR_WORKFLOW_KEY),
            );

            await user.clear(screen.getByLabelText("Draft body"));
            await user.type(screen.getByLabelText("Draft body"), DEFINITION_EDITOR_UPDATED_BODY);
            expect(screen.getByText("local edits")).toBeVisible();
            await user.click(screen.getByRole("button", { name: "Validate" }));

            expect(savedBody).toBe(DEFINITION_EDITOR_UPDATED_BODY);
            const validationDialog = await screen.findByRole("dialog", {
                name: "Validation valid",
            });
            expect(
                within(validationDialog).getByText("No validation issues returned."),
            ).toBeVisible();
            await user.click(within(validationDialog).getByRole("button", { name: /^Close$/ }));
            await waitFor(() => {
                expect(
                    screen.queryByRole("dialog", { name: "Validation valid" }),
                ).not.toBeInTheDocument();
            });

            await user.click(screen.getByRole("button", { name: "Publish" }));
            const publishDialog = await screen.findByRole("dialog", { name: "Publish published" });
            expect(
                within(publishDialog).getByText(/Workflow definition-editor-page revision 14/),
            ).toBeVisible();
            await waitFor(() => {
                expect(
                    within(publishDialog).getByText(/Reread the published registry/i),
                ).toBeVisible();
                expect(
                    screen.queryByRole("heading", { name: "Loading draft" }),
                ).not.toBeInTheDocument();
            });
        },
    );

    it("keeps the editor immutable while a delayed validation save owns its response", async () => {
        const user = userEvent.setup();
        let releaseWrite: (() => void) | undefined;
        const writeGate = new Promise<void>((resolve) => {
            releaseWrite = resolve;
        });
        installDefinitionEditorHandlers({
            onWrite: async (request) => {
                const body =
                    (await request.json()) as components["schemas"]["DefinitionDraftWriteRequest"];
                await writeGate;
                return createDefinitionEditorDraftResponse(
                    createCleanDefinitionEditorDraft(body.body),
                );
            },
        });

        renderDefinitionEditorPage();
        const editor = await screen.findByLabelText<HTMLTextAreaElement>("Draft body");
        await user.type(editor, "\n# saved generation");
        const submittedBody = editor.value;
        await user.click(screen.getByRole("button", { name: "Validate" }));

        expect(editor).toBeDisabled();
        await user.type(editor, "\n# later local generation");
        expect(editor).toHaveValue(submittedBody);
        releaseWrite?.();

        expect(await screen.findByRole("dialog", { name: "Validation valid" })).toBeVisible();
        expect(editor).toBeEnabled();
        expect(editor).toHaveValue(submittedBody);
    });

    it("keeps a delayed detail response bound to its exact draft identity", async () => {
        const user = userEvent.setup();
        const roleDraft = createNewRoleDraft();
        let releaseWorkflowRead: (() => void) | undefined;
        const workflowReadGate = new Promise<void>((resolve) => {
            releaseWorkflowRead = resolve;
        });
        installDefinitionEditorHandlers({
            list: createDefinitionEditorDraftList(createDefinitionEditorDraftDetail(), roleDraft),
        });
        server.use(
            http.get("*/authoring/definitions/:kind/:key/draft", async ({ params }) => {
                const kind = String(params.kind) as components["schemas"]["DefinitionKind"];
                const key = String(params.key);
                if (key === DEFINITION_EDITOR_WORKFLOW_KEY) {
                    await workflowReadGate;
                    return HttpResponse.json(
                        createDefinitionEditorDraftResponse(createDefinitionEditorDraftDetail()),
                    );
                }
                return HttpResponse.json(
                    createDefinitionEditorDraftResponse(
                        createDefinitionEditorDraftDetail({
                            body: bodyForKind(kind, key),
                            key,
                            kind,
                            status: "clean",
                        }),
                    ),
                );
            }),
        );

        renderDefinitionEditorPage();
        await user.click(await screen.findByRole("button", { name: new RegExp(roleDraft.key) }));
        const editor = await screen.findByLabelText<HTMLTextAreaElement>("Draft body");
        expect(editor.value).toContain(roleDraft.key);

        releaseWorkflowRead?.();
        await waitFor(() => {
            expect(editor.value).toContain(roleDraft.key);
            expect(editor.value).not.toContain(DEFINITION_EDITOR_WORKFLOW_KEY);
        });
    });

    it("blocks clean-draft navigation while validation owns the exact response", async () => {
        const user = userEvent.setup();
        let releaseValidation: (() => void) | undefined;
        const validationGate = new Promise<void>((resolve) => {
            releaseValidation = resolve;
        });
        installDefinitionEditorHandlers();
        server.use(
            http.post("*/authoring/definitions/:kind/:key/draft/validate", async () => {
                await validationGate;
                return HttpResponse.json(createDefinitionEditorValidation("valid"));
            }),
        );

        const router = renderDefinitionEditorPage();
        await screen.findByLabelText("Draft body");
        await user.click(screen.getByRole("button", { name: "Validate" }));
        act(() => {
            void router.navigate("/tasks");
        });

        const blockedDialog = await screen.findByRole("dialog", {
            name: "Draft operation still in progress",
        });
        expect(within(blockedDialog).getByText(/belongs to this exact draft/i)).toBeVisible();
        await user.click(within(blockedDialog).getByRole("button", { name: "Stay on this draft" }));
        releaseValidation?.();

        expect(await screen.findByRole("dialog", { name: "Validation valid" })).toBeVisible();
        expect(screen.getByRole("heading", { name: "Definition Editor" })).toBeVisible();
    });

    it("blocks clean-draft navigation through a delayed publish reread", async () => {
        const user = userEvent.setup();
        let releasePublish: (() => void) | undefined;
        const publishGate = new Promise<void>((resolve) => {
            releasePublish = resolve;
        });
        installDefinitionEditorHandlers();
        server.use(
            http.post("*/authoring/definitions/:kind/:key/draft/publish", async () => {
                await publishGate;
                return HttpResponse.json(createDefinitionEditorPublish("published"));
            }),
        );

        const router = renderDefinitionEditorPage();
        await screen.findByLabelText("Draft body");
        await user.click(screen.getByRole("button", { name: "Publish" }));
        act(() => {
            void router.navigate("/tasks");
        });
        expect(
            await screen.findByRole("dialog", { name: "Draft operation still in progress" }),
        ).toBeVisible();

        releasePublish?.();
        expect(await screen.findByRole("heading", { name: "Tasks destination" })).toBeVisible();
        expect(screen.queryByRole("dialog", { name: /Publish published/ })).not.toBeInTheDocument();
    });

    it("creates flat definition drafts and keeps name collisions in the dialog", async () => {
        const user = userEvent.setup();
        installDefinitionEditorHandlers({
            onCreate: async (request) => {
                const body =
                    (await request.json()) as components["schemas"]["DefinitionDraftCreateRequest"];
                if (body.key === DEFINITION_EDITOR_ROLE_KEY) {
                    return HttpResponse.json(
                        createOperationFailureBody({
                            code: "name_collision",
                            field_path: "key",
                            retryable: false,
                            suggested_next_step: "Choose a different definition key.",
                            summary: "A stored role already owns this key.",
                        }),
                        { status: 409 },
                    );
                }
                return HttpResponse.json(createDefinitionEditorDraftResponse(createNewRoleDraft()));
            },
        });

        renderDefinitionEditorPage();
        await screen.findByRole("button", { name: new RegExp(DEFINITION_EDITOR_WORKFLOW_KEY) });

        await user.click(screen.getAllByRole("button", { name: "New draft" })[0]);
        const dialog = await screen.findByRole("dialog", { name: "New draft" });
        await user.type(within(dialog).getByLabelText("Key"), DEFINITION_EDITOR_ROLE_KEY);
        await user.click(within(dialog).getByRole("button", { name: "Create draft" }));
        expect(
            await within(dialog).findByText("A stored role already owns this key."),
        ).toBeVisible();

        await user.clear(within(dialog).getByLabelText("Key"));
        await user.type(within(dialog).getByLabelText("Key"), DEFINITION_EDITOR_NEW_DRAFT_KEY);
        await user.click(within(dialog).getByRole("button", { name: "Create draft" }));

        expect(
            await screen.findByRole("button", {
                name: new RegExp(DEFINITION_EDITOR_NEW_DRAFT_KEY),
            }),
        ).toBeVisible();
        expect(screen.getByDisplayValue(new RegExp(DEFINITION_EDITOR_NEW_DRAFT_KEY))).toBeVisible();
    });

    it("creates strict V2 workflow-provider and policy-capability starter bodies", async () => {
        const user = userEvent.setup();
        const createdBodies: components["schemas"]["DefinitionDraftCreateRequest"][] = [];
        installDefinitionEditorHandlers({
            onCreate: async (request) => {
                const body =
                    (await request.json()) as components["schemas"]["DefinitionDraftCreateRequest"];
                createdBodies.push(body);
                return HttpResponse.json(
                    createDefinitionEditorDraftResponse(
                        createDefinitionEditorDraftDetail({
                            body: body.body ?? "",
                            is_saved: true,
                            key: body.key,
                            kind: body.kind,
                            mode: body.mode,
                            status: "new",
                        }),
                    ),
                );
            },
        });

        renderDefinitionEditorPage();
        await screen.findByRole("button", { name: new RegExp(DEFINITION_EDITOR_WORKFLOW_KEY) });

        await user.click(screen.getAllByRole("button", { name: "New draft" })[0]);
        let dialog = await screen.findByRole("dialog", { name: "New draft" });
        await user.selectOptions(within(dialog).getByLabelText("Kind"), "workflow");
        await user.type(within(dialog).getByLabelText("Key"), "strict-provider-workflow");
        await user.click(within(dialog).getByRole("button", { name: "Create draft" }));

        expect(createdBodies[0]?.body).toContain('node_key: "root"');
        expect(createdBodies[0]?.body).toContain('role_id: "root_planning_lead"');
        expect(createdBodies[0]?.body).toContain('policy_id: "standard-root"');
        expect(createdBodies[0]?.body).toContain('provider:\n        kind: "codex"');
        expect(createdBodies[0]?.body).not.toContain("provider_preference");

        await user.click(screen.getAllByRole("button", { name: "New draft" })[0]);
        dialog = await screen.findByRole("dialog", { name: "New draft" });
        await user.selectOptions(within(dialog).getByLabelText("Kind"), "policy");
        await user.type(within(dialog).getByLabelText("Key"), "strict-capability-policy");
        await user.click(within(dialog).getByRole("button", { name: "Create draft" }));

        expect(createdBodies[1]?.body).toContain('provider_native_access: "full"');
        expect(createdBodies[1]?.body).toContain('network_access: "allow"');
        expect(createdBodies[1]?.body).toContain('command_run: "deny"');
        expect(createdBodies[1]?.body).toContain("human_request:");
    });

    it("protects unsaved browser edits before switching saved drafts", async () => {
        const user = userEvent.setup();
        const roleDraft = createNewRoleDraft();
        installDefinitionEditorHandlers({
            list: createDefinitionEditorDraftList(createDefinitionEditorDraftDetail(), roleDraft),
        });

        const router = renderDefinitionEditorPage();
        const editor = await screen.findByLabelText("Draft body");
        await user.type(editor, "\n# local unsaved change");
        expect(screen.getByText("local edits")).toBeVisible();

        const beforeUnload = new Event("beforeunload", { cancelable: true });
        window.dispatchEvent(beforeUnload);
        expect(beforeUnload.defaultPrevented).toBe(true);

        await user.click(screen.getByRole("button", { name: new RegExp(roleDraft.key) }));
        const warning = await screen.findByRole("dialog", {
            name: "Discard local draft edits?",
        });
        expect(within(warning).getByText(/exist only in this browser tab/i)).toBeVisible();
        await user.click(within(warning).getByRole("button", { name: "Keep editing" }));
        expect(screen.getByLabelText<HTMLTextAreaElement>("Draft body").value).toContain(
            "# local unsaved change",
        );

        await user.click(screen.getByRole("button", { name: new RegExp(roleDraft.key) }));
        await user.click(
            within(
                await screen.findByRole("dialog", { name: "Discard local draft edits?" }),
            ).getByRole("button", { name: "Discard local edits" }),
        );
        expect(await screen.findByDisplayValue(new RegExp(roleDraft.key))).toBeVisible();
        expect(screen.queryByText("local edits")).not.toBeInTheDocument();

        await user.type(screen.getByLabelText("Draft body"), "\n# role query edit");
        await act(async () => {
            await router.navigate(-1);
        });
        await user.click(
            within(
                await screen.findByRole("dialog", { name: "Discard local draft edits?" }),
            ).getByRole("button", { name: "Discard local edits" }),
        );
        expect(
            await screen.findByDisplayValue(new RegExp(DEFINITION_EDITOR_WORKFLOW_KEY)),
        ).toBeVisible();
    });

    it("protects unsaved browser edits before history navigation", async () => {
        const user = userEvent.setup();
        installDefinitionEditorHandlers();
        const router = renderDefinitionEditorPage("/definitions/editor", "/tasks");

        const editor = await screen.findByLabelText("Draft body");
        await user.type(editor, "\n# unsaved before history back");
        await act(async () => {
            await router.navigate(-1);
        });

        let warning = await screen.findByRole("dialog", {
            name: "Discard local draft edits?",
        });
        await user.click(within(warning).getByRole("button", { name: "Keep editing" }));
        expect(screen.getByLabelText<HTMLTextAreaElement>("Draft body").value).toContain(
            "# unsaved before history back",
        );

        await act(async () => {
            await router.navigate(-1);
        });
        warning = await screen.findByRole("dialog", { name: "Discard local draft edits?" });
        await user.click(within(warning).getByRole("button", { name: "Discard local edits" }));

        expect(await screen.findByRole("heading", { name: "Tasks destination" })).toBeVisible();
    });

    it("opens a current stored definition from query params and saves it as an update draft", async () => {
        const user = userEvent.setup();
        const currentDraft = createUnsavedCurrentDefinitionDraft("from-definitions-link");
        installDefinitionEditorHandlers({
            detail: currentDraft,
            list: createDefinitionEditorDraftList(createDefinitionEditorDraftDetail()),
        });

        renderDefinitionEditorPage("/definitions/editor?kind=workflow&key=from-definitions-link");
        expect(await screen.findByDisplayValue(/from-definitions-link/)).toBeVisible();
        expect(screen.getAllByText("Update").length).toBeGreaterThan(0);

        await user.type(screen.getByLabelText("Draft body"), "\n# saved from link");
        await user.click(screen.getByRole("button", { name: "Save draft" }));
        await waitFor(() => {
            expect(screen.queryByText("local edits")).not.toBeInTheDocument();
        });
    });

    it("confirms reset, replace, and discard as separate saved draft actions", async () => {
        const user = userEvent.setup();
        const baselineBody = bodyForKind("workflow", DEFINITION_EDITOR_WORKFLOW_KEY).replace(
            "Deliver the Definition Editor authoring surface.",
            "Captured stored baseline for reset.",
        );
        const replacedBody = bodyForKind("workflow", DEFINITION_EDITOR_WORKFLOW_KEY).replace(
            "Deliver the Definition Editor authoring surface.",
            "Current stored truth after replace.",
        );
        let deletedCount = 0;
        let replacedCount = 0;
        let resetBody = "";

        installDefinitionEditorHandlers({
            detail: createDefinitionEditorDraftDetail({
                baseline_body: baselineBody,
                body: DEFINITION_EDITOR_UPDATED_BODY,
                status: "modified",
            }),
            onDelete: () => {
                deletedCount += 1;
            },
            onReplaceCurrent: () => {
                replacedCount += 1;
                return createDefinitionEditorDraftResponse(
                    createDefinitionEditorDraftDetail({
                        based_on: {
                            content_hash: "sha256:current-replace",
                            revision_no: 13,
                            source_path: null,
                        },
                        baseline_body: replacedBody,
                        body: replacedBody,
                        content_hash: "sha256:current-replace",
                        status: "clean",
                    }),
                );
            },
            onWrite: async (request) => {
                const body =
                    (await request.json()) as components["schemas"]["DefinitionDraftWriteRequest"];
                resetBody = body.body;
                return createDefinitionEditorDraftResponse(
                    createDefinitionEditorDraftDetail({
                        baseline_body: baselineBody,
                        body: body.body,
                        status: body.body === baselineBody ? "clean" : "modified",
                    }),
                );
            },
        });

        renderDefinitionEditorPage();
        expect(await screen.findByLabelText("Draft body")).toHaveValue(
            DEFINITION_EDITOR_UPDATED_BODY,
        );

        await user.click(screen.getByRole("button", { name: "Reset draft" }));
        const resetDialog = await screen.findByRole("dialog", { name: "Reset draft" });
        expect(
            within(resetDialog).getByText(
                /restores the selected file to its captured draft baseline/i,
            ),
        ).toBeVisible();
        await user.click(within(resetDialog).getByRole("button", { name: "Reset draft" }));
        await waitFor(() => {
            expect(screen.queryByRole("dialog", { name: "Reset draft" })).not.toBeInTheDocument();
        });
        expect(resetBody).toBe(baselineBody);
        expect(deletedCount).toBe(0);
        expect(replacedCount).toBe(0);
        expect(screen.getByLabelText("Draft body")).toHaveValue(baselineBody);

        await user.click(
            screen.getByRole("button", { name: "Replace with current stored revision" }),
        );
        const replaceDialog = await screen.findByRole("dialog", {
            name: "Replace with current stored revision",
        });
        expect(
            within(replaceDialog).getByText(/reads the current stored registry revision/i),
        ).toBeVisible();
        await user.click(within(replaceDialog).getByRole("button", { name: "Replace draft" }));
        await waitFor(() => {
            expect(
                screen.queryByRole("dialog", { name: "Replace with current stored revision" }),
            ).not.toBeInTheDocument();
        });
        expect(deletedCount).toBe(0);
        expect(replacedCount).toBe(1);
        expect(screen.getByLabelText("Draft body")).toHaveValue(replacedBody);

        await user.click(screen.getByRole("button", { name: "Discard saved draft" }));
        const discardDialog = await screen.findByRole("dialog", {
            name: "Discard saved draft",
        });
        expect(
            within(discardDialog).getByText(/permanently removes the saved draft file/i),
        ).toBeVisible();
        await user.click(
            within(discardDialog).getByRole("button", { name: "Discard saved draft" }),
        );
        await waitFor(() => {
            expect(
                screen.queryByRole("dialog", { name: "Discard saved draft" }),
            ).not.toBeInTheDocument();
        });
        expect(deletedCount).toBe(1);
        expect(replacedCount).toBe(1);
    });

    it("uses Tab and Shift+Tab for draft body indentation without leaving the editor", async () => {
        const user = userEvent.setup();
        installDefinitionEditorHandlers();

        renderDefinitionEditorPage();
        const editorElement = await screen.findByLabelText("Draft body");
        expect(editorElement).toBeInstanceOf(HTMLTextAreaElement);
        const editor = editorElement as HTMLTextAreaElement;
        await user.clear(editor);
        await user.type(editor, "root:\nchild: value");
        editor.setSelectionRange("root:\n".length, "root:\nchild".length);

        await user.keyboard("{Tab}");
        expect(editor).toHaveFocus();
        expect(editor).toHaveValue("root:\n  child: value");

        editor.setSelectionRange("root:\n".length, "root:\n  child".length);
        await user.keyboard("{Shift>}{Tab}{/Shift}");
        expect(editor).toHaveFocus();
        expect(editor).toHaveValue("root:\nchild: value");
    });

    it("contains dialog focus, closes with Escape, and restores the invoking control", async () => {
        const user = userEvent.setup();
        installDefinitionEditorHandlers();

        renderDefinitionEditorPage();
        await screen.findByLabelText("Draft body");
        const newDraftButton = screen.getAllByRole("button", { name: "New draft" })[0];
        newDraftButton.focus();
        await user.click(newDraftButton);

        let dialog = await screen.findByRole("dialog", { name: "New draft" });
        expect(within(dialog).getByLabelText("Key")).toHaveFocus();
        await user.keyboard("{Escape}");
        expect(screen.queryByRole("dialog", { name: "New draft" })).not.toBeInTheDocument();
        expect(newDraftButton).toHaveFocus();

        await user.click(newDraftButton);
        dialog = await screen.findByRole("dialog", { name: "New draft" });
        const closeButton = within(dialog).getByRole("button", { name: "Close new draft" });
        const createButton = within(dialog).getByRole("button", { name: "Create draft" });
        closeButton.focus();
        await user.keyboard("{Shift>}{Tab}{/Shift}");
        expect(createButton).toHaveFocus();
        await user.keyboard("{Tab}");
        expect(closeButton).toHaveFocus();
    });

    it("shows local-admission failures on the flat draft list", async () => {
        server.use(
            http.get("*/authoring/definition-drafts", () =>
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

        renderDefinitionEditorPage();
        expect(await screen.findByText("Access to drafts failed")).toBeVisible();
        expect(
            screen.getByText("The request was not admitted by the loopback control plane."),
        ).toBeVisible();
    });
});

function renderDefinitionEditorPage(initialEntry = "/definitions/editor", previousEntry?: string) {
    const initialEntries =
        previousEntry === undefined ? [initialEntry] : [previousEntry, initialEntry];
    const router = createMemoryRouter(
        [
            {
                element: <DefinitionEditorPage />,
                path: "/definitions/editor",
            },
            {
                element: <h1>Tasks destination</h1>,
                path: "/tasks",
            },
        ],
        { initialEntries, initialIndex: initialEntries.length - 1 },
    );
    render(<RouterProvider router={router} />);
    return router;
}

function installDefinitionEditorHandlers({
    detail = createDefinitionEditorDraftDetail(),
    list,
    onCreate,
    onDelete,
    onReplaceCurrent,
    onWrite,
    publishResponse = createDefinitionEditorPublish("published"),
    validationResponse = createDefinitionEditorValidation("valid"),
}: {
    readonly detail?: components["schemas"]["DefinitionDraftDetail"];
    readonly list?: components["schemas"]["DefinitionDraftListResponse"];
    readonly onCreate?: (request: Request) => Promise<Response>;
    readonly onDelete?: () => void;
    readonly onReplaceCurrent?: () => components["schemas"]["DefinitionDraftDetailResponse"];
    readonly onWrite?: (
        request: Request,
    ) => Promise<components["schemas"]["DefinitionDraftDetailResponse"]>;
    readonly publishResponse?: components["schemas"]["DefinitionDraftPublishResponse"];
    readonly validationResponse?: components["schemas"]["DefinitionDraftValidationResponse"];
} = {}) {
    server.use(
        http.get("*/authoring/definition-drafts", () =>
            HttpResponse.json(list ?? createDefinitionEditorDraftList(detail)),
        ),
        http.post("*/authoring/definition-drafts", async ({ request }) => {
            if (onCreate !== undefined) {
                return onCreate(request);
            }
            return HttpResponse.json(createDefinitionEditorDraftResponse(createNewRoleDraft()));
        }),
        http.get("*/authoring/definitions/:kind/:key/draft", ({ params }) =>
            HttpResponse.json(
                createDefinitionEditorDraftResponse(
                    createDraftForPath(detail, String(params.kind), String(params.key)),
                ),
            ),
        ),
        http.put("*/authoring/definitions/:kind/:key/draft", async ({ params, request }) => {
            if (onWrite !== undefined) {
                return HttpResponse.json(await onWrite(request));
            }
            const body =
                (await request.json()) as components["schemas"]["DefinitionDraftWriteRequest"];
            return HttpResponse.json(
                createDefinitionEditorDraftResponse(
                    createDefinitionEditorDraftDetail({
                        body: body.body,
                        is_saved: true,
                        key: String(params.key),
                        kind: params.kind as components["schemas"]["DefinitionKind"],
                        mode: detail.mode,
                        status: "clean",
                    }),
                ),
            );
        }),
        http.post("*/authoring/definitions/:kind/:key/draft/replace-current", () => {
            if (onReplaceCurrent !== undefined) {
                return HttpResponse.json(onReplaceCurrent());
            }
            return HttpResponse.json(
                createDefinitionEditorDraftResponse(
                    createDefinitionEditorDraftDetail({ status: "clean" }),
                ),
            );
        }),
        http.delete("*/authoring/definitions/:kind/:key/draft", () => {
            onDelete?.();
            return new HttpResponse(null, { status: 204 });
        }),
        http.post("*/authoring/definitions/:kind/:key/draft/validate", () =>
            HttpResponse.json(validationResponse),
        ),
        http.post("*/authoring/definitions/:kind/:key/draft/publish", () =>
            HttpResponse.json(publishResponse),
        ),
    );
}

function createDraftForPath(
    baseDraft: components["schemas"]["DefinitionDraftDetail"],
    kind: string,
    key: string,
): components["schemas"]["DefinitionDraftDetail"] {
    if (kind !== "role" && kind !== "policy" && kind !== "workflow") {
        return baseDraft;
    }
    if (baseDraft.kind === kind && baseDraft.key === key) {
        return baseDraft;
    }
    return createDefinitionEditorDraftDetail({
        body: bodyForKind(kind, key),
        is_saved: false,
        key,
        kind,
        mode: "update",
        status: "clean",
    });
}
