import { describe, expect, it } from "vitest";

import {
    TASK_START_FIELD_PLACEHOLDERS,
    TASK_START_INITIAL_FORM,
    buildTaskStartPreview,
    buildTaskStartRequest,
    mapTaskStartWorkflowDetail,
    mapTaskStartWorkflowChoice,
    validateTaskStartForm,
    type TaskStartFormState,
} from "../../../src/features/task-start/task-start-model";
import {
    TASK_START_WORKFLOW_KEY,
    createTaskStartPreview,
    createTaskStartWorkflowDetail,
    createTaskStartWorkflowRows,
} from "../../fixtures/task-start";

describe("task start request mapper", () => {
    it("omits default roots and trims required task fields", () => {
        expect(
            buildTaskStartRequest(
                {
                    ...TASK_START_INITIAL_FORM,
                    instruction: "  ",
                    summary: "  Summary from stored truth  ",
                    taskKey: "  launch-from-workflow  ",
                    title: "  Launch from workflow  ",
                },
                "reviewed-change-release",
            ),
        ).toEqual({
            task: {
                key: "launch-from-workflow",
                summary: "Summary from stored truth",
                title: "Launch from workflow",
            },
            workflow: {
                key: "reviewed-change-release",
            },
        });
    });

    it("sends only explicit host root bindings", () => {
        expect(
            buildTaskStartRequest(
                {
                    ...TASK_START_INITIAL_FORM,
                    workspaceHostPath: " /tmp/workspace-root ",
                    workspaceMode: "ensure_host_path",
                },
                "feature-implementation",
            ).roots,
        ).toEqual({
            workspace: {
                host_path: "/tmp/workspace-root",
                mode: "ensure_host_path",
            },
        });
    });

    it("requires host paths only for explicit host modes", () => {
        const form: TaskStartFormState = {
            ...TASK_START_INITIAL_FORM,
            workspaceMode: "ensure_host_path",
            workspaceHostPath: "",
        };

        expect(validateTaskStartForm(form, "feature-implementation")).toMatchObject({
            workspaceHostPath: "Workspace host path is required.",
        });
    });

    it("keeps stored workflow key and updated freshness without picker revision readback", () => {
        const choice = mapTaskStartWorkflowChoice({
            ...createTaskStartWorkflowRows()[0],
            title: "Display title for picker only",
        });

        expect(choice.key).toBe(TASK_START_WORKFLOW_KEY);
        expect(choice.displayName).toBe("Display title for picker only");
        expect(choice.updatedAt).toBe("2026-06-16T18:42:00Z");
        expect("revisionLabel" in choice).toBe(false);
    });

    it("maps server preview provider and capability provenance without inventing a revision", () => {
        const workflow = mapTaskStartWorkflowChoice(createTaskStartWorkflowRows()[0]);
        const form = {
            ...TASK_START_INITIAL_FORM,
            instruction: TASK_START_FIELD_PLACEHOLDERS.instruction,
            summary: TASK_START_FIELD_PLACEHOLDERS.summary,
            taskKey: TASK_START_FIELD_PLACEHOLDERS.taskKey,
            title: TASK_START_FIELD_PLACEHOLDERS.title,
        };
        const preview = buildTaskStartPreview({
            detail: mapTaskStartWorkflowDetail(createTaskStartWorkflowDetail()),
            form,
            response: createTaskStartPreview(),
            workflow,
        });

        expect(preview).toMatchObject({
            instructionSummary:
                "Keep the work scoped to the current task-start UI and publish focused verification.",
            status: "ready",
            summary: "Launch one bounded implementation task from stored workflow truth.",
            taskKey: "implement-task-start-launch-form",
            title: "Implement Task Start launch form",
            workflowKey: TASK_START_WORKFLOW_KEY,
            workspaceModeLabel: "Task default",
        });
        expect(preview.nodes[0]).toMatchObject({
            isExperimentalProvider: true,
            networkAccess: { effective: "deny", source: "policy_definition" },
            nodeKey: "root",
            providerNativeAccess: {
                effective: "restricted",
                source: "policy_definition",
            },
            requestedProvider: "openclaw",
            resolvedProvider: "openclaw",
            selectionBasis: "explicit",
        });
        expect(preview.warnings).toEqual([
            expect.objectContaining({ code: "experimental_provider", kind: "provider" }),
        ]);
        expect("workflowRevisionLabel" in preview).toBe(false);
    });
});
