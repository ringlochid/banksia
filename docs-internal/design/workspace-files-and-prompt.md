# Workspace, files, and prompt target

Status: Target

Decision record: accepted 2026-07-22; revised 2026-07-23.

## One provider-visible workspace

Every Task binds one user-selected workspace `W`. Every Codex, Claude, or OpenClaw Dispatch for that Task receives `W` as its execution working directory or provider-visible equivalent. All members share the same project files and the same Task directory.

```text
W/
  project files
  .banksia/
    t_7m4k2d9x/
      manifest.md
      workflow-note.md                 # only when Workflow note exists
      notes/
      artifacts/
      command-runs/
        c_q3m8y1ka/
          output.log
```

This choice optimizes for native shell/editor/compiler/provider use and simple agent collaboration. It deliberately does not provide per-member worktrees, read-only isolation, path leases, automatic diff transfer, or merge automation.

Full native access is the baseline default. Concurrent agents can see and change the same files. Banksia therefore does not claim deterministic or conflict-free replay of concurrent writes. The accountable Manager must avoid parallel overlapping edits unless scopes are credibly disjoint, inspect the integrated shared state, and sequence work when the risk is material.

OpenClaw is supported only when the user externally configures it to expose `W` and permit the required native access. Banksia does not inspect or mutate OpenClaw configuration and provides no managed file-tool fallback.

## What belongs where

| Surface | Authority and use |
| --- | --- |
| Ordinary project paths | Actual source, tests, project documents, and user-requested deliverables. Any existing regular file beneath the workspace may be referenced by path when another context should inspect it. |
| Controller database | Canonical Task, team, Assignment, Attempt, Dispatch, wait, Wave, Checkpoint, ordered `FileReference` values, control, and event truth. It records path/description values, never general file contents. |
| Protected controller body storage | Protected Command Run output bytes needed for truthful bounded output and recovery. It is not a general file store and is not provider-visible. |
| `.banksia/t_<id>/manifest.md` | Controller-generated organization projection. Never legality or live progress truth. |
| `workflow-note.md` | Immutable Task projection of the pinned Workflow’s optional shared note. |
| `notes/**` | Free-form shared Task working memory for coordination, investigation, review, and recovery. Native and mutable; not controller truth or automatically inserted into prompts. |
| `artifacts/**` | Free-form reviewable deliverables created for another Member or the user, such as plans, reports, reviews, verification records, diagrams, images, recordings, or patch files. They remain loose mutable files, not controller-owned Artifact resources. |
| `command-runs/**/output.log` | Controller-managed visible combined output file. DB lifecycle and protected retained Command output remain authoritative. It is not one of the two controller projections. |

Do not put the database, credentials, provider sessions, service state, locks, controller logs, raw events, or runtime-record JSON under `.banksia/`.

## Task and Command identifiers

Task and Command IDs use a product-readable opaque form:

- `t_` or `c_` prefix;
- eight lowercase Crockford Base32 characters from 40 CSPRNG bits;
- collision checked against controller records and the target path; and
- never treated as a hash, version, credential, or authorization token.

Authorization always comes from the controller-bound current Dispatch.

## Git safety

For a Git worktree, Task workspace preparation:

1. discovers the actual worktree root with `git rev-parse --show-toplevel` and the exclude file for that linked or main worktree with `git rev-parse --git-path info/exclude`;
2. computes the selected workspace relative to that worktree root and idempotently adds an anchored ignore entry for exactly that workspace's `.banksia/` (`/.banksia/` at the root or `/<workspace-relative>/.banksia/` for a nested workspace);
3. never edits the user’s tracked `.gitignore`;
4. rejects Task start if any `.banksia` path is already tracked;
5. does not follow symlinks while creating controller-owned paths; and
6. creates the Task directory without overwriting an existing path.

Non-Git workspaces need no pretend ignore file. The Task path remains visible and user-owned for cleanup policy, while DB truth and any separately retained Command Run output remain in the controller data boundary.

Task admission creates the collision-safe directory with a controller-owned initialization marker, writes only the manifest/optional Workflow-note projections plus empty conventional directories, commits controller truth, then clears the marker before provider-start publication. Recovery may remove only a stale marked directory with no committed Task; it repairs a committed marked Task in place. Reset and generic cleanup never recursively delete an accepted `.banksia/t_<id>/` directory.

## Organization manifest

`manifest.md` is a human- and agent-readable organization chart generated from the current TeamRevision. It contains:

- Task ID and pinned Workflow ID;
- the Task lead and complete recursive hierarchy in current organizational order;
- for every member: ID, optional title, optional description, optional instruction, nonsecret provider selection, requested built-in capability grants, derived Manager or Contributor label, and authored-Workflow versus Task-replan origin; and
- a short statement that hierarchy position and sibling order do not determine execution time.

It does not contain:

- the Workflow note body;
- Work Plan, Assignment, Wave, wait, Checkpoint, participation, status, or Activity data;
- controller legality or authorization facts;
- technical TeamRevision, Dispatch, Attempt, Boundary, event, route, hash, or provider-session identifiers; or
- file-reference and command indexes.

After a successful structural replan, the controller renders the complete new manifest to a sibling temporary file, flushes it, and atomically replaces the stable path. The operation result comes from database truth, not the projection. Projection failure does not roll back the committed TeamRevision, but it blocks later Dispatch start until repair so no agent begins with a known-stale organization reference.

Workflow note projection is separate and replaced only from the pinned Workflow. Agents never edit the published note through this file.

## Free-form notes and artifacts

During Task-directory initialization, the controller creates empty `notes/` and `artifacts/` directories before the first provider Dispatch can start. The directories are an agent-facing organization convention only. Banksia does not index, parse, register, classify, or own the files later written there.

### Notes

Agents may create any useful regular file below `notes/` with native tools. Good uses include:

- coordination decisions and dependency shape;
- evidence found and hypotheses ruled out;
- open uncertainty and the next useful check;
- review decisions and integration boundaries; and
- interruption/recovery state that should survive a provider turn.

Notes should record observable decisions, evidence, assumptions, uncertainty, and next actions—not private chain-of-thought or a chronological activity diary. There is no note schema, ID, kind, version, TTL, controller mutation, or required template.

Because the workspace is shared, another member can technically read a note. Banksia does not automatically insert it or promise awareness of it. When exact content should cross an Assignment boundary or become a user deliverable, the author may include the note's path and a short purpose in that message's `files` list. It does not need to move, copy, publish, or reclassify the file.

For a nontrivial Wave, a Manager should usually record a concise shared basis when that prevents repeated discovery or survives interruption, for example:

```text
notes/delegation-shape.md       mutable Manager coordination
artifacts/wave-brief.md         reviewable baseline referenced to children
```

Skip both when one complete child Assignment already communicates everything. File creation is not a required stage or evidence ritual.

### Artifacts

Agents may create regular files below `artifacts/` when the work benefits from a structured, reviewable deliverable that another Member or the user should inspect. Good uses include:

- an implementation or investigation plan that will be reviewed before work;
- a research brief, architecture diagram, image, or browser recording;
- an independent review or verification report;
- a patch, diff report, or other bounded handoff that should retain its full detail across provider contexts; and
- a polished Task deliverable that has no more natural project location.

Actual source, tests, project documentation, and user-requested files with a natural project location stay there. Do not duplicate every edit or tool result under `artifacts/`. Skip an artifact when the project change and Checkpoint are already the clearest deliverable.

An artifact file is ordinary mutable workspace content. The lowercase directory name describes intended use; it does not create an `Artifact` ID, controller record, content snapshot, approval state, version, hash, current pointer, or automatic UI catalog. A working note that later needs a polished deliverable may be refined in place or rewritten under `artifacts/`; Banksia performs no promotion operation.

When an artifact must cross an Assignment boundary or be shown through a Checkpoint or Human Request, include its path and short purpose in that message's `files` list. The receiver still opens the current loose file and reports missing or changed content honestly.

### Notes, artifacts, file references, and Checkpoints are distinct

| Surface | Purpose | Transfer and authority |
| --- | --- | --- |
| **Note** | Mutable, free-form working memory for coordination, investigation, review, or recovery. | Workspace content only. It is not controller truth and is not inserted into another Member's context automatically. |
| **Artifact file** | A structured or otherwise reviewable deliverable intentionally created for another Member or the user. | Loose workspace content under `artifacts/` by convention. It has no controller identity or lifecycle. A `FileReference` makes it an explicit navigation handoff; shared-workspace Members may also discover and open it natively, but Banksia does not guarantee awareness. |
| **File reference** | Navigation hint to an ordinary loose workspace file that another context should inspect. | Immutable `{path, description?}` value on an owning controller message. It conveys neither file ownership nor a byte snapshot. |
| **Checkpoint** | Durable teammate-facing report of progress or a terminal outcome for an exact Assignment execution. | Controller-recorded message with a required summary, optional details and file references, and an optional or terminal outcome. |

A note or artifact file keeps its loose-file semantics when referenced. A project file, note, artifact, or Command Run log can all use the same generic reference shape. A Checkpoint may point to a file but does not duplicate its contents. Neither a workspace file nor a file reference substitutes for the complete Assignment prompt or Checkpoint report.

## Generic file-reference contract

Banksia does not classify or own workspace files as runtime objects. A `FileReference` is only an ordered navigation value recorded on an Assignment, Checkpoint, or Human Request when opening a specific file will help the receiver. Task start seeds the root Assignment. Continuations, Result, Activity, context, and product views mirror the exact owning values without a second write.

The public and model-visible reference is intentionally small:

```yaml
path: .banksia/t_7m4k2d9x/artifacts/review-report.md
description: Independent findings and verification evidence.
```

- `path` is required and workspace-relative.
- `description` is optional, short, and explains why the receiver should open the file.
- Regular files are supported. Directories, URLs, remote resources, special files, and arbitrary provider blobs are deferred.
- A file reference is not a permission grant, byte snapshot, proof claim, or file-content transport. It does not replace a complete Assignment or Checkpoint.
- The path may identify an ordinary project file, a free-form file under `notes/`, a reviewable file under `artifacts/`, a controller-managed Command Run log, `manifest.md`, or the optional `workflow-note.md`. Do not redundantly attach the two projection paths when the Dispatch already renders them and no message-specific reason exists.
- A Task-start reference must already exist beneath the selected workspace before Task identity and `.banksia/t_<id>/` are allocated. Later controller messages may reference files in that Task directory.
- Ordinary project edits remain ordinary shared files and visible Git diffs. Recording a reference does not change the referenced file's lifecycle.

### Reference recording and mutability

Attaching a `FileReference`:

1. authenticates the exact current controller operation;
2. normalizes the relative path beneath `W` and rejects absolute paths, `..`, globs, NUL, devices, sockets, FIFOs, directories, and every symlink component even when it would resolve back inside `W`;
3. verifies at attachment time that the resolved target is an existing regular file without following a path outside `W`;
4. normalizes the optional short description;
5. rejects duplicate normalized paths within that owning `files` list; and
6. records the ordered `{path, description?}` values atomically with their Assignment, Checkpoint, or Human Request.

There is no standalone generic file resource, globally addressable file table, file ID, body copy, content digest, capture or promotion action, version/current pointer, materialization, or rematerialization protocol. Persistence may use owner-scoped ordered value rows or an equivalent value encoding, but those records have no independent lifecycle or lookup surface. The same normalized path may be recorded again in another owning message, but a single owning list cannot repeat it. Banksia does not infer identity or sameness from bytes.

The file remains loose and mutable. A later reader may observe changed or missing content and must report that fact honestly. Controller audit proves who referenced which path, description, and owning message at what time; it does not prove the bytes then present. Teams that need byte-for-byte reconstruction use their workspace's own version control or create a separately named immutable file by convention. Banksia does not conflate that convention with runtime identity or generate a hash.

## Command-run output

Command Run preserves controller-owned lifecycle and process supervision while using one agent-friendly file:

```text
.banksia/t_7m4k2d9x/command-runs/c_q3m8y1ka/output.log
```

The process is launched with stderr redirected to stdout at creation. Banksia drains that single pipe continuously, including after the retention cap, so it preserves the OS-observed combined stream and cannot deadlock on a full pipe. It does not attempt to merge separately buffered stdout/stderr after the fact.

The canonical record includes:

```text
CommandRun
  ID, Task/Assignment/Attempt/source Dispatch
  typed command and cwd
  pending/running/terminal state and ownership revision
  timeout/cancel/reap facts
  start/end timestamps, exit/failure facts
  visible log path
  retained_bytes, observed_bytes, truncated
  protected output body locator
```

The controller commits intent and the Attempt wait before external launch, claims exact process ownership, creates files without following/replacing, and records terminal state only after reap and protected output flush. It never blindly relaunches an ambiguously owned command after restart.

When retained bytes are truncated, the visible file ends with a clear Banksia truncation marker and the DB retains exact counts. The controller continues draining discarded bytes. A browser reads authorized bounded ranges/tails through a scoped API rather than a host path.

`output.log` is a writable controller-managed workspace file and must not be presented as immutable evidence. Protected controller-retained output plus DB lifecycle is the Command Run audit truth. An agent may reference the visible log directly through a generic `FileReference` when another context should open it; no copy, publication, or domain conversion is required.

The only controller projections under the Task directory are `manifest.md` and the optional `workflow-note.md`. Notes and artifacts are agent-authored loose files, and Command Run logs are controller-managed execution output, not projections of general controller records.

## Removed filesystem projections and tools

Do not materialize:

- per-Dispatch `instructions.md` or `input.md`;
- Assignment/checkpoint JSON or Markdown projections;
- Work Plan files;
- criteria, consume/produce, slot, file index, transient index, current pointer, or raw event files; or
- a controller data directory inside the workspace.

Remove Banksia `list_files`, `read_file`, and `write_note` operations. Agents use provider-native filesystem, search, editor, shell, and binary tools in `W`. Banksia controller tools remain for typed state reads and mutations such as context, delegation, Checkpoint, requests, commands, and replan.

## Prompt architecture

[Task member system prompts](system-prompts.md) owns the exact source bodies, composition, dynamic XML, action teaching, and behavioral evaluations. This section owns the surrounding Dispatch/workspace data boundary and summarizes that contract without creating a second prompt source.

Each Dispatch stores and sends two exact lanes:

```text
instructions
  stable Banksia controller contract
  workspace and Checkpoint teaching
  Task lead overlay when applicable
  exactly one Manager or Contributor behavior block
  Human Request teaching only when effectively allowed and exposed
  Command Run teaching only when effectively allowed and exposed
  Continuation teaching only for a successor Dispatch
  current member instruction when nonblank
  shared Workflow note when nonblank

input
  one deterministic, escaped XML runtime document
```

Adapters map instructions to the strongest provider-supported system/developer lane and input to the task/user lane. Native tool definitions carry exact action schemas separately. Tool results stay in provider-native tool-result lanes.

### Instruction precedence

```text
controller safety, authority, and legal actions
  > current Assignment and exact Continuation
  > current member instruction
  > shared Workflow note
  > manifest, notes, artifacts, referenced files, command output, and ordinary workspace content
```

Authored or file content cannot widen controller authority. XML boundaries and labels improve clarity but are not a security boundary.

### Dynamic XML content

One `<banksia_dispatch_request>` document contains, in stable order:

- Task ID and `.banksia/t_<id>` path;
- full Dispatch, Attempt, Assignment, and current Member identities needed by the agent/controller contract;
- the complete exact Assignment prompt and every file path/description;
- optional Continuation whose nested trigger contains exact kind, exact source, and complete typed result;
- fresh-at-render direct-team Member configuration and participation facts;
- optional complete current Work Plan;
- effective Human Request/Command Run grants and only controller actions legal for the current Dispatch;
- relevant resolved execution constraints; and
- manifest/optional Workflow-note paths plus the notes, artifacts, and Command Run directories.

Initial Dispatches omit Continuation and trigger entirely. There is no synthetic `task_start` trigger and no rendered `null` placeholder.

Assignment is always a separate, complete message. A trigger exists only under a successor Continuation and has this conceptual shape:

```text
continuation.trigger.kind    why this successor exists
continuation.trigger.source  exact committed controller source
continuation.trigger.result  complete typed result needed to act
```

A child-Wave trigger result contains every returned child in delegation order, including the complete child Assignment, terminal outcome, complete Checkpoint, and file references. Human, Command, retry, recovery, and explicitly resumed Checkpoint variants likewise contain their complete typed source result. A trigger is not a second Assignment or a compact reason code, and IDs alone or “latest Checkpoint” lookups are insufficient.

An accepted replan likewise closes its source Dispatch. Its successor trigger contains the exact committed structural result and fresh configuration facts; the successor opens only after the manifest projection is current.

### Safe deterministic rendering

- Build XML from a typed projection with a standard serializer, never raw interpolation.
- Code owns every tag name; all variable values are element text.
- Escape `&`, `<`, `>`, quotes as required, and prompt-shaped closing tags.
- Reject NUL and XML 1.0-illegal characters before persistence; never replace or drop them during rendering.
- Do not use CDATA, DTDs, entities, namespaces, processing instructions, or arbitrary extension tags.
- Use UTF-8, LF, stable field order, stable omission rules, and one final newline.
- Omit absent optional fields/collections; retain required empty direct-team representation because it determines Contributor behavior.
- Same typed input produces byte-identical output; same-Dispatch restart reads stored bytes rather than rendering again.

XML structures the input only. Agents use ordinary prose and controller tools for output; they are never required to reply in XML unless the Assignment asks.

## Prompt behavior

The exact controller-owned assets in [Task member system prompts](system-prompts.md) teach:

- controller truth, exact current Dispatch authority, and stop-after-transfer;
- Assignment and Checkpoint as complete messages to a teammate;
- the Task lead’s terminal green/blocked Checkpoint as the exact human Result, with retry terminal only for its current Attempt;
- Contributor direct execution, inspection, and verification;
- Manager decomposition, distinct child value, return evaluation, integration, and verification;
- sequence, parallel, iteration, batch, and hybrid selection;
- local recursive Waves and collect-all return behavior;
- required direct-child participation and remove-children-before-takeover;
- proactive but proportional notes, reviewable artifacts, and file references;
- the shared full-access workspace and overlapping-write warning;
- loose-file mutability and restrained path/description transfer;
- proportionate Human Request/Command Run use when each action is available;
- honest limits, blockers, and residual uncertainty.

It asks for observable decisions and evidence, never private reasoning or a thought transcript. Exact action parameters stay in tool schemas.

Workflow `note` and Member `instruction` do not repeat this general teaching. They provide only team-specific purpose, preferences, non-goals, contribution guidance, and heuristics. Member `capabilities` authorize Human Request and Command Run but contain no behavioral prose. Controller/deployment policy may narrow grants; a denied or currently illegal action contributes neither a tool nor an action-teaching prompt section.

## `get_current_context`

Keep one optional coherent refresh operation. It uses the same typed projection and vocabulary as Dispatch input but marks the response as a fresh observation. It returns:

- full current Assignment and file references;
- optional exact Continuation with nested trigger kind/source/result;
- current direct team, participation, and derived Manager/Contributor behavior;
- current Work Plan;
- legal controller actions and useful execution constraints; and
- Task manifest, optional Workflow note, notes/artifacts directories, and Command Run paths.

It does not return Role/Policy, criteria, consume/produce, request-file refs, managed file operations, authored hashes/versions, synthetic initial trigger, or permanently null resume fields. It is useful after recovery, replan, uncertain freshness, or an explicit controller result—not a mandatory first call and never mutation authority by itself.

## Prompt proof

Required proof includes:

- golden initial Contributor, Manager, Task lead, Wave-return, human/command, retry, and recovery requests across supported adapters;
- XML parse/round-trip, Unicode, multiline Markdown, code fences, special characters, illegal characters, injection strings, stable order, omission, and byte-identical restart;
- complete Assignment/Checkpoint content, every file path/description, and ordered Wave returns;
- exactly one applicable behavior block and only legal action teaching;
- default-deny and controller-narrowed Human Request/Command Run prompt/tool conditioning;
- no removed request-file, Role/Policy, criteria, consume/produce, external-MCP, Skill, or managed-file-tool vocabulary; and
- behavioral evaluations for relay traps, safe/unsafe parallelism, nested Waves, contradictory review, implement-review-repair, batch scope, irrelevant children, takeover, exact root Result, context recovery, useful notes, reviewable artifacts, natural project-path choice, and file-reference restraint.
