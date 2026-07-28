# Banksia verification gates

Status: Reference

This page owns Banksia's proof requirements and controller-only validation guardrails.

No change closes from inspected code, prose, mocks, or a single happy path when its surface owns persistence, runtime authority, filesystem safety, provider behavior, or a public interface. Tests use real shipped paths at the strongest applicable boundary.

## Evidence record for every package

The package closeout records:

- owning internal contracts and tracked reference pages;
- changed contracts and deletion ledger entries;
- exact focused and full commands run;
- pass/fail/skip counts and environment;
- every skipped lane with exact blocker/owner;
- reset/schema/package/generated-output proof when applicable;
- exact stale-reader/writer/reference searches;
- independent review findings and decisions; and
- remaining risks assigned to a later work package or explicit deferral.

Existing failures must be reproduced and classified before they become a baseline exception. A prior sync receipt or interrupted run is not current evidence.

Real provider, installed-package, or HTTP proof stays deliberately small. Use one or two Members and one bounded outcome such as a greeting, short brainstorm, council, or narrow research question; Operator proof uses the minimum typed clarification and final answer. Large catalog Workflows are deterministic contract fixtures, not live-provider burn tests.

Platform claims require native installed-wheel proof. A Linux test that monkeypatches `os.name` or `sys.platform` may prove selection/rendering but never substitutes for macOS filesystem, ACL, process, service-manager, or package behavior.

Managed-provider isolation proof uses a disposable provider home and workspace containing sentinel user/project instructions, Skills, plugins or apps, agents, hooks, and external MCP servers. Before a model turn, readback must show no ambient instruction source, no active external server, no extra operation, resource, or resource template, and no provider configuration mutation. Claude proof covers API-key bare mode, Task personal-subscription SDK isolation, Operator personal-subscription safe mode, and fail-closed managed-policy readiness. Codex proof covers global and project guidance, named MCP/Skill disabling, untrusted-project configuration, exact workspace roots, and byte-identical provider configuration before and after.

## Hidden controller validation guardrails

This table is the sole numeric owner of controller-only baseline safety bounds that are not represented in a public authored or operation schema. Public contract schemas remain the owners of visible semantic constraints such as Workflow identifier lengths, Work Plan step count, and Wave size. The bounds below are controller validation constants with stable field-level diagnostics, not Workflow fields, user-authored limits, provider settings, or an administrator configuration surface. Work packages and subject owners link here rather than restating different values.

| Boundary | Maximum or rule |
| --- | --- |
| Raw Workflow input | 1 MiB before parsing. |
| Parsed Workflow value | Depth 32 and 4,096 total collection nodes. |
| Workflow responsibility tree | 256 Members, tree depth 12, and 32 direct children per Member. |
| Managed-provider `model` and `effort` | 255 characters each. |
| Task, Assignment, and delegation prompt | 64 KiB UTF-8 each after newline normalization. |
| Operator user or assistant message | 64 KiB UTF-8 after newline normalization. |
| Operator native `ask_user` result | Explanation 2,048 characters; header 64 characters; question 4,096 characters; option label 255 characters; option description 1,024 characters; complete serialized result 64 KiB UTF-8. |
| Operator submitted question answer | 64 KiB serialized UTF-8, depth 16, and 1,024 collection nodes. |
| Operator product-tool result | 327,680 UTF-16 code units after compact JSON serialization with non-ASCII characters unescaped. |
| `FileReference` list | 32 entries per owning message. |
| `FileReference.path` | 4,096 UTF-8 bytes after path normalization. |
| `FileReference.description` | 1,024 characters. |
| Checkpoint | Summary 2,048 characters; optional details 64 KiB UTF-8. |
| Human Request | Summary 2,048 characters; item prompt 4,096 characters; option title 255 characters; option description 1,024 characters. |
| Human Request response schema | 64 KiB serialized UTF-8, depth 16, 1,024 collection nodes, and no remote references. |
| Human Request submitted response | 64 KiB serialized UTF-8, depth 16, and 1,024 collection nodes. |
| Command Run argv | 256 entries, each at most 4,096 characters. |
| Command Run shell text | 16 KiB UTF-8. |
| Command Run summary | 2,048 characters. |
| Command Run timeout | At most 86,400 seconds. |
| Command Run output read/preview | At most 1 MiB per controller/API response; the full combined stream is written only to the Task-workspace log. |

Text admission converts CRLF and lone CR to LF, preserves all other whitespace and Unicode exactly, and uses trimming only for nonblank/optional-omission decisions. NUL and XML 1.0-illegal characters reject. The controller never silently replaces, drops, or Unicode-normalizes accepted characters; prompt XML escapes them during rendering.

## Final whole-program review and repair

After every implementation/cleanup package is complete, a separate final work package must review the integrated product rather than trusting the sum of package-local reviews. Its traceability matrix maps every accepted decision, package objective, temporary bridge, debt entry, generated contract, and gate on this page to one shipped owner and executed proof.

The final package uses exactly two independent review/fix rounds followed by a non-review closeout proof:

1. independent whole-program review, severity plus fix-now/defer classification, and repair of every fix-now finding;
2. complete affected/full proof, then a fresh independent review of the repaired candidate and repair of every remaining fix-now finding; and
3. after the second fix pass, one final full proof pass and parent-owned release go/no-go record; this is validation, not a third review round.

No P0/P1, live compatibility bridge, unowned decision, unexplained skipped lane, generated-contract drift, stale-reader/writer path, or release-blocking debt may remain. A P2 may remain only with exact evidence, owner, reason, and revisit trigger. There is no third review round: a material round-two contract change or remaining P0/P1 reopens the owning change or decision.

A successful final-package completion records **go**. An explicit **no-go** is still a valid review result, but it records the exact blocker/owner and leaves the package and program stopped or blocked rather than complete.

## Workflow schema and authoring

### HTTP and Console route isolation

- Every product JSON route is served only under `/api`; no product route has a root compatibility alias.
- Direct navigation to `/`, `/workflows`, `/workflows/{workflow_id}`, and `/runs` returns the packaged Console, while `/assets/*` returns only packaged static assets.
- Unknown `/api/*`, `/assets/*`, and browser paths return `404`; no catch-all rewrites API or missing-asset requests to HTML.
- Health/readiness, support, Operator, node, and managed internal mounts retain their separately owned paths and schemas.
- The generated product OpenAPI document and Console client use `/api` paths, and a created Workflow draft returns an `/api/workflow-drafts/{draft_id}` `Location`.
- Removing a Workflow discards its active draft and removes it from catalog search, detail, and new Task selection while exact immutable revisions remain readable for existing Task pins. Re-running starter seeding does not restore a removed published Workflow, and ordinary create cannot reuse its retired published ID.
- Source-tree development proves the API without requiring staged Console assets; installed wheel/sdist proof includes the exact production bundle and direct-navigation behavior.

### Mechanical schema proof

- Parse the maintained YAML schema.
- Validate it as JSON Schema Draft 2020-12.
- Parse and validate every maintained YAML example listed by `examples/workflows/README.md`.
- Parse and validate every packaged seed fixture under `src/banksia/workflows/resources/starter_workflows/` through the same Workflow schema and semantic validator.
- Serialize every example and seed to JSON and prove its normalized value and validation result are identical.
- Prove examples contain only Workflow authoring fields. The narrow `capabilities` block authorizes Human Request and Command Run; the actual requests, delegate, replan, Checkpoint, and file references remain runtime behavior.
- Prove Workflow `note` and Member `instruction` contain no generic Banksia orchestration, tool-use, wait, note/file-reference, anti-relay, or Checkpoint teaching; those rules have one owner in the system-prompt assets.
- Prove reference examples and packaged seeds are distinct inventories: no reference-example path or ID is enumerated by bootstrap, and package contents include only the seed inventory as bootstrap input.
- Walk every Member in every packaged seed and prove `provider` and `capabilities` are absent. Search seed prose for source-product-specific names, phases, tools, agent names, and memory-file dependencies.
- Resolve every internal `$ref` and reject broken or unused schema fragments.
- Prove all maintained local links resolve.

### Input and normalization proof

- Strict JSON and YAML ingestion accept one object document only.
- Duplicate JSON/YAML keys, aliases, merge keys, custom tags, multiple documents, non-string mapping keys, nonfinite numbers, excessive bytes, excessive nesting/collections, and unknown fields reject with source/path diagnostics.
- Blank/null optional Member prose and Workflow note normalize to omitted canonical fields; required catalog description remains nonblank.
- Member IDs follow the schema and are unique and non-reused within the complete Workflow tree, without requiring a cross-Workflow namespace.
- The hidden controller validation guardrails above reject at validate/publish/start boundaries without partial persistence.
- Codex/Claude provider settings accept exact supported model/effort values and only legal sandbox/network pairs.
- Omitted managed-provider sandbox resolves to full access/network allow.
- OpenClaw accepts only `kind`; any model/effort/sandbox/network option rejects.
- Explicit provider selection never silently falls back.
- Provider settings do not inherit from the parent.
- Omitted capabilities deny; empty blocks/lists, duplicate or unknown Human Request kinds, and any Command Run value except `allow` reject.
- Capability grants do not inherit, controller/deployment policy can only narrow them, and exact requested/effective provenance is persisted.
- Secrets, endpoints, environment, arbitrary options, Role/Policy, generic capabilities, limits, arbitrary tools, external MCP, steps, edges, criteria, consume/produce, and authored hashes/versions reject.

### Authoring lifecycle proof

- Structured JSON draft mutations, ETag conflicts, validation, Undo, explicit publish, immutable revision history, and current-published selection work through real persistence.
- The Workflow library and Workflow-ID detail readback cover draft-only, published-only, and published-with-draft truth. A draft-only Workflow is searchable and reopenable after navigation, browser refresh, controller restart, and pagination without browser-local catalog state.
- New browser/Operator draft creation accepts no authored lead Member ID; the controller allocates it and returns complete accepted truth. Operator may supply the complete structured JSON candidate, while the browser may begin from minimal fields. Open-for-editing returns an existing draft idempotently or clones the exact current published revision and pins its base in one transaction.
- Draft opening returns `201 Created` plus `Location` only for a newly created draft and `200 OK` for idempotent reuse; HTTP and Operator share the same normalization, authoring, and result services.
- Barrier-driven SQLite/PostgreSQL tests prove Workflow detail is always one coherent before-or-after snapshot across concurrent open, edit, publish, and discard, never an impossible hybrid or spurious not-found result. File-backed restart proof rediscovers draft-only truth without browser-held state.
- SQLite/PostgreSQL library tests prove `updated_at` is the latest durable current-publication or active-draft change across seed refresh, draft discard, and old-revision reselection; exact non-ASCII query text is preserved while `%` and `_` remain literal.
- Interactive Task start traverses the complete unified Workflow-library cursor before filtering to startable published Workflows; draft-only pages cannot hide a later published choice.
- A concurrent publish/open race either clones and pins one exact current revision or returns current accepted draft truth; it never labels stale client-copied content as based on a later revision.
- Library rows expose semantic draft/published state, last controller update, provenance, optional published revision, and only currently legal `edit | start_run` actions. Authoring options expose nonsecret configured default-provider selection or explicit absence without exposing credentials or adding browser provider mutation.
- YAML/JSON CLI import feeds the same service as browser JSON; exports round-trip semantics without promising comments/formatting.
- Task start pins the exact published revision read inside its transaction; later publication changes do not rewrite a running Task.
- Empty/reset bootstrap transactionally installs the complete Starter Workflow seed set with package-owned provenance. Identical reseeding is idempotent; a changed package-owned seed may advance a package-owned current revision but never replaces a user-authored current revision.
- There is no generic Definition route/tool/model branch or executing-agent Workflow lookup path.

## Task start and Assignment

- Interactive CLI chooses a published Workflow, accepts one editor prompt, defaults to cwd, and cancels without mutation on empty/aborted input.
- Non-TTY invocation without machine mode fails with exact next action.
- Inline, `@file`, and stdin JSON modes parse strictly, never prompt, write only JSON to stdout, and return stable errors/nonzero status.
- Unknown Workflow, invalid provider/workspace/file reference, and validation errors create no Task, directory, reference, Dispatch, or provider side effect.
- Omitted CLI workspace resolves to the invocation cwd. Omitted HTTP/Console/Operator workspace resolves only from configured controller workspace and returns a semantic 422 when absent; server process cwd is never a fallback.
- Accepted start atomically creates Task, pinned Workflow, initial TeamRevision, root Assignment, first Attempt, Dispatch, and exact request before start hint.
- Initial materialization creates Task-scoped, non-reused Member identities, immutable MemberConfigurations, deterministic child order, exact branch-basis relationships, and one `Task.current_team_revision_id` in the same admitted truth transaction.
- Admission follows validation -> controller-marked staging directory -> manifest/optional note projection -> DB truth commit -> provider hint. Recovery removes only stale marked directories with no committed Task, repairs committed marked Tasks, and reset never recursively deletes an accepted `.banksia/t_<id>/` directory.
- Root Assignment prompt equals the normalized human prompt exactly and every retry/continuation preserves the complete authoritative text.
- Child Assignments contain one exact prompt and ordered file references. There is no semantic summary/details precedence or derived text sent to providers.
- Repeated machine requests create distinct Tasks unless a transport idempotency facility explicitly applies; prompt text and Workflow ID are not deduplication keys.

## Advisory Work Plan

- Every Assignment may omit its Work Plan; absence never blocks execution or completion.
- The setter atomically replaces zero to nine ordered outcome-oriented steps, accepts at most one `in_progress`, permits all-completed, and clears on an empty list.
- Duplicate/filler steps reject, normalized identical requests are accepted no-ops, and concurrent replacements have one explicit winner.
- Same-Assignment continuation, retry, watchdog replacement, and restart retain the current plan; every fresh Assignment starts without one.
- Completed plan steps never route work, satisfy child participation, settle a Wave, create a Checkpoint, or complete an Assignment.
- Prompt/current-context expose the complete current human-readable plan, while product views omit private revision and authoring-Dispatch facts.
- No Work Plan projection file or second filesystem authority exists.

## Checkpoint and Result

- Progress Checkpoint records exact authoring lineage and ordered file references, creates no Boundary, and leaves the Dispatch current.
- Every present outcome in exactly `green | blocked | retry` is terminal for the current Dispatch and commits one internal accepted Boundary; no removed `return_boundary` path owns one of those variants separately.
- Green/blocked Checkpoint atomically validates and records file references, records terminal Checkpoint plus internal Boundary, closes Dispatch/Attempt/Assignment, and settles a Wave member only after commit.
- Green rejects when any current direct child configuration lacks accepted current-basis green participation.
- Blocked is a real terminal teammate report, does not satisfy participation, and does not cancel Wave siblings.
- Retry atomically records terminal retry Checkpoint/Boundary, closes the current Attempt, opens exactly one next Attempt/Dispatch, leaves Assignment and Wave member unsettled, and rejects after budget exhaustion.
- A root retry produces no Result. Only an accepted root green/blocked Checkpoint can become the exact user Result.
- Provider terminal output cannot create or replace any Checkpoint/result.
- Task result remains null until one exact accepted terminal root Boundary.
- Completed and blocked Result exactly equal that Boundary’s Checkpoint fields and file references after restart; a later provider message or another Checkpoint cannot replace it.
- Cancellation/control failure without an accepted root return has status and no fabricated Result.

## Replan, history, and participation

- Add attaches exactly one direct child to the authenticated caller, accepts a recursively all-new ID-less subtree, allocates collision-free IDs atomically, and returns them in deterministic structure/order.
- Update can target an existing descendant only within the caller subtree; omitted fields/children preserve, `null` clears allowed values, existing IDs patch in place, ID-less entries append, and unlisted siblings remain.
- `children: []`, attempted implicit deletion, ID mutation, reparenting, reordering, wrong-parent nested IDs, self/ancestor/sibling/outside targets, and unknown fields reject.
- Remove explicitly cascades a selected descendant subtree, never orphans, reparents, cancels, or reuses IDs.
- Add/update/remove reject affected pending/running work and roll back the whole candidate on every validation/CAS failure.
- Concurrent structural changes have one internal compare-and-swap winner; losers receive fresh current readback and allocate no leaked IDs.
- Retrying the same admitted operation does not allocate duplicate members.
- Each change creates one new current TeamRevision and leaves every historical TeamRevision, Member, Assignment, Attempt, Dispatch, Checkpoint, Boundary, file reference, and event unchanged and queryable.
- Updated configuration affects future Assignments/Dispatches only and invalidates the affected containing direct-child participation basis.
- Adding the first/removing the last child produces fresh derived Manager/Contributor behavior and allowed actions without a mode record.
- Every accepted replan closes its source Dispatch; manifest health gates one same-Attempt successor with exact structural trigger/result and fresh behavior/capabilities. Projection failure opens no provider work, and repair creates exactly one successor after restart or duplicate hints.
- Manifest atomically matches committed tree before a later Dispatch starts; forced projection failure preserves DB truth and blocks start until repair.

## Attempt currentness, waits, and control

- DB constraints reject two current Dispatches, current-plus-wait, two waits, a wait with zero/multiple sources, a terminal Attempt with current/wait, and wrong-task/source ownership.
- First/current/predecessor uniqueness is Attempt-local. Typed Task start, Wave member, retry, human, command, and recovery sources preserve cross-Attempt causality without a Flow-wide chain.
- Provider start, controller actions, watchdog, human request, command run, continuation, and cleanup all authenticate the exact Attempt lane plus global Task state.
- Same-Dispatch start retry reuses byte-identical request/configuration.
- Watchdog replacement changes only the affected lane.
- A human/command wait in one branch does not suspend siblings.
- Pause blocks new starts/continuations across all lanes while retaining committed results; resume enumerates every resumable lane/source; cancel prevents every late continuation.
- Startup audit converges current/startable Dispatches, open terminal sources, and ownership-loss cases without in-memory authority.
- One-lane comparison proves Flow/Attempt equivalence before Flow currentness fields are removed. Direct Task tests prove every residual global invariant before the complete Flow graph is deleted. Schema proof shows Dispatches and Wave members reference exact immutable TeamRevisionMember selections, every execution owner tuple is Task-scoped, and no `flow_id`, Flow structural head, or mutable FlowNode pointer survives.

## Delegation Wave and race matrix

Use DB constraints, conditional DML, and event/barrier-controlled tests. Timing sleeps are not concurrency proof.

Required cases:

1. One-member Wave matches intended sequential delegation and closes the parent Dispatch without `yield`.
2. Two through eight members commit all-or-none and provider starts can overlap under distinct sessions/bindings.
3. A ninth member rejects atomically. N members consume N of the snapshotted child-Assignment budget.
4. Parent cannot resume after only a subset settles.
5. Results render in delegation order even when completion order differs.
6. Green plus blocked returns one complete collect-all Continuation without cancelling siblings.
7. Retry remains on the same semantic Wave member and replacement Attempt can later settle it.
8. `A -> [B,C,D]`, `B -> [E,F]`, `E -> [G,H]` resumes only the immediate owner at every local join.
9. Two final-member commits create one Wave settlement and one parent continuation.
10. Duplicate, missing, late, and out-of-order settlement/continuation hints are harmless.
11. Crash after member commit, after Wave settlement, and after continuation commit converges without duplicate child/parent Dispatches.
12. Pause between settlement and continuation preserves the result and starts nothing until resume.
13. Cancel at every fan-out/fan-in stage prevents late continuation and preserves truthful history.
14. Watchdog, child boundary, human/command wait, replan, pause/cancel, and provider-start races have one explicit winner under SQLite and PostgreSQL.
15. Task completion is impossible with a live descendant Attempt or Wave.
16. Nested Waves may exceed eight total active descendants because the accepted baseline has a per-Wave guard only; tests document this known boundary and prove there is no hidden global queue/ceiling.

Invalid ownership shapes—wrong parent, non-direct child Assignment, boundary from the wrong Assignment, reused source Dispatch, duplicate member/result, or two Wave successors—must fail at the database/controller boundary.

## Shared workspace and Git

- Codex, Claude, and externally configured OpenClaw receive the same normalized workspace/cwd and physical Task path.
- Banksia neither detects nor rewrites OpenClaw sandbox/workspace configuration and exposes no managed fallback file tools.
- Git workspace preparation discovers the actual linked/main worktree root and exclude file, adds one idempotent anchored rule for the selected root or nested workspace's `.banksia/`, and never changes tracked `.gitignore`.
- Already tracked `.banksia` paths reject Task start before mutation.
- Task/Command ID generation uses the exact format, collision retry, and create-exclusive path behavior.
- Task initialization creates empty `notes/`, `artifacts/`, and `command-runs/` before the first provider Dispatch can start. Partial start failure leaves no taken-over or half-initialized Task path.
- Manifest/note/controller paths reject symlink substitution, traversal, special files, overwrite, and cross-Task escape.
- All members can observe the same project and Task files; integration tests demonstrate overlapping writes are possible and therefore not advertised as isolated/reproducible. Behavioral evals prove Managers sequence or disjoint high-value writes rather than assuming controller protection.

## Generic file references

- Public API/tool inputs accept only workspace-relative regular-file path plus optional description.
- Absolute paths, `..`, globs, NUL, URLs, directories, special files, and every symlink component reject without partial link/checkpoint/Assignment state, including symlinks that resolve back inside the workspace.
- A valid path is an existing regular file at attachment time. Validation and its owning Assignment, Checkpoint, or Human Request commit all-or-none.
- The controller records the ordered normalized path, optional description, owning message, and authoring lineage. It creates no generic file resource row, body copy, digest, version, current pointer, or materialization.
- Duplicate normalized paths reject within one owning `files` list. The same path may appear in separate owning messages without acquiring file identity.
- Repeating a path does not allocate identity or freeze bytes. Later mutation or deletion remains possible; native agent and scoped UI reads report the current or missing file honestly.
- Exact inventory and schema tests prove there is no capture/publish/promote, legacy Artifact CRUD/version, Operator `artifact_get`, or generic `file_get` operation.
- Ordinary project files, free-form Task notes, reviewable loose artifact files, and Command logs can all be referenced without changing their lifecycle or classification. The physical `artifacts/` convention creates no Artifact ID, body, index, version, approval state, or content API.

## Human requests

- Managed `open_human_request` accepts only `request`; provider binding supplies scope, and model-authored Task/Dispatch/capability selectors reject.
- Request kind is one allowed effective `input | direction | approval | review`; one to three unique-ID items each provide exactly one bounded valid response schema or two to three unique-ID options.
- Other and Skip are unavailable by default and render only when the exact item permits them. `allow_other` rejects without options.
- Optional `files` uses ordered file path/description references only; `context_refs` and `suggested_human_instruction` reject.
- Timeout default behavior requires a timezone-aware due time; answer, timeout, and cancel have one conditional winner and preserve exact resolution provenance.
- Answers use closed tagged value/option-ID/other/skipped variants. Copied option labels, unallowed Other/Skip, missing required item responses, and responses that fail the original schema reject without terminalizing.
- Successful open atomically commits source/wait/Dispatch close, returns the stop result, and later renders the complete original request plus exact resolution once in a same-Attempt successor.

## Command runs

- Managed `start_command_run` accepts only `request` with explicit argv or shell command, optional contained cwd, optional positive timeout, and bounded human purpose. Agent-authored environment refs, expected outputs, Task IDs, Dispatch IDs, and implicit shell conversion reject.
- Intent/wait commits before process launch; exact ownership, timeout, cancellation, termination, kill, reap, and ambiguous-restart behavior remain correct.
- stderr is redirected to stdout at process creation and one pipe is continuously drained to EOF.
- One `command-runs/c_<id>/output.log` receives the complete OS-observed combined stream. The database stores its path, observed/written byte counts, completeness, and lifecycle, but no second full output body.
- A bounded UI/API read limit never stops pipe draining or file writing and cannot deadlock the child.
- Success with stderr and failure with stdout show the complete observed combined stream rather than a preferred-stream heuristic.
- Invalid UTF-8, ANSI/control content, large tails, live reads, search/copy, scoped download, and browser sanitization are tested.
- Mutating or removing `output.log` cannot change DB lifecycle. UI identifies bounded views and reports a missing, changed-size, or incomplete current file honestly without claiming immutable audit bytes.
- Restart never relaunches an ambiguously owned command from file presence.
- Terminal continuation contains state, summary, optional exit/failure code, timing, one combined log path, observed/written/completeness facts, and provenance exactly once; it contains neither raw output nor split log refs.
- Linux and macOS child/grandchild process trees terminate and reap on cancel, timeout, clean controller shutdown, and controller-liveness loss. The admitted working-directory identity remains descriptor-backed without a Linux `/proc` dependency.
- Native quoting, shell selection, environment allowlisting, Unicode/spaced paths, and controller restart readback pass on every supported host.

## Prompt and current context

### Golden/serialization cases

- Initial Contributor, Manager, Task lead, Wave return, human result, command result, retry, recovery, and post-replan requests have exact fixtures per supported adapter.
- Instructions contain exactly one Manager/Contributor block and conditional Task lead/action/continuation/member/note content only when applicable.
- Denied Human Request/Command Run produces no tool, action-teaching block, or advertised action. Narrowed grants render only effective Human Request kinds and managed Command Run legality.
- XML has one root, stable field order, deterministic omission, required empty direct-team representation, UTF-8/LF/final newline, and semantic test parse.
- Markdown, code fences, Unicode, emoji, non-ASCII paths, `&`, `<`, `>`, quotes, `]]>`, XML-illegal characters, and closing-tag injection cannot break or change the typed structure.
- Initial request has no Continuation/trigger. Every successor nests exactly one trigger under Continuation with exact kind, source, and complete typed result; Assignment remains separate and complete.
- Full Assignment prompt/file references and every complete returned Assignment, Checkpoint, outcome, and file reference are present exactly once in authored order.
- Same-Dispatch restart sends byte-identical stored strings; adapter mappings never rerender or conflate instruction/input/tool lanes.
- Dispatch input and fresh current context use the same conceptual vocabulary.
- Removed Role/Policy/Skill/external-MCP/criteria/consume/produce/request-file/managed-file-tool/synthetic-trigger vocabulary is absent.
- Product nouns match the canonical glossary: Workflow is a reusable team definition, Delegation Wave is a controller-managed fan-out/fan-in group, Checkpoint is a teammate-facing work report, and `FileReference` is only a path/description navigation value. Prompt text does not reintroduce Artifact as a Banksia runtime noun.
- Workspace teaching clearly distinguishes mutable `notes/`, reviewable loose files under `artifacts/`, and natural project paths; it never implies either directory is controller truth, automatically opened, or inserted into another model context.
- Dynamic `available_actions` values equal the exact logical operation names in the current binding; aliases such as `replan`, `human_request`, or `command_run` never replace `add_child`/`update_child`/`remove_child`, `open_human_request`, or `start_command_run`.
- Exact tool names, parameters, bounds, enums, and result schemas occur in tool definitions rather than being duplicated in the system prompt.
- Each normative instruction has one owning prompt asset. Any deliberate repetition, including stop-after-transfer in a conditional action block, has a named behavioral evaluation proving why locality outweighs context cost.

### Behavioral cases

- Manager avoids the single-child relay trap and removes an irrelevant child rather than inventing filler work.
- A child “done” claim triggers inspection/verification rather than automatic green.
- Dependent work is sequential; independent reads can be parallel; shared high-value writes are sequenced or credibly disjoint.
- Contradictory reviews receive evidence-based resolution rather than concatenation.
- Implement-review-repair uses a feedback-bearing fresh Assignment, not retry.
- Batch Assignments remain item-specific and finish with integrated verification.
- Complex coordination gets one useful concise shared brief when it reduces duplication; simple work avoids ceremonial notes or file references.
- A material reviewable deliverable uses its natural project path or one useful file under `artifacts/`; routine edits are not duplicated into ceremonial artifacts.
- Scratch context needed across an Assignment boundary is referenced with path/purpose rather than assumed visible to an isolated provider; it is not promoted or copied into another domain.
- A material missing user decision uses an allowed Human Request; recoverable facts do not. Long-lived supervised work may use Command Run; ordinary short shell work does not.
- Successful Human Request, Command Run, delegate, replan transfer, or terminal Checkpoint stops the closed Dispatch immediately.
- Agents use `get_current_context` when freshness matters but not as an opening ritual.
- Task lead writes a human-facing exact terminal Result, not a child transcript or technical runtime report.
- Supported provider/model evaluations compare the revised prompt against its prior baseline. Wording is accepted only when accountability, delegation, transfer, and closeout cases do not regress; prompt shortening is not treated as success by itself.

## Product API and Activity

- Generated product schemas contain no Assignment/Attempt/Dispatch/Boundary/Wave/technical revision/hash/ref/provider route/watchdog/raw payload fields.
- Separately authorized support/audit contracts preserve all exact controller evidence needed for diagnosis.
- TaskView status, team, plan, attention, legal actions, nested file references, and singular result map from authoritative source records.
- Terminal root green/blocked produces exactly one semantic Task outcome Activity and exact Result; mid-flow boundaries produce neither outcome.
- Meaningful member returns carry safe human summaries/file references; plan, replan, start/watchdog, routing, and bookkeeping facts create no Activity.
- Human Request and managed Action lifecycle map to actionable plain-language variants without leaking technical IDs/state.
- UI-facing validation and failure responses provide stable field/problem identity, human-safe explanation, and one recovery action; raw exception, SQL, provider, or runtime text never becomes required product copy.
- Controller-returned legal actions include the user label, material consequence/confirmation requirement, typed inputs, and accepted receipt needed by the UI without reconstructing legality or runtime state.
- SSE backfill, reconnect, duplicate events, cursor reset, and payload-free refetch hints converge from controller truth.
- ETag/If-Match authoring and opaque action guards prevent stale browser writes without rendering runtime revisions.

## Console and Operator

### Independent nontechnical evaluation protocol

The required usability oracle is an independent no-doc evaluator that did not implement the slice. Give it only the plain-language user scenario and the running product. It exercises the real browser and records interaction notes, screenshots, accessibility snapshots, ambiguity, hesitation, wrong turns, and recovery under ignored `tmp/`. Automated browser, keyboard, zoom/reflow, and axe proof accompany that record. A real participant study may add evidence but is not mandatory for package or release completion.

### Workflow Studio

- Before implementation, each delegated slice verifies the pinned n8n commit, reads its assigned source packet and screenshots, and returns an adopt/adapt/reject record tied to Banksia contracts. Source reading without this decision record is not proof.
- Fresh/reset library state shows exactly `decision-through-competing-prototypes`, `deep-research-and-decision-brief`, `experiment-and-replication-program`, `idea-to-validated-demo`, `incident-investigation-and-recovery`, `migration-and-modernisation`, `production-feature-delivery`, and `security-audit-and-hardening`, with human “use when” descriptions, no provider claim, and exact narrow capability readback for capable Members. The three `advanced-*` reference examples remain absent from installed content.
- New Workflow starts with one selected lead, one right-side add control, and no type picker.
- Add opens an ID-less local Member form. A nonblank Name is required. Cancel/close performs no mutation; **Add Member** submits once, returned controller truth selects the accepted child, and the same trailing control follows that child.
- A rejected add preserves the local form for correction or retry without inserting a blank accepted Member.
- Accepted subtree removal selects and restores focus to the removed Member's surviving direct parent rather than unexpectedly returning to the lead.
- Pending, accepted, conflict, validation, failure, Undo, autosave, and publish states reconcile to controller draft truth.
- Horizontal broad/deep/collapsed/error/localized trees remain readable and connectors never imply execution flow. Deep-tree geometry is compared with the curated `add-child-sibling-branch.png` reference after interpreting every block as a Member and removing all n8n node/port meaning.
- Dragging a Member changes browser-local presentation position only. Tidy clears those offsets and recomputes hierarchy layout; Fit changes viewport only. Neither creates draft, runtime, or audit changes, and no drag can reorder or reparent a Member. Continuous drag proof shows no whole-canvas flash, blank frame, page movement, or card remount; only the moving card, attached add control, and connected lines change before drag stop.
- Member and Workflow settings use separate, mutually exclusive overlay drawers/bottom sheets. They preserve focus and selected-card visibility. Non-lead Member removal remains visible in the fixed Member footer, while the lead exposes no illegal removal action.
- Capability controls default off, edit only the selected Member, communicate no inheritance, and cover all four Human Request kinds plus managed Command Run without exposing generic tool/policy concepts.
- Keyboard and narrow-screen outline can select, edit, add, remove, publish, and start equivalently.
- Route-mocked browser tests prove controlled error and responsive states but never stand in for persistence proof. A repeatable disposable-controller browser lane proves create, edit, accepted add, reload, second-client ETag conflict and recovery, publish, and reopen against controller readback.
- An independent no-doc evaluator given only “create a small research team with two members” can create, understand, revise, publish, and recover from one rejected edit without docs or runtime terminology; observation records ambiguity, hesitation, wrong turns, and the correction.

### Run Studio

- A user can identify status, current work, required input, meaningful history, legal controls, referenced files, and exact Result without runtime-noun explanation.
- Open Human Request is pinned and commits through its own API; managed Action output is scoped/sanitized; result remains Task-level regardless of selected Member.
- Technical strings/identifiers and raw event/trace payloads are absent from DOM, accessibility snapshots, network product responses, and navigation.
- An independent no-doc evaluator can answer “what is happening, does Banksia need me, what can I safely do, and what was the result?” from the default Run view without opening support data or documentation.

### QuestionCard and Operator

- Question sets validate one to three questions and two to three options; controller allocates stable IDs and UI adds Other.
- Selection, custom text, allowed Skip, paging, focus, keyboard shortcuts, submit failure, double-submit prevention, receipt, reload, and responsive behavior pass accessibility/browser proof.
- Native `ask_user` output ends the provider turn and persists awaiting state; no provider process/tool call remains open. Answer starts a fresh turn on the same opaque thread after restart/navigation.
- The schema contains only `OperatorConversation` and ordered `OperatorConversationEntry` records. The product contract contains only status/list/create/get/message/answer routes, with no queue, invocation, effect, proposal, confirmation, retry, `operator_return`, or Operator SSE family.
- One active-turn compare-and-swap rejects concurrent message/answer work. POST idempotency returns committed readback for a same-body duplicate and rejects key/body mismatch without a second provider turn or mutation.
- Operator operations call the shared product services directly. Explicit user text or a committed typed answer supplies intent; Workflow ETags, Undo receipts, current opaque legal-action IDs, strict schemas, and owning transactions own currentness and acceptance.
- Operator tools cover every ordinary Workflow discovery/draft/team/publish, Run start/read/control, Human Request, managed Action, Result, referenced-file, and controller-returned legal-action service through the exact typed family that owns it, with no generic execute-anything operation or support/runtime/setup authority leakage.
- Exact inventory proves seventeen Banksia operations, full-JSON `workflow_draft_create`, and no eighteenth import, `ask_user`, `operator_return`, `artifact_get`, `file_get`, host, support, setup, or generic-execute tool.
- `workflow_get` has one closed source selector. Catalog reads return only metadata, exact published/draft source references, and bounded immutable history. Member reads require an exact published revision or exact draft ID/ETag and return one Member plus ordered direct-child IDs; an absent Member selector chooses the lead, and omitted versus explicit-empty `children` remains distinguishable.
- Operator Workflow mutations return only compact draft references, accepted-change/Undo/validation facts, allocated root Member identity when adding a subtree, or the published revision receipt. No mutation result or stale-draft failure contains a complete Workflow body.
- `task_get` defaults to a bounded overview with a flattened team and direct-child IDs, counts, truncation facts, excerpts, legal actions, and no loose file bodies. Closed selectors return one exact Member, Result, recent Activity item, Human Request, or Human Request file set from the named Task; legal maximum team prose no longer makes the overview unreadable.
- Operator Task control and Human Request response return compact post-commit state receipts. Shared HTTP response contracts remain unchanged, and exact follow-up content comes from a new explicit `task_get` read rather than replaying the mutation.
- Every Operator leaf result is compact-serialized once and checked against the controller-owned UTF-16 bound above before crossing a provider boundary. Oversize reads fail closed without the body; a post-commit failure is never replayed, and mutation receipts remain statically bounded below the guard.
- Claude native structured output and Codex 0.144.4 `outputSchema` plus `dynamicTools` both satisfy the same typed result and same-thread contract. Fresh and cold-resumed Codex turns prove empty execution environments, exact temporary effective cwd, empty runtime workspace roots, disabled external MCP and ambient extensions, and a code-mode nested registry containing only the seventeen Banksia operations plus inert `update_plan`. The nested `thread.cwd` is creation-time metadata and is therefore checked only on fresh start; resume proof checks the top-level effective cwd returned by `thread/resume`. Provider-native `exec` and `wait` have no host bindings, filesystem, shell, network, module imports, or independent Banksia authority; any wider registry or host surface fails availability. Proof does not claim a literal global seventeen-tool ceiling.
- Provider/tool/controller failure creates one bounded visible interruption, clears only the matching active turn, and refetches owning product truth when known. Restart and duplicate client submission never replay provider work or an uncertain mutation.
- The shipped Operator prompt is byte-identical to the appendix and teaches authoritative readback, missing-choice questions, explicit intent, accepted-result claims, uncertain-effect nonreplay, one typed result, and hidden-internal omission.
- Task Human Requests never lock unrelated Operator chat and do not share its persistence or continuation path.
- Operator messages show outcomes and interruptions, not chain-of-thought or raw tool traces, and never claim state absent a controller result/refetch.
- An independent no-doc evaluator can ask “create a workflow for me,” understand and answer the short clarification, inspect the draft, distinguish draft from publish, and recover from one failed action without knowing tool/MCP/provider/runtime concepts.

### Provenance

- The reference log records pinned n8n commit, exact files read, adopted, adapted, and rejected principles for every UI/UI-facing backend slice.
- The local sparse snapshot is clean, ignored, unpackaged, and contains no `.ee` enterprise path; its root license and selection manifest were reviewed.
- Source/dependency/license inventory shows no copied n8n Vue, CSS, markup, TypeScript, tests, strings, tokens, icons, assets, enterprise files, stores, routes, backend, or product model, including line-for-line React translation.
- Visual comparisons document independently implemented geometry/interaction, Banksia tokens/content, responsive behavior, and accessibility.

## Identity, layout, docs, and package release

- Import, module execution, CLI, distribution metadata, services, environment, config/data/database names, Compose resources, built-in server names, API identity, Console package, generated output, examples, and docs all use Banksia only.
- No AutoClaw compatibility import/command/config/state path survives.
- Final package installs from a fresh clone with `src/banksia`; backend tests live at `tests`; fresh Console lives at `console`; no `apps/`, empty wrappers, egg-info, or placeholder directories remain.
- Wheel/sdist/container/package-data inspection contains expected code/assets and no old identity, old docs, temporary bridges, or development debris.
- A clean backend wheel/sdist build and the installed-distribution verifier prove package integrity. Console-inclusive release proof additionally requires the shipped root Console build.
- Reset/setup uses the shipped path, not test-only table creation or direct helper calls; SQLite and PostgreSQL schema/integrity paths pass.
- Public/internal docs describe shipped Banksia only; no internal `design/v1`, `design/v2`, `current/v1`, `vnext`, archive, obsolete ADR, or old owner link remains.
- Docs format, link, authority/front-door, prompt catalog, generated schema/API, examples, and executable command checks pass at final paths.
- Exact stale searches cover identity plus removed Role/Policy/Task Compose/compiler/criteria/consume/produce/request-file/staged-yield/Flow authority terms with a reviewed narrow allowlist for legitimate dependency language.
- Distribution-name availability is rechecked immediately before publication.
- Ubuntu and macOS 13+ native lanes install the built wheel outside the checkout and prove CLI import/help, interactive-safe initialization primitives, exact schema/reset, workspace admission, private-path enforcement, Command Run process-family cleanup, and the native user-service lifecycle.
- Provider setup always lists the pinned Codex, Claude, and OpenClaw routes documented for that host. Diagnostics separately report installation, identity, reachability, and exact sandbox/network support; failure never disables, rewrites, or silently replaces a route.
- Fresh guided initialization completes local state, one Task-provider choice, and one optional Operator choice through the same provider configuration and diagnostic owner. Existing guided initialization offers `keep | reconfigure | cancel`; reconfigure keeps provider/default/Operator settings and labels them as kept.
- One initialization checks a shared Task/Operator provider once. Selecting an unconfigured, different Operator provider configures and checks that route while preserving the Task default. Same-call check reuse remains transient, and initialization renders compact provider facts rather than detailed limitations.
- An authenticated route without a live reachability probe reads **Ready for first task**. Reusing a detected credential takes one confirmation; declining opens authentication replacement.
- Guided Operator setup defaults to the persisted provider, preserves existing overrides when change is declined, supports explicit clearing, and offers a shared readiness check after a no-op without contacting the provider when declined.

## Required final proof matrix

The final Makefile/CI must expose and pass, at minimum:

- backend format/lint plus both configured type checkers;
- backend unit tests;
- real SQLite/integration tests;
- real PostgreSQL schema/runtime tests;
- bounded/reviewed/staged end-to-end runtime scenarios as applicable;
- Console format, lint, typecheck, generated OpenAPI drift, unit/component, API/SSE integration, production build, route-controlled browser e2e, and disposable real-controller browser e2e;
- keyboard/screen-reader/zoom/reflow and critical visual-state checks;
- documentation format/contract/link/prompt/generated-output/tests;
- provider adapter exact-request and native-workspace integration;
- fresh install, reset, start, restart/recovery, package-content, and stale-term audits.

Grouped commands must preserve the complete underlying coverage and print readable progress. A skipped external environment lane blocks a release claim unless its exact owner accepts and records the exception.

## End-to-end acceptance story

From a fresh clone and reset state:

1. configure managed providers and, separately, user-managed OpenClaw if used;
2. import equivalent YAML and JSON Workflows and publish one;
3. use Operator to ask one material question and draft/edit another Workflow;
4. use the canvas to add nested Members, Undo, publish, and start with one prompt in a Git workspace;
5. observe one shared `.banksia/t_<id>/`, correct manifest/Workflow note, initialized `notes/` and `artifacts/`, and exact root Assignment;
6. execute sequence, parallel, nested Wave, retry, command, Human Request, replan, iteration, batch, pause/restart/resume, and cancellation cases;
7. create and reference a working note, a reviewable artifact, and an ordinary project file; change and remove loose files, verify references stay truthful without claiming frozen bytes, and inspect a bounded tail of a large full Action log;
8. verify a Task lead cannot finish green without current-child participation;
9. receive exactly one integrated completed or blocked Result and semantic Activity; and
10. verify normal product network/DOM surfaces contain no technical runtime data while support audit retains exact lineage.

Only after this story, the full matrix, and the final two-round integration review pass may Banksia 0.1.0 be tagged.
