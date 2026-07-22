# Banksia migration target

Status: Target

Decision record: accepted 2026-07-22; revised 2026-07-23.

## Strategy

Banksia is a clean product reached through an evolutionary implementation, not a second runtime and not a delete-and-rewrite event:

```text
characterize proven AutoClaw controller substrate
  -> establish compact Banksia authority
  -> cut over identity
  -> put simple Workflow and Task/Assignment contracts in front
  -> establish the shared native workspace and prompt
  -> simplify replan and participation
  -> move currentness to Attempt
  -> introduce recursive Waves
  -> expose semantic product APIs
  -> contract and move the stable backend
  -> build a fresh Console and Operator
  -> rewrite docs and remove every legacy path
  -> whole-program review and repair
  -> clean-root release decision
```

Each package must leave one coherent executable system. Temporary bridges are internal, named, tested, deletion-tracked, and unavailable as public compatibility contracts.

Do not:

- create parallel `banksia_v2` source, schema, API, or persistence trees;
- mechanically rename obsolete concepts before deleting them;
- change identity, domain semantics, persistence authority, layout, and UI in one unreviewable diff;
- delete current tests and replace them only with target happy paths;
- preserve old public aliases “temporarily” without an exact deletion package; or
- treat ignored target notes as shipped authority after a tracked owner exists.

## Starting-point interpretation

The current tracked repository is the imported AutoClaw 0.1.8 baseline under the Banksia Git repository. Its implementation is now hosted under the Banksia-only `apps/api/src/banksia` package, while `apps/api/tests`, `apps/console`, frozen V1/V2/current documentation, the Role/Policy/compiler model, and the single-Flow execution shape remain migration evidence—not the target layout or product language.

Current code and tests can expose invariants and regressions, but they do not override the accepted target. Conversely, a target simplification does not authorize deletion until the responsibility is either proven unnecessary or has a tested new owner.

The first package must rerun and classify the complete current proof matrix. Prior sync receipts and an interrupted later test run are evidence, not a current green claim.

## Preserve-first inventory

Retain or strengthen these controller properties while changing their owner or public presentation:

- immutable published Workflow revisions and Task pinning;
- exact Assignment/Attempt/Dispatch identity and source lineage;
- one exact current-authority predicate per execution lane;
- exact immutable Dispatch requests and same-Dispatch retry;
- commit controller intent before provider/process side effects;
- post-commit effect publication with duplicate/lost-signal recovery;
- provider-start reservation/retry and startup audit;
- watchdog replacement and ownership-loss handling;
- typed human/command waits and exact-source continuation;
- durable Checkpoints and internal AcceptedBoundaries;
- terminal outcome selected by exact relationship rather than time;
- exact ordered `FileReference` values on their owning controller messages, plus honest mutable/missing-file behavior;
- structural revision compare-and-swap and immutable history;
- pause/resume/cancel and recovery over every current lane; and
- raw internal event/audit truth separate from user projections.

Preserve semantics before names or current table shapes. For example, the single Flow pointer is removed, but exact currentness becomes stronger at Attempt scope.

## Replace or remove

| Current family | Final disposition |
| --- | --- |
| Role + Policy + Workflow composition | One self-contained recursive Workflow with only narrow per-Member Human Request/Command Run grants. |
| Generic Definition registry and tools | Workflow-specific catalog, draft, publication, revision, and authoring services. |
| Definition compiler and CompiledPlan graph | Workflow normalization/semantic validation plus initial Task-tree materialization. |
| Task Compose and preview | One transient TaskStartRequest and atomic start service. |
| Assignment summary/instruction/criteria/consume/produce | One exact prompt plus optional file references. |
| Separate checkpoint/release ceremony | One Checkpoint action: omitted outcome is progress; `green`, `blocked`, and `retry` are terminal for the current Dispatch and preserve an internal boundary. |
| Release basis/evidence/criteria gates | Participation, exact current authority, useful loose file references, and accountable terminal Checkpoint. |
| Legacy Artifact publication/body/slot/version/current-pointer families | Delete. Keep only ordered `{path, description?}` values owned by Assignment, Checkpoint, or Human Request; Activity and Result mirror source values. |
| Human Request context refs and suggested instruction | Preserved typed request with optional file path/description values and system-prompt teaching. |
| Command Run environment/expected-output refs and split logs | Controller-approved Task environment, simple command/cwd/timeout/summary request, and one combined log that can be referenced directly. |
| Generic projection/task-root families | Physical `.banksia/t_<id>/` with manifest, optional Workflow note, free-form `notes/`, loose reviewable `artifacts/`, and command logs. Only the first two are projections. |
| Request-pair files and managed note/file tools | Exact DB request strings and provider-native filesystem access. |
| Root/parent/worker prompt families | Task lead overlay plus derived Manager/Contributor behavior and typed XML input. |
| Staged one-child assignment + yield | Atomic one-or-many DelegationWave and AttemptWait. |
| Flow-wide current Dispatch/wait | Attempt-local currentness/waits; residual global fields fold into Task; Flow deleted. |
| Raw Task Event product feed | Semantic TaskActivity and TaskView; raw chronology remains support/audit truth. |
| Current Console | Delete after evidence extraction; build root Console fresh. |
| Versioned AutoClaw docs | Versionless Banksia public/internal docs; Git is history. |

## Deletion gate

A removed concept may disappear only when all five facts are true:

1. a named target owner exists;
2. all authoritative writes have moved;
3. all authoritative reads have moved;
4. characterization plus target tests prove the replacement invariant; and
5. exact searches show no runtime, interface, test, fixture, generated client, packaged resource, prompt, example, or live document still depends on it.

“The new schema does not mention it” and “the old code is complicated” are not deletion proof. A compatibility adapter that survives its exit gate is a release blocker.

## Ordered implementation program

### 0. Authority and characterization

- Promote a compact, versionless Banksia implementation canon, exact Workflow schema, maintained reference examples, and separate provider-neutral seed fixtures at final tracked internal paths, then update repository instruction routing.
- Promote a tracked n8n reference-protocol appendix with pinned commit, sparse selection, license boundary, packet map, and delegated evidence fields; keep the actual source clone ignored under `tmp/` and out of packages.
- Mark existing V1/V2/current pages frozen nonauthoritative migration evidence; do not keep editing them as a second target.
- Create table-, route-, prompt-, generated-contract-, seed-, and UI-level retain/adapt/remove ledgers.
- Characterize start, pinning, currentness, exact requests, continuation, Checkpoints/file references, structural change, typed waits, provider start, watchdog, pause/resume/cancel, recovery, SSE, and public CLI/API behavior.
- Run the complete baseline matrix and record exact pre-existing failures.

Exit: one target authority and enough executable characterization to detect lost controller invariants.

### 1. Behavior-neutral Banksia identity

- Change product/import/CLI identity while temporarily retaining `apps/` layout.
- Distribution: `banksia-ai`; Python import/module and CLI: `banksia`.
- Rename package discovery, entry points, environment prefix to `BANKSIA_`, service/config/data/database/Compose resources, API title, built-in MCP servers, backend fixtures/generated output, scripts, examples, and safe current commands.
- Leave the disposable legacy `apps/console` implementation unchanged except for the minimum API compatibility needed to keep characterized gates running. Keep its stale identity on a shrinking allowlist and delete it after the new root Console is proven; do not spend the identity package renaming its visual tokens or package surface.
- Keep no AutoClaw import, CLI, environment, config, or state fallback alias.
- Reset development state instead of migrating AutoClaw databases.

Exit: existing characterized behavior runs only through Banksia identity while layout and semantics remain otherwise unchanged.

### 2. Workflow-only authoring

- Implement the target recursive schema, strict JSON/YAML ingest, normalization, semantic validation, structured drafts, publish, immutable revisions, history, Task pinning, and the separate general Starter Workflow seeds. Do not package or seed the maintained reference examples. Every packaged seed recursively omits `provider` and `capabilities` while retaining the accepted OMC/OMX-inspired responsibility patterns in ordinary Banksia language.
- Replace Policy capability lookup with the Workflow Member's default-deny Human Request/Command Run request plus controller-narrowed effective Dispatch grants. Do not migrate old grants or preserve generic policy lookup.
- Specialize public contracts around Workflow and remove outward Role/Policy/generic Definition surfaces.
- Introduce `materialize_initial_task_team`; a temporary adapter may translate into legacy launch records with removed fields empty/defaulted.
- Rewire executing agents away from Role/Policy rereads before dropping their persistence.

Exit: every new published input is one Workflow; no model-visible/runtime behavior depends on Role/Policy; the temporary materializer is named and has a deletion package.

### 3. Task start, Assignment, Checkpoint, Result, and file references

- Route CLI/HTTP/Console/Operator through TaskStartRequest.
- Introduce exact Assignment.prompt behind one temporary old-column adapter if needed; do not expose both shapes.
- Implement the one Checkpoint action, internal accepted boundaries, retry semantics, exact root Result, and simple ordered file references. Preserve all three terminal Checkpoint outcomes: green/blocked close the Assignment; retry closes only the current Attempt and opens a replacement for the same immutable Assignment.
- Delete legacy Artifact publication/body/current-pointer models and all capture, promote, version, materialize, and rematerialize operations once no new Assignment/Checkpoint reader depends on them.
- Remove Task Compose, criteria/consume/produce, model-visible release, and duplicate result prose after replacement proof.

Exit: exact human/child prompts survive retry/continuation; one accepted root Checkpoint is the user Result; invalid start/checkpoint/reference mutations are atomic.

### 4. Shared physical workspace, loose files, and command output

- Materialize the target `.banksia/t_<id>/` layout inside the user-selected shared workspace, including empty controller-created `notes/`, `artifacts/`, and `command-runs/` directories before first provider start.
- Implement safe Git exclusion/tracked-path rejection, manifest/note projections, free-form notes, loose reviewable artifacts, safe regular-file reference validation, and combined protected/visible command output.
- Bind every adapter to the same workspace. OpenClaw readiness remains the user’s externally managed prerequisite; Banksia adds no inspection/fallback.

Exit: paths, symlinks, overwrite, mutable/missing file references, note/artifact directory semantics, restart, and command truncation behave exactly as documented; the lowercase `artifacts/` convention exists but no legacy Artifact resource or capture machinery remains.

### 5. Dispatch request and prompt

- Persist exact `instructions` and `input` per Dispatch.
- Temporarily dual-publish old request files only to assert byte equivalence.
- Implement conditional Banksia instruction assets, deterministic escaped XML, complete continuations, conditional Human Request/Command Run teaching, one context projection, notes-versus-artifacts guidance, terminal retry scope, and behavioral evaluations from the exact system-prompt owner.
- Map exact lanes through each adapter.
- Delete request files and list/read/write-note operations at the exit gate.

Exit: same-Dispatch restart is byte-identical; initial and continuation prompts are complete; no removed vocabulary or file-tool path remains.

### 6. Recursive replan and participation on the sequential engine

- Implement caller-bounded recursive add/update/remove, controller IDs, immutable history, busy guards, internal CAS, exact invalidation, fresh response context, and atomic manifest regeneration.
- Derive Manager/Contributor and enforce current direct-child green participation while retaining one-child execution underneath.

Exit: structural behavior is proven independently of the concurrency rewrite.

### 7. Attempt-local currentness and typed waits

- Introduce Attempt current Dispatch and one typed AttemptWait.
- Migrate provider start, watchdog, controller-operation authority, human and command waits, continuation, retry/recovery, pause/resume/cancel, cleanup, and startup audit one source family at a time.
- Assert one-lane Flow/Attempt equivalence during migration, then remove Flow current/wait truth and its uniqueness constraints.

Exit: distinct nested Attempts can be current without a global pointer and every Task-wide control safely enumerates them.

### 8. Delegation Waves

- Add one-member Wave as the only delegation path and prove parity before deleting staged child/yield.
- Generalize to up to eight members; publish all child starts after commit.
- Prove collect-all local joins, authored ordering, retry, blocked siblings, cancellation, pause gap, duplicate/lost hints, nested recursion, and crash recovery.
- Document shared-workspace parallel-write risk; do not add isolation or a Task-wide queue as hidden scope.

Exit: recursive fan-out/fan-in creates exactly one continuation at every level.

### 9. Semantic API, backend contraction, and root layout

- Fold final global Flow fields into directly tested Task fields and delete Flow in the existing backend tree before changing product contracts or paths.
- Implement Workflow draft/tree APIs, TaskView, attention/actions/result, semantic TaskActivity/SSE, scoped Action output, and separate support/audit contracts against those final records. Freeze exact product and support service/route inventories plus separate OpenAPI documents before either the Console or Operator consumes them.
- Shape every UI-facing product response for nontechnical consumption: semantic state, human-safe errors/recovery, legal actions, consequences, typed input, and receipts without frontend runtime classification.
- Finish removal of Role/Policy, generic compiler/registry, Task Compose, criteria/consume/produce, request files, staged delegation, and remaining Flow authority.
- Extract useful legacy Console API/SSE/accessibility scenarios into contracts or target tests.
- Only after the existing-tree Flow contraction and semantic product/support contracts pass, move the stable backend without semantic rewriting to `src/banksia/` and tests to `tests/`; remove `apps/api` and update pyproject, Makefile, scripts, generated contracts, Docker/infra, CI, package resources, tooling, and backend path references in `AGENTS.md`, `STYLE.md`, and relevant standards.

Exit: final backend layout and semantic product contracts pass fresh install, reset, SQLite/Postgres, provider, runtime, package-content, and generated-client proof.

### 10. Fresh Workflow Studio

- Before delegation, fetch or verify the pinned license-audited sparse n8n source snapshot under ignored `tmp/`. Give every UI edit/review slice its exact source packet and require adopt/adapt/reject plus provenance evidence.
- Create a new root `console/`; do not move old Console code.
- Update Console path references in `AGENTS.md`, `STYLE.md`, and relevant standards only after the root application exists. Build to `console/dist/` and stage distributable UI assets through an ignored generated-assets path.
- Implement the Workflows shell, horizontal hierarchy, structured Member editing, ETag autosave, Undo, explicit publish, trailing add, Tidy/Fit, responsive drawer/sheet, and accessible outline.
- Independently author React/Tailwind UI after studying the pinned source and curated screenshots; import, copy, or line-for-line translate no n8n source, tests, CSS, strings, tokens, or assets.

Exit: the complete Workflow authoring journey passes generated-contract, unit/integration, browser, visual, responsive, accessibility, provenance, and independent no-doc comprehension/recovery gates.

### 11. Run Studio and Operator

- Implement Run start from the shared TaskStartRequest, Runs list, read-only team, semantic Activity, attention, Actions and protected log access, Human Requests, referenced files, exact Result, and legal controls.
- Implement durable Operator threads, structured tool use, typed question turn, QuestionCard, confirmations, receipts, Undo, and controller-truth refetch.
- Re-verify and use the pinned Run/log/question/chat reference packets in every edit/review brief, while keeping Banksia product contracts authoritative.

Exit: a nontechnical user can understand, answer, control, and consume a Run and ask Operator to draft work without docs, tool/provider concepts, or technical runtime data.

### 12. Final contraction, docs, and release-candidate preparation

- Delete `apps/console`, every temporary adapter, obsolete model/table/route, empty wrapper, stale asset, fixture, generated artifact, and compatibility name.
- Rewrite root/public/internal documentation from shipped Banksia behavior; reissue only still-governing ADRs.
- Delete frozen `docs-internal/design/v1/**`, `docs-internal/design/v2/**`, `docs-internal/current/v1/**`, old superseded ADRs, and obsolete public pages. Preserve and finish the versionless `docs-internal/design/**` Banksia owners created by WP-00; keep no V1/V2/vnext/current-target/archive lane.
- Prepare and inspect local release-candidate artifacts and run cleanup-focused identity, path, package, docs, and stale-reader proof.

Exit: one versionless Banksia product, code layout, documentation system, and local 0.1.0 release candidate remain. Git history is the only historical archive.

### 13. Whole-program integration review, repair, and release decision

- Reconcile every accepted decision, work-package objective, temporary-bridge ledger, deferred finding, generated contract, and verification gate against the complete integrated tree.
- Run independent whole-program review round one, fix all fix-now findings, and rerun affected plus full proof.
- Run a fresh independent whole-program review round two, fix all remaining fix-now findings, and repeat the full release matrix.
- Execute the clean-clone end-to-end acceptance story across backend, SQLite, PostgreSQL, providers, workspace/recovery, Console, Operator, browser, accessibility, docs, packaging, and stale-term/provenance audits.

Successful exit: no P0/P1, unexplained integration gap, live bridge, release-blocking debt, or required unexecuted lane remains, and the parent records the final local release **go** decision. Any **no-go** records the exact blocker and owner, leaves the package/program stopped or blocked, and is not completion. No publication or deployment is implied.

## Final repository layout

```text
src/
  banksia/
tests/
console/
docs/
docs-internal/
examples/
infra/
scripts/
tmp/                     ignored research, target planning, and orchestration
```

Keep `src/banksia` as the protected Python import namespace. Do not flatten generic packages such as `runtime`, `interfaces`, or `persistence` directly under `src`, and do not reserve an `apps/` taxonomy for hypothetical future applications.

The root `pyproject.toml` owns the one Python distribution. Root tests mirror the backend package. Root Console retains its own package/build boundary. Empty directories and placeholder `.gitkeep` files do not survive.

## Identity completion

The final tracked tree must use:

| Surface | Target |
| --- | --- |
| Product | Banksia |
| Distribution | `banksia-ai` |
| Import/CLI/module | `banksia` / `python -m banksia` |
| Environment prefix | `BANKSIA_` |
| Service/config/data namespaces | `banksia` |
| Console package | `@banksia/console` |
| Built-in controller servers | Banksia-named |
| First release | `0.1.0` |

Recheck distribution registry availability at publication time. Preserve the existing Git commit history and origin; historical commits may contain AutoClaw. Final source, tests, generated files, package contents, services, configs, examples, UI, and live docs may not.

No AutoClaw CLI/import/config/state/database compatibility alias ships. This is a reset-only product baseline.

## Documentation cutover

Use two passes:

1. Before semantic implementation, create compact versionless target owners and make them authoritative while freezing old trees as migration evidence.
2. After backend layout, Console, Operator, and generated contracts are stable, replace the complete public/internal corpus and delete every old versioned tree in WP-12. WP-13 then independently checks documentation against the integrated shipped contracts and fixes any remaining drift.

The final internal structure is exactly `docs-internal/{architecture,interfaces,operations,verification,adr}/`—not design/current or release eras. Public docs are organized by user need: getting started, guides, concepts, reference, and help.

Do not mechanically rename old prose, retain redirects/archives, or document unimplemented behavior. Update AGENTS/STYLE/standards, docs discovery and formatting, prompt catalog, generated references, tests, navigation, links, and package inclusion with the cutover.

## License and external-reference boundary

The repository’s MIT license remains. Banksia’s free/no-paid-plan product intent does not narrow the permissions of that license.

n8n screenshots and the pinned sparse source clone under ignored `tmp/` are visual, interaction, component-boundary, responsive, accessibility, and test-strategy research only. Final Console code is independently authored; there is no literal or line-for-line translated n8n TypeScript/Vue, tests, CSS, markup, strings, tokens, icons/assets, enterprise source, backend, or product model whose license/provenance must be carried into shipped Banksia.

## Release barrier

Do not publish, tag, archive AutoClaw, or call the migration complete until:

- target owner docs, implementation, generated contracts, package contents, reset schema, and tests agree;
- all temporary adapters and old readers/writers are gone;
- full backend, DB, runtime, Console, browser, accessibility, docs, provider, install, reset, restart, and recovery gates pass;
- stale identity/concept/path searches are clean under an explicit narrow allowlist; and
- a fresh clone can install, configure, author/import a Workflow, start and complete a representative Task, recover from restart, and render its exact Result; and
- WP-13's two independent whole-program review/fix rounds complete with no unresolved P0/P1 or release-blocking evidence gap.

The reproducible local candidate build is `make package-build`; release proof does not substitute a bare `python -m build` that omits the Console asset pipeline.
