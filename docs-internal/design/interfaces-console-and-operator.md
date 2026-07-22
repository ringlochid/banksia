# Interfaces, Console, and Operator target

Status: Target

Decision record: accepted 2026-07-22; revised 2026-07-23.

## Product language and audience boundary

The controller entity remains `Task`. The ordinary UI calls a Task a **Run**. There is no duplicate Run persistence model.

Banksia deliberately separates three planes:

| Plane | Audience | Contents |
| --- | --- | --- |
| Controller truth | Runtime and recovery | Task, TeamRevision, Assignment, Attempt, Dispatch, wait, Wave, Checkpoint, Boundary, exact source, control, and raw event records. |
| Support/audit | Maintainers and diagnosis | Exact chronology, technical IDs, provider routing, retries, watchdog, revisions, hashes, refs, raw payloads, and protected logs. |
| Product experience | Person who commissioned the work | Workflow, team, plan, status, attention, meaningful Activity, legal actions, referenced files, and exact Result. |

The browser product API receives only the third plane. Technical fields are not downloaded and then hidden behind a toggle. A separately authorized internal support API/export may expose controller/audit truth.

Opaque resource IDs, URLs, ETags, SSE cursors, and request correlation tokens may be carried by the client when required for navigation or concurrency. They are not rendered as product content.

## Nontechnical product contract

The Console and every backend surface created primarily for it are designed for a person commissioning work, not for someone who understands agent-runtime machinery. This is a product contract, not a final-copy polish pass.

- Default screens ask only for the minimum user intent. Progressive disclosure means every supported provider, sandbox, capability, import, and diagnostic choice remains reachable in its relevant screen, but secondary choices begin in clearly labeled collapsed or contextual controls instead of competing with the primary task. It never means removing, silently defaulting without readback, or making an advanced choice support-only.
- Page names, field labels, status, Activity, attention, actions, errors, and receipts describe the person's work and next safe action. They do not require a glossary of Banksia internals.
- Destructive or externally consequential actions state their scope and consequence before commitment. Reversible accepted edits return a concise receipt and Undo when the owning contract permits it.
- Empty, loading, pending, conflict, offline, rejected, blocked, partial-log, and restart/reconnect states each provide a clear explanation and safe next action without exposing controller machinery.
- Advanced fields explain their practical consequence. They never present raw provider options, Policy syntax, generic tools, technical event types, or support/audit data merely because the backend stores them.

The product backend makes this possible rather than delegating semantic work to the browser. UI-facing responses provide semantic status, human-safe field errors, actionable attention, controller-returned legal actions, confirmation requirements, typed input constraints, effect receipts, and opaque correlation handles where support needs them. They never require the browser to classify raw events, decode runtime states, derive legality, or turn an exception string into user guidance.

Every critical journey is tested from a first-use prompt without access to internal docs: recognize the page's purpose, find the primary action, predict its material effect, recover from one failure, and confirm accepted controller truth. Passing typecheck or reproducing a reference screenshot is not evidence of this usability contract.

The required repeatable evaluator is an independent review agent that did not implement the slice and receives only the plain user scenario plus the product UI—no Banksia internal docs or runtime vocabulary. It drives the real browser and records screenshots, accessibility snapshots, ambiguity, hesitation, wrong turns, and recovery evidence under ignored `tmp/`. A real human study is welcome but is not a release prerequisite for this baseline.

## Workflow authoring API

The product API is Workflow-specific. It exposes:

- list/search published Workflows;
- read one Workflow and immutable revision history;
- create/read/update/discard a mutable Workflow draft;
- structured tree add/update/remove operations;
- validate a normalized draft;
- explicitly publish a draft; and
- start a Task from one published Workflow.

Browser requests and responses use structured JSON. They contain no generic Definition kind switch, Role/Policy route, source-text YAML body, compiler preview, external MCP configuration, or arbitrary tool configuration. The Member shape includes only the narrow Human Request/Command Run capability grants defined by the Workflow schema.

### Draft concurrency and identity

- Draft reads carry an opaque HTTP ETag.
- Mutations send `If-Match`; a stale client receives a conflict plus current draft readback, never last-write-wins guessing.
- The ordinary UI does not expose revision tokens.
- The controller allocates new member IDs for canvas/Operator add operations.
- IDs cannot be edited after creation.
- Draft mutations are autosaved to controller truth and return an opaque, controller-issued, single-use Undo receipt bound to the draft and accepted ETag. The browser never computes or submits an inverse mutation.
- Discard deletes only a mutable draft. A published Workflow revision is immutable and has no product delete operation in this baseline.
- Publish is explicit and creates an immutable revision. Autosave never publishes.

The UI and Operator call the same structured services. Neither maintains a parallel local Workflow truth.

## Task start API

HTTP, Console, CLI, and Operator converge on the strict TaskStartRequest in [Product and Workflow](product-and-workflow.md). A successful response is a start receipt containing opaque Task ID, selected Workflow/revision readback, resolved workspace, manifest path, and accepted status. It does not imply that the root provider started successfully or finished.

The ordinary product labels this action **Run workflow** or **Start run**, not Compose Task.

## Task product read model

The exact wire schema is generated from typed backend contracts. Conceptually:

```text
TaskView
  id
  prompt_excerpt                    presentation-only
  workflow {id, description}
  status                            starting | working | waiting_for_you |
                                    paused | completed | blocked | cancelled
  status_message
  started_at / updated_at
  team: recursive TaskMemberView
  plan?
  attention[]
  actions[]                         actions currently legal for the user
  result?                           singular exact root Result
```

`TaskMemberView` contains opaque navigation identity, title/fallback name, purpose, recursive children, and plain work state such as not started, working, waiting, done, or blocked. It may contain one latest human update. It does not contain Assignment, Attempt, Dispatch, Boundary, Wave, configuration revision, provider route, or watchdog fields.

`attention[]` contains actionable human facts such as an open Human Request or an Action whose failure requires a decision. Each item has human copy, relevant member, typed answer/action controls, and legal operation URLs/guards. It is not a raw wait row.

`actions[]` is the backend-owned legal control set. The browser does not derive pause/resume/cancel/answer/cancel-action legality from controller internals.

`result` is null until an accepted terminal root Checkpoint exists. When present it is singular and contains exact completed/blocked outcome, Checkpoint summary, optional details, file references, and completion time. Cancellation or infrastructure failure without that Checkpoint never fabricates a Result.

Every nested `files[]` entry is only a workspace-relative path and optional short description already recorded on its Assignment, Checkpoint, or Human Request. Result, Activity, attention, and current-work views mirror those exact source values. References stay embedded in their owning semantic view; `TaskView` has no standalone file catalog. A reference has no generic file resource ID, frozen body, version, hash, or content guarantee. A separately authorized browser file route may open the file's current bytes after fresh containment checks; it must label missing or changed files honestly and is not an Operator tool.

The normal model excludes technical IDs beyond opaque navigation handles, Workflow revision internals, control counters, hashes, refs, provider/session facts, route resolution, raw trace, raw event payloads, and negative filler such as “No current Dispatch.”

## Semantic Activity and SSE

The browser chronology is `TaskActivity`, not TaskEvent:

```text
TaskActivity
  id                              opaque cursor identity
  kind                            small semantic discriminator
  occurred_at
  title
  summary?
  member? {id, name}
  outcome?                        completed | blocked | failed | cancelled
  files[]                         exact source readback; not a file catalog
  action? {label, href}
```

Initial semantic kinds are bounded to human meaning:

```text
task_started / task_paused / task_resumed / task_cancelled
task_completed / task_blocked
work_completed / work_blocked
input_requested / input_received / input_expired / input_cancelled
action_started / action_succeeded / action_failed /
action_timed_out / action_cancelled
```

The backend maps committed source facts to these variants. The frontend never classifies `boundary_accepted`, payload shape, runtime IDs, or provider events. Mid-flow Dispatch, plan bookkeeping, structural revision, start/watchdog, Wave, retry, and cleanup facts create no Activity item unless they produce a separate human-relevant outcome.

An accepted root terminal Boundary emits exactly one `task_completed` or `task_blocked` Activity. Result is the singular readable projection of that same Checkpoint and emits no second readiness Activity.

Initial implementation may project Activity deterministically from durable raw TaskEvents and source records. It must not create a second runtime state machine. A dedicated persisted Activity table is deferred until stable backfill/localization requirements prove one necessary.

SSE has two product uses:

- semantic Activity backfill/stream with opaque cursor; and
- a payload-minimal `task_changed` hint that causes TaskView refetch.

Cursor reset triggers silent authoritative refetch. The UI only reports a live update problem when delay is long enough to affect the user.

## Actions, Human Requests, and Results

### Managed Command Run -> Action

A controller-managed Command Run appears as one evolving **Action** with a human purpose, member, running/terminal outcome, elapsed time, `View output`, and Cancel only when legal. It does not show argv, cwd, process state, exit code, physical log path, ownership revision, or runtime ID by default.

`View output` opens a scoped contextual view with sanitized bounded tail, search, copy, optional download, and explicit truncation/incomplete notices. Routine provider-native shell calls do not become product Activity.

### Human Request -> Needs your attention

An open request creates a pinned `Needs your attention` card beneath the Run header and highlights the requesting member/ancestor path. Controls match the typed request:

- Input: bounded text/number/date/etc.;
- Direction: two or three choices and optional Other;
- Approval: explicit Approve/Decline;
- Review: decision plus optional note.

Submitting commits only the answer. The card freezes as a receipt; SSE/refetch later proves whether a continuation opened. The UI never equates a successful answer HTTP request with completed resumption.

### Root Checkpoint -> Result

When present, Result appears directly below status and above the team/Activity. It renders the exact Checkpoint summary, optional Markdown details, file references, completion time, and completed/blocked status. A blocked Result is an accountable answer with the same prominence as completed. It is never streamed from provisional provider prose or reconstructed from the latest child/event.

## Fresh Console

Create a new root `console/` application in React, TypeScript, and Tailwind after semantic backend contracts are stable. Do not move, rename, or incrementally restyle `apps/console`; inspect it only to extract useful API, SSE, browser, accessibility, and error-case coverage before deletion.

The production build writes `console/dist/`. Packaging stages those files into an ignored generated-assets directory and then into the distribution through `make package-build`; generated assets never become a parallel hand-edited Console source tree.

Top-level navigation is intentionally small:

- **Workflows** — library, Workflow Studio, publish, and start;
- **Runs** — task list, Run Studio, attention, Activity, and Result.

Settings needed for controller/provider configuration may be contextual but do not become a third authoring model.

An empty/reset installation shows the three packaged Starter Workflows in the Workflow library as ordinary published teams with a quiet **Starter** label and a plain-language “use when” description. It never shows the maintained OMC/OMX reference-example IDs as installed content. Because Starter Workflows omit provider and capability configuration, their cards make no provider or tool availability promise; they use the installation's configured default until a user explicitly customizes a draft.

## Workflow Studio

### Horizontal team hierarchy

- Use the [`add-child-sibling-branch.png` geometry reference](appendices/n8n-reference-protocol.md#visual-reference-packet) as the primary deep-team geometry reference, interpreting every block as one Member and discarding n8n's node, port, and execution semantics.
- The lead begins on the left.
- Each hierarchy depth occupies the next column to the right.
- Direct children stack vertically in authored organizational order.
- One card is one recursive Member.
- One neutral connector means direct ownership only.
- There are no arrowheads, particles, step numbers, sockets, typed ports, or flow animation.
- Column and sibling position never imply sequence or execution order.

Use React Flow for canvas interaction and Dagre with `rankdir: LR` for the first deterministic layout. Test broad, deep, collapsed, blank-title, error, and localized trees with measured cards. Evaluate ELK only if Dagre demonstrably cannot preserve readable noncrossing subtrees.

Canvas coordinates, viewport, zoom, selection, and collapse are presentation state, never Workflow or scheduling data. Baseline authoring has no arbitrary free positioning, drag reorder, or drag reparent.

### One trailing add-child control

Exactly one visible `+` belongs to the selected editable Member:

- with no children it sits on a short right-side stem;
- with children it occupies the next vertical direct-child slot after the final accepted child subtree;
- activation submits one structured add-child mutation and no type picker;
- an in-flight pending card is UI state only;
- accepted truth appends one blank child with controller ID, keeps the parent selected, and moves the same `+` to the next slot;
- failure removes pending state and restores the original control; and
- selecting another Member relocates the single `+` to that Member.

Run Studio never shows the authoring `+`. The accessible outline and Member drawer expose an equivalent text Add child action.

### Member editing

Selecting a card opens one context drawer with human fields in this order:

1. title/name;
2. purpose/description;
3. instruction;
4. collapsed advanced provider selection; and
5. collapsed built-in capabilities with default-off Human Request kinds and Managed Command Run.

The capability controls say what they permit in human language. They do not show Policy, generic tools, MCP, allow/deny rule expressions, or system-prompt prose. Child controls always begin from that child's explicit grants; the UI never implies inheritance from the selected parent.

ID is visible only when support/import needs it and is never editable. Removal states the full subtree consequence. Changes autosave through structured JSON with ETag conflict handling, receipts, and controller-issued single-use Undo; publish is explicit. Discard applies only to the mutable draft; published Workflow revisions cannot be deleted.

### Canvas and drawer

The canvas owns the page body. One contextual surface displays Member details, Operator, and later Run context:

- desktop: collapsible overlay drawer on the right, not a permanent width-consuming split;
- narrow screen: bottom sheet plus accessible tree/outline as primary navigation;
- opening it pans the selected card into the unobscured region.

`Tidy team` deterministically recomputes visible card positions from hierarchy, authored child order, card sizes, and collapse state. It changes no draft, revision, event, or runtime fact and preserves selection/context/zoom when practical. `Fit team` changes viewport only. They are separate controls.

## Run Studio

Run Studio reuses the horizontal hierarchy as a read-only organization view. It shows:

- plain Task status and meaningful message;
- pinned attention and exact Result before lower-priority details;
- Member work states and optional human-readable current plan;
- semantic Activity;
- generic file references and managed Action output;
- legal Task controls; and
- the Operator as a separate contextual agent.

It does not show Assignments, Attempts, Dispatches, Boundaries, Waves, Checkpoints as machinery, revisions, routes, watchdogs, raw refs, technical events, or raw JSON. A selected Member can focus relevant Activity but never replace the Task-level attention or Result.

## Shared QuestionCard

One presentational family serves Operator clarification and runtime Human Requests while feature containers retain separate persistence and continuation.

Behavior:

- one active question at a time;
- one to three questions per short set;
- two or three full-width, single-select suggested rows;
- stable controller-issued question/option IDs;
- UI-added `Something else`/Other with nonblank free text;
- `current of total` progress and back/next preserving drafts;
- one explicit final action such as Continue, Approve, Decline, or Submit review;
- read-only receipt after commit;
- fieldset/radio semantics, focus management, announcements, keyboard use, zoom/reflow, and narrow-screen layout.

Operator questions may explicitly allow Skip as “continue without this preference.” Runtime Human Requests allow Skip/Other only when their typed contract permits it. An open Operator question locks only the Operator composer; a Task Human Request never locks unrelated Operator chat.

Task-start file entries are labeled **Referenced files**, live under Advanced, and accept workspace-relative path plus optional purpose only. The baseline has no browser upload, copied attachment body, or generic file picker that implies Banksia owns the bytes.

## Operator agent

Operator is a separate control-plane agent configured with a Codex or Claude SDK provider. It is not a Workflow member, Task/Attempt/Dispatch, second Banksia runtime, or LangGraph graph.

The controller owns the selected Operator provider and adapter configuration. If neither supported provider is configured and authenticated, Operator shows an unavailable state with a concrete setup action; it never silently falls back or borrows a Task Member's provider choice.

Operator receives Banksia’s built-in, controller-authorized Operator tools (which may use MCP as transport). External user-authored MCP integration remains deferred. Workflow drafting is a primary job, but Operator may perform every Task/Workflow action currently legal in its user scope.

### Complete product-operation coverage

The Operator catalog must cover every ordinary product operation a user can perform in Workflow Studio or Run Studio:

| Family | Required effects |
| --- | --- |
| Workflow discovery | List/search Workflows; read current/published Workflow and revision history; read the active mutable draft and ETag when one exists. |
| Draft lifecycle | Create, read, update metadata/note, discard, validate, and explicitly publish a draft. |
| Team editing | Add, update, or remove a Member/subtree, including prose, provider, and built-in capability settings. |
| Run lifecycle | Start from one published Workflow; list/read Runs; pause, resume, or cancel when legal. |
| Human attention | Read open Human Requests; submit or cancel an answer when the product service says it is legal. |
| Managed Actions | Read Command Run state/output and cancel when legal. |
| Results and files | Read Result and loose file references. The product UI may open current file bytes through an authorized route; Operator has no generic file-content operation. |
| Legal actions | Execute controller-returned Task lifecycle controls through `task_control`; every non-Task action stays with its typed Workflow, Human Request, or Command Run operation. There is no generic execute-anything escape hatch. |

The exact baseline catalog is seventeen operations over those product services:

```text
workflow_search
workflow_get
workflow_authoring_options
workflow_draft_create
workflow_draft_edit
workflow_draft_validate
workflow_draft_undo
workflow_draft_discard
workflow_draft_publish
task_search
task_get
task_start
task_control
human_request_respond
command_run_get
command_run_output_read
command_run_cancel
```

`task_get` returns bounded current attention, Result, Activity, Command Run summaries, and exact source file references embedded with their owning semantic messages. There is no `artifact_get`, `file_get`, generic file reader, or file CRUD/catalog family. Operator receives no support/audit export, raw runtime record, provider credential/setup, host filesystem, or external-MCP administration tool merely to achieve parity. Exact schemas share the same typed product-service contracts as HTTP and the SDK adapter; MCP is one optional projection rather than the authority.

### Durable conversation

Minimal state:

```text
OperatorConversation
  conversation ID
  configured provider
  opaque provider thread/session ID
  ordered user and assistant turns
  state: ready | running | awaiting_answer | failed | provider_thread_lost
```

Do not reproduce Assignment, Attempt, Dispatch, Wave, Checkpoint, or raw tool event families for Operator chat. Controller mutations remain canonical in their owning services; chat retains human messages and receipts/links.

Conversation create/list/read, message submit, question answer, confirmation, and retry are durable product-service boundaries shared by HTTP and the UI. One conditional controller claim permits at most one active provider turn per conversation. Duplicate submits, answers, confirmations, and reconnects return the committed turn/receipt or a typed conflict; they never start a second turn.

If the SDK reports that the opaque provider thread no longer exists or cannot be resumed, Banksia records `provider_thread_lost`, preserves every visible turn and controller receipt, and offers an explicit new-conversation action. It does not silently fork the thread, replay committed tool effects, or claim continuity from transcript text.

### Typed turn output

Every provider turn must finish with one structured variant:

```text
message
  human-facing message

ask_user
  optional explanation
  1..3 questions
    short header
    concrete question
    allow_skip: boolean = false
    2..3 mutually exclusive options
      label
      one-sentence consequence
```

The model does not generate `Other`, persistent question IDs, or option IDs. `allow_skip` is explicit and defaults to false. Banksia validates, allocates IDs, persists the assistant turn, and changes the conversation to awaiting answer. The provider invocation has ended; no process or open tool call survives the human delay.

The user answers through QuestionCard and presses Continue. Banksia commits one structured user turn, marks the previous card as a receipt, and invokes the same provider thread/session for a fresh turn carrying the exact question and answer. Refresh, navigation, restart, and browser closure therefore do not lose the boundary.

Provider-native question events may later adapt to the same product contract, but the baseline does not enable a second path. LangGraph adds no value for one completed-turn boundary and is excluded.

### Action and confirmation policy

These general rules belong to the Operator's controller-owned system prompt and tool teaching. They are never inserted into Workflow `note` or Member `instruction`.

- If a material user choice is missing, Operator asks rather than guessing. Prefer one question and ask none when the request is already specific.
- An explicit request to create or edit a Workflow authorizes reversible draft mutations. Each mutation returns a human receipt and Undo; no redundant Apply confirmation is needed.
- “Create a workflow for me” authorizes drafting, not publishing or starting a Run.
- Publish, Run/start, runtime controls, and destructive or unrequested actions require explicit current-turn instruction or clear confirmation.
- Confirmation is a durable, opaque, single-use controller receipt bound to conversation, exact action payload, and current ETag/action guard. Payload or controller-truth change expires it; the client never reconstructs authority.
- Operator never claims a mutation succeeded without the controller tool result and never renders model-invented Workflow/Task state; the client refetches controller truth after receipts/SSE.
- Product UI shows meaningful messages, questions, changes, and receipts—not chain-of-thought or raw tool-call internals.

## n8n reference boundary

The curated screenshots and pinned sparse source snapshot documented in the [tracked n8n reference protocol](appendices/n8n-reference-protocol.md) provide mature implementation-study references for question cards, assistant chat, canvas density/layering, selection, add affordances, horizontal branching, contextual editing, list/run/log views, compact controls, responsive states, accessibility behavior, and tests.

Before any UI or UI-facing product-API delegation, the parent selects the matching reference packet and names the exact upstream files in the brief. The slice records what it adopts, adapts, and rejects against the Banksia owner contract. Reading the source is mandatory; treating its data model or visual surface as authority is forbidden.

Implementation is independently authored React/Tailwind Banksia code. Import or copy no n8n Vue/TypeScript components, stores, tests, router, CSS, HTML/markup, tokens, strings, icons/assets, enterprise files, backend, or dataflow/product semantics, and do not translate it line-for-line. The source snapshot remains ignored and unpackaged. Banksia owns its information architecture, contracts, terminology, visual identity, and accessibility behavior. Any desired substantially derived implementation stops for an explicit license/provenance decision.

## Product acceptance journey

A nontechnical user must be able to:

1. ask Operator to draft a Workflow and answer a short material question;
2. inspect and edit the horizontal responsibility tree without learning runtime nouns;
3. publish explicitly and start with one prompt;
4. understand what the team is doing and whether Banksia needs input;
5. answer a Human Request or inspect a managed Action log;
6. see meaningful Activity and file references; and
7. read the exact completed or blocked Result.

At no point should the journey require understanding Dispatch, Attempt, Boundary, Wave, control revision, provider route, watchdog, raw event, or trace JSON. The user must be able to complete the journey from visible labels and feedback without opening product documentation or a support/audit surface.
