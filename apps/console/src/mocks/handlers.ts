import { http, HttpResponse, type HttpHandler, type JsonBodyType } from "msw";

import type { components } from "../api/generated/openapi";

export interface TaskEventStreamFixture {
    readonly chunks: readonly string[];
    readonly chunksByCursor: Readonly<Record<string, readonly string[]>>;
    readonly cursorResetCursors: readonly string[];
}

export interface ConsoleMockScenario {
    readonly commandRun: components["schemas"]["CommandRunRecord"];
    readonly commandRunCancel: components["schemas"]["CommandRunCancelResponse"];
    readonly commandRunCancelByRun?: Readonly<
        Record<string, components["schemas"]["CommandRunCancelResponse"]>
    >;
    readonly commandRunDetails?: Readonly<
        Record<string, components["schemas"]["CommandRunRecord"]>
    >;
    readonly commandRunList: components["schemas"]["CommandRunListResponse"];
    readonly commandRunListPages?: Readonly<
        Record<string, components["schemas"]["CommandRunListResponse"]>
    >;
    readonly commandRunLog: components["schemas"]["CommandRunLogReadResponse"];
    readonly commandRunLogs?: Readonly<
        Record<string, components["schemas"]["CommandRunLogReadResponse"]>
    >;
    readonly definitionDetail: components["schemas"]["DefinitionRevisionDetailResponse"];
    readonly definitionDetails?: Readonly<
        Record<string, components["schemas"]["DefinitionRevisionDetailResponse"]>
    >;
    readonly definitionLists: {
        readonly policies: components["schemas"]["DefinitionSummaryListResponse"];
        readonly roles: components["schemas"]["DefinitionSummaryListResponse"];
        readonly workflows: components["schemas"]["DefinitionSummaryListResponse"];
    };
    readonly definitionListPages?: {
        readonly policies?: Readonly<
            Record<string, components["schemas"]["DefinitionSummaryListResponse"]>
        >;
        readonly roles?: Readonly<
            Record<string, components["schemas"]["DefinitionSummaryListResponse"]>
        >;
        readonly workflows?: Readonly<
            Record<string, components["schemas"]["DefinitionSummaryListResponse"]>
        >;
    };
    readonly definitionVersions: components["schemas"]["DefinitionRevisionHistoryResponse"];
    readonly definitionVersionPages?: Readonly<
        Record<
            string,
            Readonly<Record<string, components["schemas"]["DefinitionRevisionHistoryResponse"]>>
        >
    >;
    readonly definitionVersionsByDefinition?: Readonly<
        Record<string, components["schemas"]["DefinitionRevisionHistoryResponse"]>
    >;
    readonly draftDetail: components["schemas"]["DefinitionDraftDetailResponse"];
    readonly draftList: components["schemas"]["DefinitionDraftListResponse"];
    readonly draftPublish: components["schemas"]["DefinitionDraftPublishResponse"];
    readonly draftValidation: components["schemas"]["DefinitionDraftValidationResponse"];
    readonly humanRequestList: components["schemas"]["HumanRequestListResponse"];
    readonly humanRequestResolve: components["schemas"]["HumanRequestResolveResponse"];
    readonly snapshot: components["schemas"]["OperatorFlowSnapshotResponse"];
    readonly taskEvents: components["schemas"]["TaskEventListResponse"];
    readonly taskEventStream: TaskEventStreamFixture;
    readonly taskList: components["schemas"]["RuntimeFlowSummaryListResponse"];
    readonly taskListPages?: Readonly<
        Record<string, components["schemas"]["RuntimeFlowSummaryListResponse"]>
    >;
    readonly taskRead: components["schemas"]["RuntimeFlowRead"];
    readonly taskComposePreview: components["schemas"]["TaskComposePreviewResponse"];
    readonly taskStart: components["schemas"]["TaskStartResponse"];
    readonly trace: components["schemas"]["OperatorFlowTraceResponse"];
}

export function createConsoleApiHandlers(scenario: ConsoleMockScenario): readonly HttpHandler[] {
    return [
        ...createTaskHandlers(scenario),
        ...createHumanRequestHandlers(scenario),
        ...createCommandRunHandlers(scenario),
        ...createDefinitionHandlers(scenario),
        ...createDraftAuthoringHandlers(scenario),
        http.post("*/authoring/task-compose/preview", ({ request }) =>
            guardedJson(request, scenario, scenario.taskComposePreview),
        ),
        http.post("*/tasks/start", ({ request }) =>
            guardedJson(request, scenario, scenario.taskStart),
        ),
    ];
}

function createTaskHandlers(scenario: ConsoleMockScenario): readonly HttpHandler[] {
    return [
        http.get("*/runtime/tasks", ({ request }) =>
            guardedJson(request, scenario, taskListForRequest(request, scenario)),
        ),
        http.get("*/runtime/tasks/:taskId", ({ request }) =>
            guardedJson(request, scenario, scenario.taskRead),
        ),
        http.get("*/control/tasks/:taskId", ({ request }) =>
            guardedJson(request, scenario, scenario.taskRead),
        ),
        http.post("*/control/tasks/:taskId/pause", ({ request }) =>
            guardedJson(request, scenario, { flow: scenario.taskRead }),
        ),
        http.post("*/control/tasks/:taskId/continue", ({ request }) =>
            guardedJson(request, scenario, scenario.taskRead),
        ),
        http.post("*/control/tasks/:taskId/cancel", ({ request }) =>
            guardedJson(request, scenario, scenario.taskRead),
        ),
        http.get("*/control/tasks/:taskId/snapshot", ({ request }) =>
            guardedJson(request, scenario, scenario.snapshot),
        ),
        http.get("*/control/tasks/:taskId/trace", ({ request }) =>
            guardedJson(request, scenario, scenario.trace),
        ),
        http.get("*/control/tasks/:taskId/events/stream", ({ request }) =>
            guardedTaskEventStream(request, scenario),
        ),
        http.get("*/control/tasks/:taskId/events", ({ request }) =>
            guardedJson(request, scenario, scenario.taskEvents),
        ),
    ];
}

function taskListForRequest(
    request: Request,
    scenario: ConsoleMockScenario,
): components["schemas"]["RuntimeFlowSummaryListResponse"] {
    const cursor = new URL(request.url).searchParams.get("cursor");
    if (cursor === null) {
        return scenario.taskList;
    }

    return scenario.taskListPages?.[cursor] ?? scenario.taskList;
}

function createHumanRequestHandlers(scenario: ConsoleMockScenario): readonly HttpHandler[] {
    return [
        http.get("*/control/tasks/:taskId/human-requests", ({ request }) =>
            guardedJson(request, scenario, scenario.humanRequestList),
        ),
        http.post("*/control/tasks/:taskId/human-requests/:requestId/resolve", ({ request }) =>
            guardedJson(request, scenario, scenario.humanRequestResolve),
        ),
    ];
}

function createCommandRunHandlers(scenario: ConsoleMockScenario): readonly HttpHandler[] {
    return [
        http.get("*/control/tasks/:taskId/command-runs", ({ request }) =>
            guardedJson(request, scenario, commandRunListForRequest(request, scenario)),
        ),
        http.get("*/control/tasks/:taskId/command-runs/:runId", ({ params, request }) =>
            guardedJson(request, scenario, commandRunDetailForRequest(params.runId, scenario)),
        ),
        http.post("*/control/tasks/:taskId/command-runs/:runId/cancel", ({ params, request }) =>
            guardedJson(request, scenario, commandRunCancelForRequest(params.runId, scenario)),
        ),
        http.get("*/control/tasks/:taskId/command-runs/:runId/log", ({ params, request }) =>
            guardedJson(request, scenario, commandRunLogForRequest(params.runId, scenario)),
        ),
    ];
}

function commandRunListForRequest(
    request: Request,
    scenario: ConsoleMockScenario,
): components["schemas"]["CommandRunListResponse"] {
    const cursor = new URL(request.url).searchParams.get("cursor");
    if (cursor === null) {
        return scenario.commandRunList;
    }

    return scenario.commandRunListPages?.[cursor] ?? scenario.commandRunList;
}

function commandRunDetailForRequest(
    runId: unknown,
    scenario: ConsoleMockScenario,
): components["schemas"]["CommandRunRecord"] {
    const normalizedRunId = normalizePathParam(runId);
    if (normalizedRunId !== null) {
        return scenario.commandRunDetails?.[normalizedRunId] ?? scenario.commandRun;
    }

    return scenario.commandRun;
}

function commandRunCancelForRequest(
    runId: unknown,
    scenario: ConsoleMockScenario,
): components["schemas"]["CommandRunCancelResponse"] {
    const normalizedRunId = normalizePathParam(runId);
    if (normalizedRunId !== null) {
        return scenario.commandRunCancelByRun?.[normalizedRunId] ?? scenario.commandRunCancel;
    }

    return scenario.commandRunCancel;
}

function commandRunLogForRequest(
    runId: unknown,
    scenario: ConsoleMockScenario,
): components["schemas"]["CommandRunLogReadResponse"] {
    const normalizedRunId = normalizePathParam(runId);
    if (normalizedRunId !== null) {
        return scenario.commandRunLogs?.[normalizedRunId] ?? scenario.commandRunLog;
    }

    return scenario.commandRunLog;
}

function normalizePathParam(value: unknown): string | null {
    if (typeof value === "string") {
        return value;
    }

    if (Array.isArray(value) && typeof value[0] === "string") {
        return value[0];
    }

    return null;
}

function createDefinitionHandlers(scenario: ConsoleMockScenario): readonly HttpHandler[] {
    return [
        http.get("*/definitions/roles", ({ request }) =>
            guardedJson(request, scenario, definitionListForRequest("roles", request, scenario)),
        ),
        http.get("*/definitions/policies", ({ request }) =>
            guardedJson(request, scenario, definitionListForRequest("policies", request, scenario)),
        ),
        http.get("*/definitions/workflows", ({ request }) =>
            guardedJson(
                request,
                scenario,
                definitionListForRequest("workflows", request, scenario),
            ),
        ),
        http.get("*/definitions/:kind/:key", ({ params, request }) =>
            guardedJson(
                request,
                scenario,
                definitionDetailForRequest(params.kind, params.key, scenario),
            ),
        ),
        http.get("*/definitions/:kind/:key/versions", ({ params, request }) =>
            guardedJson(
                request,
                scenario,
                definitionVersionsForRequest(params.kind, params.key, request, scenario),
            ),
        ),
    ];
}

function definitionListForRequest(
    kind: "policies" | "roles" | "workflows",
    request: Request,
    scenario: ConsoleMockScenario,
): components["schemas"]["DefinitionSummaryListResponse"] {
    const url = new URL(request.url);
    const cursor = url.searchParams.get("cursor");
    const explicitPages = scenario.definitionListPages?.[kind];
    if (cursor !== null && explicitPages !== undefined) {
        return explicitPages[cursor] ?? scenario.definitionLists[kind];
    }

    return filterDefinitionListForRequest(scenario.definitionLists[kind], url);
}

function filterDefinitionListForRequest(
    list: components["schemas"]["DefinitionSummaryListResponse"],
    url: URL,
): components["schemas"]["DefinitionSummaryListResponse"] {
    const query = (url.searchParams.get("q") ?? "").trim().toLowerCase();
    const limit = Number(url.searchParams.get("limit"));
    const offset = parseDefinitionListOffset(url.searchParams.get("cursor"));
    const filteredItems =
        query.length === 0
            ? list.items
            : list.items.filter((item) => definitionSummaryMatchesQuery(item, query));
    const pageLimit = Number.isFinite(limit) && limit > 0 ? limit : filteredItems.length;
    const selectedItems = filteredItems.slice(offset, offset + pageLimit + 1);
    const limitedItems = selectedItems.slice(0, pageLimit);

    return {
        ...list,
        items: [...limitedItems],
        next_cursor: selectedItems.length > pageLimit ? String(offset + pageLimit) : null,
    };
}

function parseDefinitionListOffset(cursor: string | null): number {
    if (cursor === null) {
        return 0;
    }

    const offset = Number(cursor);
    return Number.isInteger(offset) && offset >= 0 ? offset : 0;
}

function definitionSummaryMatchesQuery(
    item: components["schemas"]["DefinitionSummaryRead"],
    query: string,
): boolean {
    const searchableFields = [item.key, item.description ?? "", item.title ?? ""];

    return searchableFields.some((field) => field.toLowerCase().includes(query));
}

function definitionDetailForRequest(
    kind: unknown,
    key: unknown,
    scenario: ConsoleMockScenario,
): components["schemas"]["DefinitionRevisionDetailResponse"] {
    const lookupKey = definitionLookupKey(kind, key);
    if (lookupKey !== null) {
        return scenario.definitionDetails?.[lookupKey] ?? scenario.definitionDetail;
    }

    return scenario.definitionDetail;
}

function definitionVersionsForRequest(
    kind: unknown,
    key: unknown,
    request: Request,
    scenario: ConsoleMockScenario,
): components["schemas"]["DefinitionRevisionHistoryResponse"] {
    const lookupKey = definitionLookupKey(kind, key);
    if (lookupKey === null) {
        return scenario.definitionVersions;
    }

    const cursor = new URL(request.url).searchParams.get("cursor");
    if (cursor !== null) {
        return (
            scenario.definitionVersionPages?.[lookupKey]?.[cursor] ??
            scenario.definitionVersionsByDefinition?.[lookupKey] ??
            scenario.definitionVersions
        );
    }

    return scenario.definitionVersionsByDefinition?.[lookupKey] ?? scenario.definitionVersions;
}

function definitionLookupKey(kind: unknown, key: unknown): string | null {
    const normalizedKind = normalizePathParam(kind);
    const normalizedKey = normalizePathParam(key);
    if (normalizedKind === null || normalizedKey === null) {
        return null;
    }

    return `${normalizedKind}:${normalizedKey}`;
}

function createDraftAuthoringHandlers(scenario: ConsoleMockScenario): readonly HttpHandler[] {
    return [
        http.get("*/authoring/definition-drafts", ({ request }) =>
            guardedJson(request, scenario, scenario.draftList),
        ),
        http.post("*/authoring/definition-drafts", async ({ request }) => {
            const body =
                (await request.json()) as components["schemas"]["DefinitionDraftCreateRequest"];
            return HttpResponse.json({
                draft: {
                    ...scenario.draftDetail.draft,
                    body: body.body ?? scenario.draftDetail.draft.body,
                    is_saved: true,
                    key: body.key,
                    kind: body.kind,
                    mode: body.mode,
                    status: body.mode === "create" ? "new" : "modified",
                },
            } satisfies components["schemas"]["DefinitionDraftDetailResponse"]);
        }),
        http.get("*/authoring/definitions/:kind/:key/draft", ({ params, request }) =>
            guardedJson(
                request,
                scenario,
                draftDetailForRequest(params.kind, params.key, scenario),
            ),
        ),
        http.put("*/authoring/definitions/:kind/:key/draft", async ({ params, request }) => {
            const body =
                (await request.json()) as components["schemas"]["DefinitionDraftWriteRequest"];
            return HttpResponse.json(
                draftDetailForRequest(params.kind, params.key, scenario, body.body),
            );
        }),
        http.post(
            "*/authoring/definitions/:kind/:key/draft/replace-current",
            ({ params, request }) =>
                guardedJson(
                    request,
                    scenario,
                    draftDetailForRequest(params.kind, params.key, scenario),
                ),
        ),
        http.delete("*/authoring/definitions/:kind/:key/draft", ({ request }) =>
            guardedEmpty(request, scenario),
        ),
        http.post("*/authoring/definitions/:kind/:key/draft/validate", ({ request }) =>
            guardedJson(request, scenario, scenario.draftValidation),
        ),
        http.post("*/authoring/definitions/:kind/:key/draft/publish", ({ request }) =>
            guardedJson(request, scenario, scenario.draftPublish),
        ),
    ];
}

function draftDetailForRequest(
    kind: unknown,
    key: unknown,
    scenario: ConsoleMockScenario,
    body?: string,
): components["schemas"]["DefinitionDraftDetailResponse"] {
    const normalizedKind = normalizePathParam(kind);
    const normalizedKey = normalizePathParam(key);
    if (normalizedKind === null || normalizedKey === null || !isDefinitionKind(normalizedKind)) {
        return scenario.draftDetail;
    }

    return {
        draft: {
            ...scenario.draftDetail.draft,
            body: body ?? scenario.draftDetail.draft.body,
            is_saved: body === undefined ? scenario.draftDetail.draft.is_saved : true,
            key: normalizedKey,
            kind: normalizedKind,
            status: body === undefined ? scenario.draftDetail.draft.status : "modified",
        },
    };
}

function isDefinitionKind(value: string): value is components["schemas"]["DefinitionKind"] {
    return value === "policy" || value === "role" || value === "workflow";
}

function guardedEmpty(_request: Request, _scenario: ConsoleMockScenario): Response {
    void _request;
    void _scenario;
    return new HttpResponse(null, { status: 204 });
}

function guardedJson(
    _request: Request,
    _scenario: ConsoleMockScenario,
    body: JsonBodyType,
): Response {
    return HttpResponse.json(body);
}

function guardedTaskEventStream(request: Request, scenario: ConsoleMockScenario): Response {
    const cursor = new URL(request.url).searchParams.get("cursor");
    if (cursor !== null && scenario.taskEventStream.cursorResetCursors.includes(cursor)) {
        return operationFailureResponse({
            code: "cursor_reset_required",
            status: 410,
            summary: "The stream cursor must be reset.",
            suggestedNextStep:
                "Refetch current task truth through the control API, then reconnect without the stale task-event cursor.",
        });
    }

    const chunks =
        cursor === null
            ? scenario.taskEventStream.chunks
            : (scenario.taskEventStream.chunksByCursor[cursor] ?? scenario.taskEventStream.chunks);

    return new HttpResponse(textStream(chunks), {
        headers: { "Content-Type": "text/event-stream" },
    });
}

function operationFailureResponse({
    code,
    status,
    summary,
    suggestedNextStep,
}: {
    readonly code: components["schemas"]["OperationFailureCode"];
    readonly status: number;
    readonly summary: string;
    readonly suggestedNextStep: string;
}): Response {
    return HttpResponse.json(
        {
            code,
            field_path: null,
            ok: false,
            retryable: false,
            suggested_next_step: suggestedNextStep,
            summary,
        },
        { status },
    );
}

function textStream(chunks: readonly string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    return new ReadableStream<Uint8Array>({
        start(controller) {
            for (const chunk of chunks) {
                controller.enqueue(encoder.encode(chunk));
            }
            controller.close();
        },
    });
}
