import { buildQueryParams, type QueryParams } from "./client";
import type { operations } from "./generated/openapi";

export interface ApiRoute {
    readonly path: string;
    readonly query?: URLSearchParams;
}

export type RuntimeTasksQuery = NonNullable<
    operations["get_runtime_tasks_runtime_tasks_get"]["parameters"]["query"]
>;
export type ControlTaskEventsQuery = NonNullable<
    operations["get_control_task_events_control_tasks__task_id__events_get"]["parameters"]["query"]
>;
export type CommandRunListQuery = NonNullable<
    operations["get_control_command_runs_control_tasks__task_id__command_runs_get"]["parameters"]["query"]
>;
export type DefinitionListQuery = NonNullable<
    operations["get_role_definitions_definitions_roles_get"]["parameters"]["query"]
>;
export type DefinitionVersionsQuery = NonNullable<
    operations["get_definition_versions_definitions__kind___key__versions_get"]["parameters"]["query"]
>;
export type DefinitionDraftsQuery = NonNullable<
    operations["get_definition_drafts_authoring_definition_drafts_get"]["parameters"]["query"]
>;

export function runtimeTasksRoute(query?: RuntimeTasksQuery): ApiRoute {
    return {
        path: "/runtime/tasks",
        query: buildOptionalQuery(query),
    };
}

export function controlTaskRoute(taskId: string): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}`,
    };
}

export function controlTaskSnapshotRoute(taskId: string): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/snapshot`,
    };
}

export function controlTaskTraceRoute(taskId: string, query?: QueryParams): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/trace`,
        query: buildOptionalQuery(query),
    };
}

export function controlTaskEventsRoute(taskId: string, query?: ControlTaskEventsQuery): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/events`,
        query: buildOptionalQuery(query),
    };
}

export function controlTaskActionRoute(
    taskId: string,
    action: "cancel" | "continue" | "pause",
): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/${action}`,
    };
}

export function humanRequestsRoute(taskId: string): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/human-requests`,
    };
}

export function resolveHumanRequestRoute(taskId: string, requestId: string): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/human-requests/${encodeURIComponent(requestId)}/resolve`,
    };
}

export function commandRunsRoute(taskId: string, query?: CommandRunListQuery): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/command-runs`,
        query: buildOptionalQuery(query),
    };
}

export function commandRunRoute(taskId: string, runId: string): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/command-runs/${encodeURIComponent(runId)}`,
    };
}

export function commandRunLogRoute(taskId: string, runId: string): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/command-runs/${encodeURIComponent(runId)}/log`,
    };
}

export function cancelCommandRunRoute(taskId: string, runId: string): ApiRoute {
    return {
        path: `/control/tasks/${encodeURIComponent(taskId)}/command-runs/${encodeURIComponent(runId)}/cancel`,
    };
}

export function definitionsRoute(
    kind: "policies" | "roles" | "workflows",
    query?: DefinitionListQuery,
): ApiRoute {
    return {
        path: `/definitions/${kind}`,
        query: buildOptionalQuery(query),
    };
}

export function definitionRoute(kind: string, key: string): ApiRoute {
    return {
        path: `/definitions/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
    };
}

export function definitionVersionsRoute(
    kind: string,
    key: string,
    query?: DefinitionVersionsQuery,
): ApiRoute {
    return {
        path: `/definitions/${encodeURIComponent(kind)}/${encodeURIComponent(key)}/versions`,
        query: buildOptionalQuery(query),
    };
}

export function definitionDraftsRoute(query?: DefinitionDraftsQuery): ApiRoute {
    return {
        path: "/authoring/definition-drafts",
        query: buildOptionalQuery(query),
    };
}

export function definitionDraftRoute(kind: string, key: string): ApiRoute {
    return {
        path: `/authoring/definitions/${encodeURIComponent(kind)}/${encodeURIComponent(key)}/draft`,
    };
}

export function definitionDraftValidateRoute(kind: string, key: string): ApiRoute {
    return {
        path: `${definitionDraftRoute(kind, key).path}/validate`,
    };
}

export function definitionDraftPublishRoute(kind: string, key: string): ApiRoute {
    return {
        path: `${definitionDraftRoute(kind, key).path}/publish`,
    };
}

export function definitionDraftReplaceCurrentRoute(kind: string, key: string): ApiRoute {
    return {
        path: `${definitionDraftRoute(kind, key).path}/replace-current`,
    };
}

export function taskStartRoute(): ApiRoute {
    return {
        path: "/tasks/start",
    };
}

export function taskComposePreviewRoute(): ApiRoute {
    return {
        path: "/authoring/task-compose/preview",
    };
}

function buildOptionalQuery(query: QueryParams | undefined): URLSearchParams | undefined {
    if (query === undefined) {
        return undefined;
    }

    return buildQueryParams(query);
}
