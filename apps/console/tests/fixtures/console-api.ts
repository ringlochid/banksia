import type { ConsoleMockScenario, TaskEventStreamFixture } from "../../src/mocks/handlers";
import type { components } from "../../src/api/generated/openapi";
import { createTaskStartPreview } from "./task-start";

export const TEST_API_BASE_URL = "http://127.0.0.1:18125";
export const TEST_TASK_ID = "task-console-fixture";
export const TEST_UPDATED_AT = "2026-06-29T14:00:00Z";

export interface TaskEventStreamFixtureOptions {
    readonly chunks?: readonly string[];
    readonly chunksByCursor?: Readonly<Record<string, readonly string[]>>;
    readonly cursorResetCursors?: readonly string[];
    readonly events?: readonly components["schemas"]["TaskEventRecord"][];
}

type TaskStartedEventRecord = Extract<
    components["schemas"]["TaskEventRecord"],
    { readonly event_type: "task_started" }
>;

export function createConsoleMockScenario(
    overrides: Partial<ConsoleMockScenario> = {},
): ConsoleMockScenario {
    const taskRead = createRuntimeFlowRead();
    const firstEvent = createTaskEventRecord({ event_id: "evt-001", event_seq: 1 });

    const scenario: ConsoleMockScenario = {
        ...createCommandRunScenario(),
        ...createDefinitionScenario(),
        ...createDraftScenario(),
        ...createHumanRequestScenario(),
        ...createTaskScenario(taskRead, firstEvent),
    };
    return {
        ...scenario,
        ...overrides,
    };
}

function createTaskScenario(
    taskRead: components["schemas"]["RuntimeFlowRead"],
    firstEvent: components["schemas"]["TaskEventRecord"],
): Pick<
    ConsoleMockScenario,
    | "snapshot"
    | "taskComposePreview"
    | "taskEvents"
    | "taskEventStream"
    | "taskList"
    | "taskRead"
    | "taskStart"
    | "trace"
> {
    return {
        snapshot: {
            current_paths: [],
            flow: taskRead,
            stream_head_event_id: firstEvent.event_id,
            top_actionable_items: [],
        },
        taskEvents: {
            items: [firstEvent],
            next_cursor: null,
            task_id: TEST_TASK_ID,
            through_event_id: firstEvent.event_id,
        },
        taskEventStream: createTaskEventStreamFixture({ events: [firstEvent] }),
        taskList: {
            items: [createRuntimeFlowSummary()],
            next_cursor: "cursor-next",
        },
        taskRead,
        taskComposePreview: createTaskStartPreview(),
        taskStart: createTaskStartResponse(),
        trace: {
            boundary_history: [],
            checkpoint_history: [],
            current_paths: [],
            dependency_edges: [],
            dispatch_history: [],
            graph_nodes: [],
            next_cursor: null,
            scope: "current",
            task_id: TEST_TASK_ID,
        },
    };
}

export function createRuntimeFlowSummaryList(
    items: readonly components["schemas"]["RuntimeFlowSummary"][] = [createRuntimeFlowSummary()],
    nextCursor: string | null = null,
): components["schemas"]["RuntimeFlowSummaryListResponse"] {
    return {
        items: [...items],
        next_cursor: nextCursor,
    };
}

export function createMixedRuntimeTaskRows(): readonly components["schemas"]["RuntimeFlowSummary"][] {
    return [
        createRuntimeFlowSummary({
            current_node_key: "copy_update",
            status: "running",
            task_id: "task-runtime-copy-refresh",
            task_summary: "Update the current task-control labels.",
            task_title: "Refresh runtime route copy",
            updated_at: "2026-06-29T13:54:00Z",
            workflow_key: "runtime_copy_refresh",
        }),
        createRuntimeFlowSummary({
            active_attempt_id: "attempt-definition-001",
            current_node_key: "boundary_check",
            status: "pending",
            task_id: "task-definition-boundaries",
            task_summary: "Confirm draft publish and Task Start stay separate.",
            task_title: "Check Definition Editor boundaries",
            updated_at: "2026-06-29T13:31:00Z",
            workflow_key: "definition-authoring-suite",
        }),
        createRuntimeFlowSummary({
            active_attempt_id: "attempt-runtime-handoff-001",
            current_node_key: "root_handoff",
            status: "running",
            task_id: "task-runtime-handoff",
            task_summary: "Gather the current summary and open blockers.",
            task_title: "Prepare runtime handoff",
            updated_at: "2026-06-29T13:12:00Z",
            workflow_key: "runtime_handoff",
        }),
        createRuntimeFlowSummary({
            active_attempt_id: "attempt-blocked-001",
            current_node_key: "navigation_copy_patch",
            status: "paused",
            task_id: "task-stale-navigation-labels",
            task_summary: "Replace retired runtime names.",
            task_title: "Fix stale navigation labels",
            updated_at: "2026-06-29T12:58:00Z",
            workflow_key: "shape_navigation_contract",
        }),
        createRuntimeFlowSummary({
            active_attempt_id: "attempt-paused-001",
            current_node_key: "command_runs_overflow",
            status: "paused",
            task_id: "task-command-run-overflow",
            task_summary: "Check long rows on narrow widths.",
            task_title: "Verify command-run overflow",
            updated_at: "2026-06-29T11:42:00Z",
            workflow_key: "task_control_suite",
        }),
        createRuntimeFlowSummary({
            active_attempt_id: "attempt-succeeded-001",
            current_node_key: "release_closure",
            status: "completed",
            task_id: "task-release-note",
            task_summary: "Archive accepted evidence.",
            task_title: "Close frontend planning note",
            updated_at: "2026-06-29T10:15:00Z",
            workflow_key: "frontend_console_continuation",
        }),
        createRuntimeFlowSummary({
            active_attempt_id: "attempt-cancelled-001",
            current_node_key: "root",
            status: "cancelled",
            task_id: "task-old-compose-refresh",
            task_summary: "Cancelled stale draft refresh after continuation superseded it.",
            task_title: "Retire old compose refresh",
            updated_at: "2026-06-29T09:45:00Z",
            workflow_key: "frontend_console_continuation",
        }),
    ];
}

export function createLongRuntimeTaskRow(): components["schemas"]["RuntimeFlowSummary"] {
    return createRuntimeFlowSummary({
        active_attempt_id: "attempt-with-a-long-but-real-controller-identifier-001",
        current_node_key: "verify_extremely_long_console_task_row_without_horizontal_overflow",
        status: "running",
        task_id: "task-long-row-runtime-list-validation",
        task_summary:
            "Validate a long but controller-backed summary that should wrap inside the scan-first task list without hiding the status, updated time, or open target.",
        task_title:
            "Validate long task title wrapping inside the scan-first Tasks route implementation",
        updated_at: "2026-06-29T08:30:00Z",
        workflow_key: "frontend_console_runtime_task_list_visual_validation",
    });
}

function createHumanRequestScenario(): Pick<
    ConsoleMockScenario,
    "humanRequestList" | "humanRequestResolve"
> {
    const humanRequest = createHumanRequestRead();
    return {
        humanRequestList: {
            items: [
                humanRequest,
                createHumanRequestRead({ kind: "approval", request_id: "hr-approval" }),
                createHumanRequestRead({ kind: "input", request_id: "hr-input" }),
                createHumanRequestRead({ kind: "review", request_id: "hr-review" }),
            ],
            task_id: TEST_TASK_ID,
        },
        humanRequestResolve: {
            resolution: {
                item_responses: {
                    "request-item-1": {
                        extra_notes: "Operator approved.",
                        selected_option: "approve",
                    },
                },
                request_id: humanRequest.request.request_id,
                resolution_kind: "answered",
                resolved_at: TEST_UPDATED_AT,
                resolved_by_actor_ref: "local_operator",
                resolved_by_surface: "control_ui",
                summary: "The operator approved the request.",
                task_id: TEST_TASK_ID,
            },
            task_id: TEST_TASK_ID,
        },
    };
}

function createCommandRunScenario(): Pick<
    ConsoleMockScenario,
    "commandRun" | "commandRunCancel" | "commandRunList" | "commandRunLog"
> {
    return {
        commandRun: createCommandRunRecord(),
        commandRunCancel: {
            run: createCommandRunListItem({ state: "cancellation_requested" }),
            task_id: TEST_TASK_ID,
        },
        commandRunList: {
            items: [
                createCommandRunListItem({ state: "pending_start" }),
                createCommandRunListItem({ run_id: "run-running", state: "running" }),
                createCommandRunListItem({ run_id: "run-cancel", state: "cancellation_requested" }),
                createCommandRunListItem({ run_id: "run-succeeded", state: "succeeded" }),
                createCommandRunListItem({ run_id: "run-failed", state: "failed" }),
                createCommandRunListItem({ run_id: "run-timeout", state: "timed_out" }),
                createCommandRunListItem({ run_id: "run-cancelled", state: "cancelled" }),
            ],
            next_cursor: null,
            task_id: TEST_TASK_ID,
        },
        commandRunLog: {
            content: "command output",
            log_ref: "tmp/command-runs/run-001.log",
            run_id: "run-001",
            task_id: TEST_TASK_ID,
        },
    };
}

function createDefinitionScenario(): Pick<
    ConsoleMockScenario,
    "definitionDetail" | "definitionLists" | "definitionVersions"
> {
    return {
        definitionDetail: createDefinitionRevisionDetail("role"),
        definitionLists: {
            policies: createDefinitionList("policy"),
            roles: createDefinitionList("role"),
            workflows: createDefinitionList("workflow"),
        },
        definitionVersions: createDefinitionVersions(),
    };
}

function createDraftScenario(): Pick<
    ConsoleMockScenario,
    "draftDetail" | "draftList" | "draftPublish" | "draftValidation"
> {
    const draftDetail = createDraftDetail();
    const draftValidation = createDraftValidation();
    return {
        draftDetail: {
            draft: draftDetail,
        },
        draftList: {
            items: [createDraftSummary()],
            next_cursor: null,
        },
        draftPublish: {
            key: "frontend_engineer",
            kind: "role",
            published_revision: {
                content_hash: "sha256:published",
                key: "frontend_engineer",
                kind: "role",
                revision_no: 3,
            },
            status: "published",
            validation: draftValidation,
        },
        draftValidation,
    };
}

export function createRuntimeFlowSummary(
    overrides: Partial<components["schemas"]["RuntimeFlowSummary"]> = {},
): components["schemas"]["RuntimeFlowSummary"] {
    return {
        active_assignment_id: "assignment-001",
        active_attempt_id: "attempt-001",
        active_flow_revision_id: "flow-revision-001",
        current_node_key: "implement_frontend_scope",
        status: "running",
        task_id: TEST_TASK_ID,
        task_summary: "Implement the console frontend foundation.",
        task_title: "Console Frontend Foundation",
        updated_at: TEST_UPDATED_AT,
        workflow_key: "frontend-console-continuation-delivery",
        workflow_manifest_ref: createWorkflowManifestRef(),
        ...overrides,
    };
}

export function createRuntimeFlowRead(
    overrides: Partial<components["schemas"]["RuntimeFlowRead"]> = {},
): components["schemas"]["RuntimeFlowRead"] {
    return {
        active_assignment_id: "assignment-001",
        active_attempt_id: "attempt-001",
        active_flow_revision_id: "flow-revision-001",
        control_revision: 1,
        current_command_run: null,
        current_dispatch: null,
        current_human_request: null,
        current_node_key: "implement_frontend_scope",
        current_plan: null,
        latest_dispatch_id: "dispatch-001",
        pause_reason: null,
        status: "running",
        task_id: TEST_TASK_ID,
        task_summary: "Implement the console frontend foundation.",
        task_title: "Console Frontend Foundation",
        updated_at: TEST_UPDATED_AT,
        waiting_cause: null,
        watchdog_recovery_count: 0,
        workflow_key: "frontend-console-continuation-delivery",
        workflow_manifest_ref: createWorkflowManifestRef(),
        ...overrides,
    };
}

export function createWorkflowManifestRef(): components["schemas"]["WorkflowManifestRef"] {
    return {
        description: "Workflow manifest",
        path: "_runtime/workflow-manifest.md",
    };
}

export function createTaskEventRecord(
    overrides: Partial<TaskStartedEventRecord> = {},
): TaskStartedEventRecord {
    const eventId = overrides.event_id ?? "evt-001";
    return {
        actor_ref: "controller",
        attempt_id: "attempt-001",
        dispatch_id: "dispatch-001",
        event_hash: `hash-${eventId}`,
        event_id: eventId,
        event_seq: overrides.event_seq ?? 1,
        event_source: "controller",
        event_type: "task_started",
        flow_revision_id: "flow-revision-001",
        node_key: "root",
        occurred_at: TEST_UPDATED_AT,
        payload: {
            compiled_plan_id: "compiled-plan-001",
            flow_id: "flow-001",
            manifest_ref: "_runtime/workflow-manifest.md",
            workflow_key: "frontend-console-continuation-delivery",
            workflow_revision_no: 1,
        },
        prev_event_hash: null,
        task_id: TEST_TASK_ID,
        ...overrides,
    };
}

export function createTaskEventStreamFixture(
    options: TaskEventStreamFixtureOptions = {},
): TaskEventStreamFixture {
    const events = options.events ?? [createTaskEventRecord()];
    return {
        chunks: options.chunks ?? createTaskEventStreamChunks(events),
        chunksByCursor: options.chunksByCursor ?? {},
        cursorResetCursors: options.cursorResetCursors ?? [],
    };
}

export function createTaskEventStreamChunks(
    events: readonly components["schemas"]["TaskEventRecord"][],
    options: { readonly splitFirstFrameAt?: number } = {},
): readonly string[] {
    const frames = events.map((event) => createTaskEventStreamFrame(event));
    const splitFirstFrameAt = options.splitFirstFrameAt;
    if (
        splitFirstFrameAt === undefined ||
        frames.length === 0 ||
        splitFirstFrameAt <= 0 ||
        splitFirstFrameAt >= frames[0].length
    ) {
        return frames;
    }

    const [firstFrame, ...remainingFrames] = frames;
    return [
        firstFrame.slice(0, splitFirstFrameAt),
        firstFrame.slice(splitFirstFrameAt),
        ...remainingFrames,
    ];
}

export function createTaskEventStreamFrame(
    event: components["schemas"]["TaskEventRecord"],
): string {
    return `id: ${event.event_id}\ndata: ${JSON.stringify(event)}\n\n`;
}

export function createHumanRequestRead(
    overrides: Partial<components["schemas"]["PendingHumanRequest"]> = {},
): components["schemas"]["HumanRequestRead"] {
    const kind = overrides.kind ?? "direction";
    return {
        request: {
            assignment_id: overrides.assignment_id ?? "assignment-001",
            attempt_id: overrides.attempt_id ?? "attempt-001",
            context_refs: [],
            flow_id: overrides.flow_id ?? "flow-001",
            items: [
                {
                    id: "request-item-1",
                    options:
                        kind === "approval"
                            ? [
                                  {
                                      description: "Approve the action.",
                                      id: "approve",
                                      title: "Approve",
                                  },
                                  {
                                      description: "Decline the action.",
                                      id: "decline",
                                      title: "Decline",
                                  },
                              ]
                            : [],
                    prompt: "Choose the next operator action.",
                    response_schema: kind === "input" ? { type: "object" } : null,
                },
            ],
            kind,
            opened_at: TEST_UPDATED_AT,
            request_id: "human-request-001",
            source_dispatch_id: "dispatch-001",
            status: "open",
            suggested_human_instruction: "Review the request and answer the current item.",
            summary: "Operator input is needed.",
            task_id: TEST_TASK_ID,
            timeout: {
                default_behavior: "block",
                due_at: "2026-06-29T16:00:00Z",
            },
            ...overrides,
        },
        resolution: null,
    };
}

export function createCommandRunListItem(
    overrides: Partial<components["schemas"]["CommandRunListItem"]> = {},
): components["schemas"]["CommandRunListItem"] {
    return {
        command: "make console-test-integration",
        created_at: TEST_UPDATED_AT,
        description: "Run console integration tests.",
        ended_at: null,
        exit_code: null,
        log_ref: "tmp/command-runs/run-001.log",
        run_id: "run-001",
        signal: null,
        started_at: TEST_UPDATED_AT,
        state: "running",
        summary: "Integration tests are running.",
        timeout_seconds: 120,
        workdir: "apps/console",
        ...overrides,
    };
}

export function createCommandRunRecord(
    overrides: Partial<components["schemas"]["CommandRunRecord"]> = {},
): components["schemas"]["CommandRunRecord"] {
    return {
        assignment_id: "assignment-001",
        attempt_id: "attempt-001",
        cancellation_requested_at: null,
        cancellation_requested_by_actor_ref: null,
        created_at: TEST_UPDATED_AT,
        due_at: "2026-06-29T14:02:00Z",
        ended_at: null,
        flow_id: "flow-001",
        ownership_revision: 1,
        request: {
            command: { command: "make console-test-integration", kind: "shell" },
            cwd: "apps/console",
            environment: [],
            expected_outputs: [],
            summary: "Run console integration tests.",
            timeout_seconds: 120,
        },
        run_id: "run-001",
        source_dispatch_id: "dispatch-001",
        started_at: TEST_UPDATED_AT,
        state: "running",
        stderr_log_ref: "tmp/command-runs/run-001.stderr.log",
        stdout_log_ref: "tmp/command-runs/run-001.stdout.log",
        successor_dispatch_id: null,
        task_id: TEST_TASK_ID,
        terminal_result: null,
        ...overrides,
    };
}

export function createDefinitionList(
    kind: components["schemas"]["DefinitionKind"],
): components["schemas"]["DefinitionSummaryListResponse"] {
    return {
        items: [
            {
                allowed_node_kinds: kind === "role" ? ["worker"] : null,
                applies_to: kind === "policy" ? ["worker"] : null,
                budget_spec: null,
                current_revision_no: 2,
                description: `${kind} definition`,
                key: `${kind}-fixture`,
                labels: ["console"],
                title: `${kind} fixture`,
                updated_at: TEST_UPDATED_AT,
            },
        ],
        kind,
        next_cursor: null,
    };
}

export function createDefinitionRevisionDetail(
    kind: components["schemas"]["DefinitionKind"],
): components["schemas"]["DefinitionRevisionDetailResponse"] {
    return {
        content: createDefinitionContent(kind),
        key: `${kind}-fixture`,
        recorded_by: null,
        revision_no: 2,
        updated_at: TEST_UPDATED_AT,
    };
}

export function createDefinitionVersions(): components["schemas"]["DefinitionRevisionHistoryResponse"] {
    return {
        current_revision_no: 2,
        items: [
            {
                recorded_by: null,
                revision_no: 2,
                updated_at: TEST_UPDATED_AT,
            },
        ],
        key: "role-fixture",
        kind: "role",
        next_cursor: null,
    };
}

export function createDraftSummary(): components["schemas"]["DefinitionDraftSummary"] {
    return {
        based_on: {
            content_hash: "sha256:baseline",
            revision_no: 2,
            source_path: null,
        },
        body_format: "yaml",
        content_hash: "sha256:draft",
        draft_path: "drafts/definitions/roles/frontend_engineer.yaml",
        key: "frontend_engineer",
        kind: "role",
        mode: "update",
        normalized_path: "drafts/definitions/_normalized/roles/frontend_engineer.json",
        status: "modified",
        updated_at: TEST_UPDATED_AT,
    };
}

export function createDraftDetail(): components["schemas"]["DefinitionDraftDetail"] {
    return {
        ...createDraftSummary(),
        baseline_body: "id: frontend_engineer\n",
        baseline_normalized_content: null,
        body: "id: frontend_engineer\ndescription: Frontend engineer\n",
        is_saved: true,
        normalized_content: null,
    };
}

export function createDraftValidation(): components["schemas"]["DefinitionDraftValidationResponse"] {
    return {
        errors: [],
        key: "frontend_engineer",
        kind: "role",
        status: "valid",
        warnings: [
            {
                code: "review_recommended",
                kind: "schema",
                message: "Review saved definition draft before publish.",
                path: "role.frontend_engineer",
            },
        ],
    };
}

export function createTaskStartRequest(): components["schemas"]["TaskStartRequest"] {
    return {
        roots: {
            workspace: {
                host_path: null,
                mode: "ensure_task_default",
            },
        },
        task: {
            instruction: "Run the console frontend continuation workflow.",
            key: "console-frontend-foundation",
            summary: "Implement API foundation.",
            title: "Console Frontend Foundation",
        },
        workflow: {
            key: "frontend-console-continuation-delivery",
        },
    };
}

export function createTaskStartResponse(): components["schemas"]["TaskStartResponse"] {
    return {
        active_flow_revision_id: "flow-revision-001",
        compiled_plan_id: "compiled-plan-001",
        flow_status: "running",
        task_id: TEST_TASK_ID,
        workflow_manifest_ref: createWorkflowManifestRef(),
    };
}

export function createOperationFailureBody(
    overrides: Partial<components["schemas"]["OperationFailure"]> = {},
): components["schemas"]["OperationFailure"] {
    return {
        code: "stale_flow_revision",
        field_path: null,
        ok: false,
        retryable: true,
        suggested_next_step: "Reread current task state and retry.",
        summary: "The active flow revision is stale.",
        ...overrides,
    };
}

function createDefinitionContent(
    kind: components["schemas"]["DefinitionKind"],
): components["schemas"]["DefinitionContent-Output"] {
    if (kind === "policy") {
        return {
            applies_to: ["worker"],
            capabilities: {
                command_run: "allow",
                human_request: {
                    allowed_kinds: ["approval"],
                    mode: "deny",
                },
            },
            description: "Policy fixture",
            id: "policy-fixture",
            instruction: "Follow policy.",
            labels: ["console"],
            title: "Policy Fixture",
        };
    }

    if (kind === "workflow") {
        return {
            description: "Workflow fixture",
            id: "workflow-fixture",
            root: {
                children: null,
                criteria: null,
                description: "Root node",
                instruction: "Coordinate the work.",
                kind: "root",
                node_key: "root",
                policy_id: "standard-parent",
                produces: null,
                provider: null,
                role_id: "root_planning_lead",
                title: "Root",
            },
        };
    }

    return {
        allowed_node_kinds: ["worker"],
        description: "Role fixture",
        id: "role-fixture",
        instruction: "Implement the assigned scope.",
        labels: ["console"],
        title: "Role Fixture",
    };
}
