# Troubleshooting

Begin with passive readback:

```bash
banksia status
banksia config path
banksia config show
banksia providers status
banksia service status
```

Use `--json` where the command offers it when collecting diagnostics. Use the root `--debug` flag only when a traceback is useful. A browser or provider process is not controller truth; inspect the current Workflow or Task before choosing a mutation.

Each symptom below separates meaning, safe checks, the next legal action, controller consequences, and defect evidence.

## Initialization fails or the default workspace is invalid

**Meaning.** The selected configuration already exists without `--force`, or the configured/default workspace is blank, relative, missing, or not a directory. HTTP, Console, and Operator cannot omit `workspace` unless `paths.workspace` is valid.

**Safe checks.**

```bash
banksia config path
banksia config show
banksia status
```

Confirm that the shown workspace is the intended existing absolute directory. Also check whether `BANKSIA_CONTROLLER_WORKSPACE` is overriding TOML.

**Legal action.** For a new configuration, run:

```bash
banksia init --workspace /absolute/path/to/project
```

For an existing configuration, correct `[paths].workspace` or the environment override explicitly. Use `init --force` only when you intend to replace the managed configuration; it preserves a valid existing workspace unless a replacement is supplied.

**Controller truth.** A preflight rejection creates no Task and performs no workspace admission. Existing controller history is unchanged.

**Report a defect when.** The effective readback differs from documented precedence, a valid existing absolute directory is rejected, or configuration changes after a rejected preflight. Include redacted `config show` output and the exact environment variable names, never their secrets.

## A provider is unavailable or authentication is missing

**Meaning.** The requested provider route is disabled, unconfigured, unauthenticated, unavailable, or incompatible with the explicit model, effort, or sandbox request. Banksia does not silently fall back.

**Safe checks.**

```bash
banksia providers status
banksia providers check codex
```

`providers status` is passive. `providers check NAME` actively tests that route and returns exit `1` when it is not ready.

For a Claude Member whose effective network setting is `deny` on Linux or WSL2, also check the sandbox host prerequisites:

```bash
command -v bwrap
command -v socat
```

**Legal action.**

```bash
banksia providers configure codex
banksia providers login codex --method subscription
banksia providers set-default codex
banksia providers check codex
```

Choose the real provider and authentication method. For OpenClaw, also verify the user-operated CLI, Gateway URL/profile, authentication mode, Gateway health, provider-visible workspace, and source access outside Banksia.

For Claude deny-network execution on Ubuntu or Debian, install the missing host packages:

```bash
sudo apt-get install bubblewrap socat
```

On Ubuntu 24.04 or later, an installed `bwrap` may still need the AppArmor setup documented in the [Claude Code sandboxing guide](https://code.claude.com/docs/en/sandboxing). Banksia configures this path to fail closed: do not widen network access merely to bypass a missing sandbox unless that policy change is intentional.

**Controller truth.** A Task-start provider rejection commits no Task. A provider interruption after acceptance does not erase the Task; current controller state determines recovery or attention.

**Report a defect when.** `providers check` reports ready but an unchanged supported request cannot start, or the explicit route changes without a configuration mutation. Include provider kind, redacted status/check output, Banksia version, and timestamps.

## A Workflow draft is invalid or stale

**Meaning.** Invalid means schema or semantic validation found issues. Stale means another edit advanced the draft ETag before your mutation. Validation is not publication.

**Safe checks.**

- Refetch the Workflow/draft in Workflow Studio or through `GET /api/workflows/{workflow_id}`.
- Read the current ETag and validation issues.
- Validate in Workflow Studio or against the maintained public schema. Do not run file import to replace the active draft unless you have its exact current ETag.

**Legal action.** Correct the named validation paths. For stale state, compare your intended edit with current controller truth, then submit it against the new ETag. Do not guess an ETag or replay an entire old draft.

**Controller truth.** Rejected validation changes nothing. A stale mutation does not overwrite the winning draft. Published revisions remain immutable.

**Report a defect when.** A document accepted by the maintained public schema is rejected by the shipped ingestion path without a documented semantic issue, or a stale edit overwrites current state. Include a minimal secret-free Workflow and the issue paths.

## A Workflow cannot publish or a Task cannot start

**Meaning.** Publication may be blocked by invalid or stale draft truth. Task start additionally requires a published revision, a valid workspace, provider resolution, legal capabilities, and valid existing file references.

**Safe checks.**

- Read Workflow state and the current publication/draft ETag.
- Validate the draft before publishing.
- Run `banksia config show` and `banksia providers status`.
- Confirm every referenced path is a regular workspace-relative file with no symbolic-link component.
- Confirm the controller is reachable before `banksia task start`.

**Legal action.** Publish the current validated draft with its current ETag, or select an existing published Starter. Correct the exact rejected workspace, provider, capability, or file field and submit one new start request.

**Controller truth.** Import only creates a draft. Publish creates an immutable revision. A rejected start creates no Task, Task directory, file-reference record, or provider work. A `202` accepted receipt means the Task committed; provider startup is still asynchronous.

**Report a defect when.** Admission leaves an unmarked unexplained Task directory, returns acceptance without a readable Task, or starts a revision different from the receipt.

## A run needs your attention

**Meaning.** The semantic Task view may contain an open Human Request, a failed Action, or a blocked Result. `waiting_for_you` is not evidence that work was lost.

**Safe checks.** Open the current Task detail and read:

- attention title and summary;
- the requesting Member;
- referenced files;
- current action and confirmation consequence; and
- current Human Request or Command Run state.

**Legal action.** Answer each current Human Request item using its accepted typed shape, cancel it only when that action is offered, inspect failed Action output, or commission new work after a blocked Result. Use only the current opaque action ID.

**Controller truth.** An open Human Request is a persisted Attempt-local wait. An accepted answer/cancellation commits first; continuation opens separately. A blocked root Result is terminal history, not a retry prompt.

**Report a defect when.** Attention has no legal action or explanation, accepted input disappears after refetch, or a stale action succeeds against a different current request.

## A Command Run is still working, failed, or timed out

**Meaning.** The Action has its own managed lifecycle. `queued`, `running`, and `cancelling` are nonterminal. `succeeded`, `failed`, `timed_out`, and `cancelled` are terminal product states.

**Safe checks.**

- Read the Command Run state from Task detail or its exact route.
- Follow bounded output pages using only `next_cursor`.
- Open the full workspace log when needed:

```text
.banksia/t_<id>/command-runs/c_<id>/output.log
```

Check `output_complete`, `is_missing`, `is_changed`, and `is_bounded` before interpreting a partial page.

**Legal action.** Wait while the Action is active. Request cancellation only when the current readback offers a cancel action. After terminal failure or timeout, let the controller resume the waiting Member; that Member decides whether new work is justified.

**Controller truth.** Command state, terminal result, wait, and continuation are controller records. The full log is a loose workspace file. Missing or changed bytes are reported honestly and are not reconstructed from bounded database output.

**Report a defect when.** Terminal state has no continuation after recovery, output facts contradict the current log without reporting change, or a cancelled process remains controller-owned as running.

## A provider stopped or a run appears stuck

**Meaning.** The provider may have stopped after a successful authority-transferring action, the controller may be waiting for a Wave or external result, the service may be down, or a current Dispatch may need bounded startup/watchdog recovery.

**Safe checks.**

```bash
banksia status
banksia service status
curl --fail http://127.0.0.1:18125/healthz
curl --fail http://127.0.0.1:18125/readyz
```

Replace the example health host and port with the effective values from `banksia config show`. Then refetch the Task. Look for current attention, legal controls, Activity, Result, and whether all members of a visible delegation have returned. A blocked child is a terminal Wave result; siblings still collect.

**Legal action.** If the service is actually stopped, start it. If the current Task offers pause, resume, or cancel, use that exact action. Otherwise allow startup recovery to reconcile committed sources. Do not manually repeat a provider request, answer, command, or Task start merely because a process window closed.

**Controller truth.** Provider terminal success is not Assignment success. Committed waits and accepted Checkpoints survive process/browser interruption. Bounded recovery may restart the same stored provider request, but it cannot promise exactly-once external effects or invent a Result.

**Report a defect when.** Readiness is green and current controller truth has no legal progress path after its documented recovery window. Include Task ID, semantic state, timestamps, Activity, and protected trace only when authorized.

## A referenced file is missing or changed

**Meaning.** A file reference records a path and optional description, not file bytes. The file may have been edited, removed, replaced, or moved after the owning message was accepted.

**Safe checks.**

- Resolve the path beneath the Task's selected workspace.
- Inspect Git status/history for tracked project files.
- Compare the current file with the Checkpoint, Assignment, or Human Request that referenced it.
- For Command Run output, inspect the product flags before opening the log.

**Legal action.** Report the missing or changed state. Recreate content only from user-owned version control or another authoritative source. If the changed file invalidates a review or conclusion, commission a fresh Assignment or record a new Checkpoint after reinspection.

**Controller truth.** The original reference and owning message remain historical truth. Their acceptance never guaranteed immutable bytes, a hash, or a managed Artifact snapshot.

**Report a defect when.** Admission accepted a missing, non-regular, duplicate, or symbolic-link path, or a product read hides a known changed/missing Command Run log.

## The browser disconnected or Activity stopped

**Meaning.** The SSE connection is an invalidation channel, not runtime authority. A proxy, sleep, reload, or network interruption may stop updates while the controller continues.

**Safe checks.** Reload the exact Task route and refetch current Task truth. Backfill Activity from the last accepted cursor. Check `/readyz` if product reads also fail.

**Legal action.** Reconnect with `Last-Event-ID` or restart Activity from a fresh page after `cursor_reset_required`. Use refetched legal actions only.

**Controller truth.** Browser state cannot start, settle, pause, complete, or erase work. Missing UI updates do not prove controller loss.

**Report a defect when.** Refetched truth and the semantic UI disagree, reconnection duplicates or loses accepted Activity after correct cursor handling, or the UI applies an action no longer offered.

## You are considering database reset

**Meaning.** `banksia db reset` creates a clean controller-storage baseline. It is destructive initialization, not a stuck-Task recovery action.

**Safe checks.**

```bash
banksia config show
banksia db upgrade --help
banksia db reset --help
```

Confirm the selected database, data directory, workspace, and whether the actual problem is configuration, exact-schema verification, service readiness, or one Task.

**Legal action.** Use `db upgrade` only to create a genuinely empty database or verify that a nonempty database already matches the exact shipped schema. It never migrates or repairs nonexact storage and stops with reset guidance when any schema detail differs. For recovery, use current Task controls and documented service restart first. Reset only in an intentionally disposable or backed-up environment when losing controller history is the desired outcome.

**Controller truth.** Reset destroys controller records and recreates the schema/catalog. It cannot convert blocked work to success, reconstruct loose files, or make old workspace Task directories canonical to the new database.

**Report a defect when.** Upgrade or startup schema verification fails on a supported untouched database, or reset crosses the selected data boundary. Do not run reset again to collect evidence.

## When to use support/audit detail

Use semantic Task, Workflow, attention, Action, and Result views first. Open the protected support plane only when diagnosing controller transitions, recovery, cursor behavior, or a reproducible product/controller disagreement.

Support routes are bearer-authenticated, reject browser origins, and are read-only. A support snapshot, trace, or event never becomes runtime authority.

For a defect report, collect only what is needed:

- Banksia version and platform;
- exact command or route and timestamp;
- redacted `banksia status --json` and `banksia config show`;
- Task ID and semantic Task state when relevant;
- the smallest safe Activity or support trace excerpt;
- expected versus actual consequence; and
- whether the issue survives a normal refetch or documented service restart.

Remove credentials, provider tokens, user content, and sensitive file bytes. Report the issue through the repository's issue tracker. Do not include a database dump or full provider transcript unless a maintainer explicitly requests a safe transfer.
