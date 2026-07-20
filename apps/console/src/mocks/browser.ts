import { setupWorker } from "msw/browser";

import { createConsoleApiHandlers } from "./handlers";
import {
    createConsoleMockScenario,
    createLongRuntimeTaskRow,
    createMixedRuntimeTaskRows,
    createRuntimeFlowSummary,
    createRuntimeFlowSummaryList,
} from "../../tests/fixtures/console-api";
import {
    createDefinitionDetailMap,
    createDefinitionSummaryList,
    createDefinitionVersionsMap,
    createPolicyDefinitionRows,
    createRoleDefinitionRows,
} from "../../tests/fixtures/definitions";
import {
    DEFINITION_EDITOR_ROLE_KEY,
    createDefinitionEditorDraftList,
    createDefinitionEditorDraftDetail,
    createDefinitionEditorDraftResponse,
    createDefinitionEditorPublish,
    createDefinitionEditorValidation,
} from "../../tests/fixtures/definition-editor";
import {
    TASK_DETAIL_TASK_ID,
    createTaskDetailMockScenario,
} from "../../tests/fixtures/task-detail";
import {
    createHumanRequestPageList,
    createHumanRequestResolveResponse,
} from "../../tests/fixtures/human-requests";
import {
    SECOND_TASK_START_WORKFLOW_KEY,
    TASK_START_WORKFLOW_KEY,
    createTaskStartWorkflowDetail,
    createTaskStartWorkflowRows,
    createTaskStartWorkflowVersions,
} from "../../tests/fixtures/task-start";

let isStarted = false;

export async function enableMockApi(): Promise<void> {
    if (!import.meta.env.DEV) {
        throw new Error("The browser mock API is available only in development builds");
    }
    if (isStarted) {
        return;
    }

    const worker = setupWorker(...createConsoleApiHandlers(createDevMockScenario()));
    await worker.start({
        onUnhandledRequest: "bypass",
        serviceWorker: {
            url: "/mockServiceWorker.js",
        },
    });

    isStarted = true;
}

function createDevMockScenario() {
    const taskDetailScenario = createTaskDetailMockScenario();
    const humanRequestList = createHumanRequestPageList();
    const taskListRows = createMixedRuntimeTaskRows()
        .filter((task) => task.task_id !== "task-runtime-copy-refresh")
        .map((task, index) =>
            withRelativeUpdatedAt(task, [29, 48, 60, 120, 135, 160][index] ?? 180),
        );
    const firstTaskListPage = [
        createRuntimeFlowSummary({
            active_attempt_id: taskDetailScenario.taskRead.active_attempt_id,
            active_flow_revision_id: taskDetailScenario.taskRead.active_flow_revision_id,
            current_node_key: "copy_update",
            status: taskDetailScenario.taskRead.status,
            task_id: TASK_DETAIL_TASK_ID,
            task_summary: "Update the current task-control labels.",
            task_title: taskDetailScenario.taskRead.task_title,
            updated_at: relativeUpdatedAt(6),
            workflow_key: "runtime_copy_refresh",
            workflow_manifest_ref: taskDetailScenario.taskRead.workflow_manifest_ref,
        }),
        ...taskListRows.slice(0, 4),
    ];
    const secondTaskListPage = [
        ...taskListRows.slice(4),
        withRelativeUpdatedAt(createLongRuntimeTaskRow(), 190),
    ];
    const definitionDetails = createDefinitionDetailMap();
    const definitionVersionsByDefinition = createDefinitionVersionsMap();
    const definitionEditorDraftDetail = createDefinitionEditorDraftResponse();
    const definitionEditorRoleDraft = createDefinitionEditorDraftDetail({
        key: DEFINITION_EDITOR_ROLE_KEY,
        kind: "role",
        status: "clean",
    });
    const scenario = createConsoleMockScenario({
        commandRunList: taskDetailScenario.commandRunList,
        humanRequestList,
        humanRequestResolve: createHumanRequestResolveResponse(humanRequestList.items[0].request),
        snapshot: taskDetailScenario.snapshot,
        taskEvents: taskDetailScenario.taskEvents,
        taskEventStream: taskDetailScenario.taskEventStream,
        taskList: createRuntimeFlowSummaryList(firstTaskListPage, "cursor-page-2"),
        taskListPages: {
            "cursor-page-2": createRuntimeFlowSummaryList(secondTaskListPage),
        },
        taskRead: taskDetailScenario.taskRead,
        trace: taskDetailScenario.trace,
    });

    return {
        ...scenario,
        definitionDetails: {
            ...definitionDetails,
            [`workflow:${TASK_START_WORKFLOW_KEY}`]:
                createTaskStartWorkflowDetail(TASK_START_WORKFLOW_KEY),
            [`workflow:${SECOND_TASK_START_WORKFLOW_KEY}`]: createTaskStartWorkflowDetail(
                SECOND_TASK_START_WORKFLOW_KEY,
            ),
        },
        definitionLists: {
            roles: createDefinitionSummaryList("role", createRoleDefinitionRows(), null),
            policies: createDefinitionSummaryList("policy", createPolicyDefinitionRows(), null),
            workflows: createDefinitionSummaryList("workflow", createTaskStartWorkflowRows(), null),
        },
        definitionVersionsByDefinition: {
            ...definitionVersionsByDefinition,
            [`workflow:${TASK_START_WORKFLOW_KEY}`]:
                createTaskStartWorkflowVersions(TASK_START_WORKFLOW_KEY),
            [`workflow:${SECOND_TASK_START_WORKFLOW_KEY}`]: createTaskStartWorkflowVersions(
                SECOND_TASK_START_WORKFLOW_KEY,
            ),
        },
        draftDetail: definitionEditorDraftDetail,
        draftList: createDefinitionEditorDraftList(
            definitionEditorDraftDetail.draft,
            definitionEditorRoleDraft,
        ),
        draftPublish: createDefinitionEditorPublish(),
        draftValidation: createDefinitionEditorValidation(),
    };
}

function relativeUpdatedAt(minutesAgo: number): string {
    return new Date(Date.now() - minutesAgo * 60_000).toISOString();
}

function withRelativeUpdatedAt<T extends { readonly updated_at: string }>(
    task: T,
    minutesAgo: number,
): T {
    return {
        ...task,
        updated_at: relativeUpdatedAt(minutesAgo),
    };
}
