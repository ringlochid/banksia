import type { components } from "../../src/api/generated/openapi";
import { TEST_UPDATED_AT, createCommandRunListItem } from "./console-api";

export const COMMAND_RUN_TASK_ID = "task-runtime-copy-refresh";
export const COMMAND_RUN_LOG_CONTENT =
    "$ pytest apps/api/tests/unit/runtime_prompt_rendering -q\nF.F\nAssertionError: continuation context missing terminal command-run summary";

type CommandRunState = components["schemas"]["CommandRunState"];

const stateRuns: readonly {
    readonly command: string;
    readonly description: string;
    readonly runId: string;
    readonly state: CommandRunState;
    readonly summary: string;
}[] = [
    {
        command: "make test-api-unit",
        description: "Run focused runtime route tests.",
        runId: "run-queued",
        state: "pending_start",
        summary: "Waiting for the controller runner to start.",
    },
    {
        command: "make console-test-integration",
        description: "Verify command-run runner behavior.",
        runId: "run-running",
        state: "running",
        summary: "Command produced output.",
    },
    {
        command: "make console-build",
        description: "Cancel the superseded route-test run.",
        runId: "run-cancel-requested",
        state: "cancellation_requested",
        summary: "Cancel request accepted.",
    },
    {
        command: "make console-lint",
        description: "Check runtime lint gates.",
        runId: "run-succeeded",
        state: "succeeded",
        summary: "Runtime command-run files passed lint.",
    },
    {
        command: "pytest apps/api/tests/unit/runtime_prompt_rendering -q",
        description: "Check prompt continuation rendering.",
        runId: "run-failed",
        state: "failed",
        summary: "Two continuation-context assertions failed.",
    },
    {
        command: "make console-e2e",
        description: "Capture browser evidence.",
        runId: "run-timed-out",
        state: "timed_out",
        summary: "Browser evidence timed out before completion.",
    },
    {
        command: "make obsolete-check",
        description: "Retire old proof lane.",
        runId: "run-cancelled",
        state: "cancelled",
        summary: "The controller cancelled this run.",
    },
    {
        command: "make lost-owner-check",
        description: "Inspect a command whose process ownership was lost.",
        runId: "run-abandoned",
        state: "abandoned",
        summary: "The controller could not prove process ownership after restart.",
    },
];

export function createCommandRunPageList(
    overrides: Partial<components["schemas"]["CommandRunListResponse"]> = {},
): components["schemas"]["CommandRunListResponse"] {
    return {
        items: stateRuns.map((run) =>
            createCommandRunListItem({
                command: run.command,
                description: run.description,
                ended_at:
                    run.state === "pending_start" ||
                    run.state === "running" ||
                    run.state === "cancellation_requested"
                        ? null
                        : "2026-06-29T14:26:00Z",
                exit_code: run.state === "failed" ? 1 : run.state === "succeeded" ? 0 : null,
                log_ref:
                    run.state === "pending_start" || run.runId === "run-cancelled"
                        ? null
                        : `outputs/command-runs/${run.runId}.log`,
                run_id: run.runId,
                state: run.state,
                summary: run.summary,
                workdir: "apps/api",
            }),
        ),
        next_cursor: "cursor-command-runs-page-2",
        task_id: COMMAND_RUN_TASK_ID,
        ...overrides,
    };
}

export function createCommandRunDetail(
    runId: string,
    overrides: Partial<components["schemas"]["CommandRunRecord"]> = {},
): components["schemas"]["CommandRunRecord"] {
    const base =
        stateRuns.find((run) => run.runId === runId) ??
        stateRuns.find((run) => run.runId === "run-failed") ??
        stateRuns[0];
    const isTerminal =
        base.state === "succeeded" ||
        base.state === "failed" ||
        base.state === "timed_out" ||
        base.state === "cancelled" ||
        base.state === "abandoned";
    const hasLogs = base.state === "pending_start" || base.runId === "run-cancelled" ? false : true;
    const stdoutLogRef = hasLogs ? `outputs/command-runs/${base.runId}.stdout.log` : null;
    const stderrLogRef = hasLogs ? `outputs/command-runs/${base.runId}.stderr.log` : null;

    return {
        assignment_id: `assignment-${base.runId}`,
        attempt_id: `attempt-${base.runId}`,
        cancellation_requested_at:
            base.state === "cancellation_requested" ? "2026-06-29T14:18:00Z" : null,
        cancellation_requested_by_actor_ref:
            base.state === "cancellation_requested" ? "local_operator" : null,
        created_at: TEST_UPDATED_AT,
        due_at: isTerminal ? null : "2026-06-29T14:30:00Z",
        ended_at: isTerminal ? "2026-06-29T14:26:00Z" : null,
        flow_id: "flow-command-runs",
        ownership_revision: base.state === "pending_start" ? 0 : 1,
        request: {
            command: { command: base.command, kind: "shell" },
            cwd: "apps/api",
            environment: [],
            expected_outputs:
                base.runId === "run-failed"
                    ? [
                          {
                              description: "Focused prompt-rendering test report.",
                              path: "tmp/pytest-command-run.txt",
                          },
                      ]
                    : [],
            summary: base.description,
            timeout_seconds: 120,
        },
        run_id: base.runId,
        source_dispatch_id: `dispatch-${base.runId}`,
        started_at: base.state === "pending_start" ? null : TEST_UPDATED_AT,
        state: base.state,
        stderr_log_ref: stderrLogRef,
        stdout_log_ref: stdoutLogRef,
        successor_dispatch_id:
            base.state === "succeeded" ? `dispatch-successor-${base.runId}` : null,
        task_id: COMMAND_RUN_TASK_ID,
        terminal_result: isTerminal
            ? {
                  ended_at: "2026-06-29T14:26:00Z",
                  exit_code: base.state === "failed" ? 1 : base.state === "succeeded" ? 0 : null,
                  failure_code: base.state === "abandoned" ? "command_ownership_lost" : null,
                  started_at: TEST_UPDATED_AT,
                  state: base.state,
                  stderr_log_ref: stderrLogRef,
                  stdout_log_ref: stdoutLogRef,
                  summary: base.summary,
                  terminal_actor_ref: null,
                  terminal_event_source: "process_owner",
              }
            : null,
        ...overrides,
    };
}

export function createCommandRunDetailMap(): Readonly<
    Record<string, components["schemas"]["CommandRunRecord"]>
> {
    return Object.fromEntries(
        stateRuns.map((run) => [run.runId, createCommandRunDetail(run.runId)]),
    );
}

export function createCommandRunLogRead(
    runId = "run-failed",
    content = COMMAND_RUN_LOG_CONTENT,
): components["schemas"]["CommandRunLogReadResponse"] {
    return {
        content,
        log_ref:
            runId === "run-failed" || runId === "run-timed-out"
                ? `outputs/command-runs/${runId}.stderr.log`
                : `outputs/command-runs/${runId}.stdout.log`,
        run_id: runId,
        task_id: COMMAND_RUN_TASK_ID,
    };
}

export function createCommandRunSecondPage(): components["schemas"]["CommandRunListResponse"] {
    return {
        items: [
            createCommandRunListItem({
                command: "make console-openapi-check",
                description: "Check generated OpenAPI drift.",
                log_ref: "outputs/command-runs/run-openapi.log",
                run_id: "run-openapi",
                state: "succeeded",
                summary: "OpenAPI generated types are current.",
                workdir: "apps/console",
            }),
        ],
        next_cursor: null,
        task_id: COMMAND_RUN_TASK_ID,
    };
}
