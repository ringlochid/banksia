# AutoClaw coding agent contract

Status: Reference

This is the canonical root instruction surface for coding agents in this repo. Keep this file and `STYLE.md` short, stable, and authoritative. Put extended, example-heavy standards in [`.agents/standards/`](.agents/standards/README.md). If those standards disagree with this file or `STYLE.md`, the root files win.

## Product purpose

AutoClaw is a controlled agent runtime for multi-step work that must stay auditable, replayable, and operationally recoverable.

We are building it so:

- controller-owned runtime truth stays separate from provider behavior
- explicit routing and boundaries beat hidden conversational continuity
- parent, worker, operator, and support lanes stay distinct products
- prompts, plans, artifacts, reviews, and observability stay explicit enough to validate and recover

## Design philosophy

- document target truth before trusting old code shape
- prefer rewrite-first when the current structure hides the target model
- keep recovery, routing, and ownership rules teachable
- treat docs, prompts, examples, and gates as implementation inputs
- keep support observability subordinate to controller truth

## Principles

- do not assume agents know the product concepts, nouns, or rules unless the prompt or docs restate them
- do not assume hidden transcript memory is sufficient for correctness
- do not assume cross-system context sharing is robust, cheap, or lossless
- do not assume filesystem state is canonical runtime truth unless canon says so
- do not assume repo-local YAML or packaged definition files stay canonical after a controller-owned definition registry exists
- do not assume validation preview is equivalent to publish-, start-, commit-, or runtime-time legality
- treat Phase 0-3 as one-process local-tool-first until canon explicitly reopens MQ or distributed-safe compatibility
- do not assume retries are safe to replay across queued or distributed delivery
- do not assume support-state files are authoritative controller truth
- do not assume old compatibility layers deserve to survive
- do not assume provider terminal success implies assignment success
- do not assume missing contract details can be reconstructed safely from nearby code shape
- keep exact inline-versus-after-return timing and sync/async ownership with the owning Phase 2 or Phase 3 docs

## Authority split

- `AGENTS.md` owns shared repo policy, routing, verification expectations, and delegation rules
- `STYLE.md` owns measurable coding standards and refactor triggers
- `.agents/standards/*` owns long-form structural, readability, test, docs, and boundary guidance
- [Naming standard](.agents/standards/code/naming.md) owns long-form symbol, module, and package naming guidance
- [Source layout standard](.agents/standards/structure/source-layout.md) owns long-form monorepo, package-root, domain-first runtime, transport-thinness, and test-layout guidance
- public product docs, public reference/internals docs, and internal canon docs should remain distinct methodology layers
- `docs-internal/design/**` is the long-term home for target design truth
- `docs-internal/current/**` is the long-term home for shipped-behavior contrast
- durable accepted decisions live under `docs-internal/adr/**`
- design appendix owners own exhaustive API, schema, prompt, and payload detail

## Instruction layering

- read this file first
- read `STYLE.md` second
- read the relevant `docs-internal/design/**` and `docs-internal/current/**` owner pages before implementation work
- use `.agents/standards/*` for extended cleanup and layout guidance after the root surfaces
- if a closer subtree `AGENTS.md` is added later, treat it as local routing for that subtree, not a silent replacement for root canon

## Docs layout rule

The current docs layout is:

- public docs under `docs/**`
- V2 target design truth under `docs-internal/design/v2/**`
- V1 target baseline and existing execution-era design truth under `docs-internal/design/v1/**`
- shipped-behavior contrast under `docs-internal/current/v1/**`
- durable accepted decisions under `docs-internal/adr/**`

Rules:

- prefer `design/` rather than `redesign/` in all live canon naming
- keep public docs versionless by default
- keep internal version eras explicit with directories such as `v1/`, `v2/`, and future draft-version directories
- do not recreate deleted execution or archive trees just to satisfy stale references

## Source of truth rule

- `docs-internal/design/v2/**` is the current target product and implementation source of truth for V2-owned surfaces
- `docs-internal/design/v1/**` remains the target baseline for existing V1 execution-era surfaces that V2 does not supersede
- `docs-internal/current/v1/**` is the current shipped-behavior contrast lane
- `apps/console/**` frontend work consumes controller contracts, OpenAPI, and V2 UI docs as data truth
- external design repos, screenshots, and static HTML handoffs are visual, state, and interaction references only; they do not override controller-owned routes, fields, states, or legality
- when V2 target pages and V1 target pages disagree about a V2-owned surface, V2 wins
- when target design truth and shipped contrast disagree about target behavior, target design truth wins
- code and tests can expose drift, but they do not overrule target design truth unless canon is silent and is being patched

## Mandatory read order

Read these in order before non-trivial implementation:

1. `STYLE.md`
2. the primary `docs-internal/design/**` owner page for the touched surface
3. any relevant `docs-internal/current/**` shipped-behavior contrast page
4. named appendix owners for exact API, schema, prompt, or payload detail
5. the smallest relevant subset of `.agents/standards/*`

For non-trivial `apps/console/**` frontend implementation, also read the relevant UI contract and route sources before touching components:

1. `docs-internal/design/v2/interfaces/console-runtime-surfaces.md`
2. `docs-internal/design/v2/interfaces/control-api.md` for current task state and task controls
3. `docs-internal/design/v2/interfaces/task-event-stream.md` for task chronology, SSE, and cursor reset
4. `docs-internal/design/v2/interfaces/human-request-and-approval-contract.md` for human-request surfaces
5. `docs-internal/design/v2/architecture/command-run-and-external-wait.md` for command-run surfaces
6. `docs-internal/design/v2/interfaces/definition-authoring-api-and-flat-draft-contract.md` for authoring surfaces
7. `docs/reference/api/api-surface-and-route-map.md` for current shipped route families
8. the relevant design-repo product brief, navigation contract, page charter, static HTML, screenshot, and shared CSS handoff

For non-trivial V2 runtime implementation, start with these owner pages before reading provider-specific or shipped-contrast detail:

1. `docs-internal/design/v2/architecture/runtime-lifecycle-and-watchdog.md`
2. `docs-internal/design/v2/architecture/runtime-records-and-control-state.md`
3. `docs-internal/design/v2/architecture/work-plan-and-checkpoint-contract.md`
4. `docs-internal/design/v2/architecture/task-root-and-file-access.md`
5. `docs-internal/design/v2/architecture/controller-contract-and-resumable-execution.md`
6. `docs-internal/design/v2/architecture/adapter-contract.md`

## Implementation fast path

1. Identify the smallest target/current-doc delta that owns the behavior.
2. Read the owner design page, current contrast page when it exists, and appendix owners for exact contracts.
3. If stale repo shape still dominates target-facing behavior, patch canon before treating the answer as settled.
4. Add or update tests early.
5. Implement the bounded slice only.
6. Run the applicable tests, docs validators, and review checks before claiming completion.
7. If the blocker depends on exact case-sequence timing or sync/async ownership, patch the owning design/current docs instead of inventing new shared canon.

## Answer-source hierarchy

Use this order when a design or implementation question comes up:

1. `docs-internal/design/v2/**` for V2-owned surfaces
2. `docs-internal/design/v1/**` and named design appendix owners for baseline or still-V1 surfaces
3. `docs-internal/current/v1/**`
4. repo code and tests

Rules:

- do not ask the user for answers already covered by design or current docs
- for V2 implementation slices, start from `docs-internal/design/v2/README.md` and the V2 owner page before falling back to V1
- when design and current disagree about target behavior, design wins
- use current only for migration truth or shipped-behavior contrast
- if canonical docs are silent, record the exact gap and patch canon before treating the answer as settled

## Shared implementation stance

- treat target design implementation as override-first
- remove stale core logic instead of leaving parallel truth paths alive
- keep current truth and target truth separate
- keep boundaries explicit and low-surprise
- keep one coherent top-level organizing model per shipped package root; do not mix transport edges, domain owners, and substrate buckets as peer families without an explicit canon reason
- prefer ecosystem-stable naming for grouped inbound surfaces, and keep contracts near the domain that owns them when that ownership is clear
- keep domain concepts typed and named directly
- persist canonical controller relationships as DB-enforced truth when canon names them as authoritative
- when a helper becomes shared across modules, promote it to a public shared surface instead of leaving it underscore-private
- when touched code drifts into structural cleanup, use `STYLE.md` plus [Repo layout standard](.agents/standards/structure/repo-layout.md), [Readability and refactor standard](.agents/standards/code/readability-refactor.md), and [Naming standard](.agents/standards/code/naming.md)

## Extended standards router

Use [`.agents/standards/`](.agents/standards/README.md) when the root contract is not enough but the question is still a repo-wide structure, style, docs, test, or boundary issue. Read only the smallest relevant subset.

- [Standards tree index](.agents/standards/README.md) — index, precedence, and use order for the standards tree. Go here first when you are not sure which deeper guide owns the issue.
- [Standards writing guide](.agents/standards/standards-writing.md) — how the standards stack itself should be structured, named, and maintained. Go here when editing `AGENTS.md`, `STYLE.md`, or any file under `.agents/standards/**`.
- [Readability and refactor standard](.agents/standards/code/readability-refactor.md) — long-form guidance for extraction, control-flow cleanup, helper shaping, whitespace phases, and readability-first refactors. Go here when a slice needs more than formatter output or crosses readability/refactor thresholds.
- [Naming standard](.agents/standards/code/naming.md) — naming rules for symbols, files, packages, schemas, routes, and CLI/API surfaces. Go here when naming or renaming anything shared, user-visible, or structurally important.
- [Repo layout standard](.agents/standards/structure/repo-layout.md) — repo tree, package splitting, family-stem cleanup, and ownership-by-path guidance. Go here when moving files, splitting directories, or cleaning flat-tree sprawl.
- [Source layout standard](.agents/standards/structure/source-layout.md) — monorepo root ownership, canonical backend package direction, transport thinness, and steady-state source layout. Go here when deciding long-term package roots, transport layering, or source-tree convergence.
- [Test structure standard](.agents/standards/structure/test-structure.md) — proof-lane ownership and where unit, integration, and e2e tests belong. Go here when adding tests, reorganizing test trees, or deciding what evidence is acceptable for a touched slice.
- [Integration boundaries standard](.agents/standards/structure/integration-boundaries.md) — seam ownership between API, services, runtime, registry, DB, CLI, OpenClaw, and support-state surfaces. Go here when a change crosses subsystem boundaries or risks putting logic in the wrong layer.
- [Docs structure guide](.agents/standards/docs/docs-structure.md) — public-versus-internal docs placement, page types, versioning, and docs information architecture. Go here when adding, moving, splitting, or reclassifying docs.

## Testing, proof, and commands

Use real shipped lanes for shipped behavior. Do not treat mocks or ad-hoc setup as equivalent proof when the touched slice owns persistence, runtime truth, CLI behavior, or end-to-end semantics.

Rules:

- add or update tests before claiming a behavior change is done
- where practical, start with a failing or gap-revealing test
- use real DB paths and shipped setup for integration, reset, schema, install, upgrade, and public-surface proof; unit lanes remain unit-scoped
- do not use mocks to stand in for shipped persistence, shipped runtime truth, or shipped public-surface behavior
- if a command, validator, or lane is skipped, record the exact scope reason or blocker in review
- if test-command expectations change, update this file and the owning command surface such as `Makefile` together

### Test command matrix

- `make check-api` runs lint, mypy, and pyright only; it is not a test command
- `make test-api` and `make test-api-unit` run `apps/api/tests/unit`
- `make test-api-integration` runs the canonical repo-native SQLite and runtime-template integration groups
- `make test-api-integration-local` remains a compatibility alias for `make test-api-integration`
- `make test-api-db` runs the Docker/Postgres-backed integration groups only
- `make test-api-e2e-bounded`, `make test-api-e2e-reviewed`, and `make test-api-e2e-staged` are the progressive e2e lanes
- `make console-format-check`, `make console-lint`, `make console-typecheck`, `make console-openapi-check`, `make console-test`, `make console-test-integration`, and `make console-build` are the console proof lanes
- `make console-e2e` runs browser e2e when Playwright browser dependencies are available
- `make check-console` runs the non-browser console gate: format check, lint, typecheck, generated OpenAPI drift check, unit/component tests, MSW-backed integration tests, and production build
- grouped runners must preserve the full coverage of the target they replace and expose readable progress

Docs commands:

- `make docs-format` rewrites maintained Markdown with the repo formatter
- `make docs-format-check` checks maintained Markdown formatting without writes
- `make docs-contract-check` validates authority metadata, links, front-door coverage, and docs-layer rules
- `make docs-inventory` prints maintained-doc and contract-finding counts
- `make docs-prompt-generate` regenerates prompt-catalog readbacks
- `make docs-prompt-check` validates prompt-catalog inputs and generated readbacks
- `make test-docs` runs the focused docs-tooling unit lane
- `make check-docs` runs the complete non-mutating docs gate

### Applicability

For touched backend behavior under `apps/api/**`, run every applicable lane before claiming completion:

- `make test-api`
- `make test-api-integration` when the touched slice owns repo-native SQLite or runtime-template integration behavior
- `make test-api-db` when the touched slice owns the Docker/Postgres verification shell, Postgres-specific behavior, or schema/reset proof that needs the stronger lane
- the relevant e2e lane when the touched slice reaches parent-first runtime flows, support-state truth, public CLI/API semantics, or other shipped end-to-end behavior

Prefer focused pytest selection while iterating, but do not claim completion until the applicable command matrix for the touched surface is green.

For touched frontend behavior under `apps/console/**`, run every applicable lane before claiming completion:

- `make console-format-check`
- `make console-lint`
- `make console-typecheck`
- `make console-openapi-check` when API types, route usage, view-models, or API client code are touched
- `make console-test` for unit/component behavior
- `make console-test-integration` when the touched slice owns API-backed flows, SSE handling, request resolution, command-run actions, definition authoring, or task start
- `make console-build`
- `make console-e2e` when the touched slice changes navigation, page-level flows, browser-only behavior, visual parity, or accessibility-critical interaction and the local browser dependencies are available

## Repo-native quality gates

For touched Python backend surfaces:

- `ruff format`
- `ruff check`
- `mypy`
- `make pyright-api`
- `./.venv/bin/python -m scripts.docs.style_audit.cli --fail-on-findings`
- the full applicable backend test command matrix
- exact repo search for retained underscore-private shared helpers, plus explicit review justification for any retained exception

For touched prompt assets, prompt-catalog inputs, or generated prompt pages:

- `make docs-prompt-check`
- `make docs-prompt-generate` first when inputs or generated pages changed
- `ruff check scripts/docs` and `mypy scripts/docs` when the slice touched `scripts/docs/*`

For touched TypeScript, frontend, or plugin surfaces:

- repo-native formatter and linter
- repo-native typecheck
- repo-native OpenAPI/generated-type drift check when the slice touches API contracts or API-backed view-models
- repo-native tests for the touched lane
- repo-native build
- Playwright browser and visual/a11y checks when page-level UI behavior, layout, navigation, or interaction changed

For touched docs:

- run `make check-docs`
- keep line wrapping and paragraph breaks intentional
- fix broken line-splitting instead of carrying it forward
- update the owning current, design, execution, standards, public product, or public reference surface instead of dropping truth into an unrelated page
- do not collapse public docs and internal canon into one undifferentiated tree; follow [Docs structure guide](.agents/standards/docs/docs-structure.md)
- keep new steady-state path planning aligned with `docs/**` for public docs and `docs-internal/**` for internal canon

## Delegation model

- the parent agent is the router and integrator
- the parent agent owns contract interpretation, critical-path design decisions, integration, final validation, and closeout
- check tool and runtime constraints before spawning subagents
- do not assume forked subagent-of-subagent flows are available, necessary, or appropriate; prefer parent-owned fanout unless the runtime explicitly supports the deeper fork and the plan truly needs it
- use subagents only for bounded slices with explicit owned surfaces
- every plan must say `no subagents` or define the delegated slices
- every delegated slice must be tagged `edit` or `review-only`
- every delegated slice must name the owner docs, owned surfaces, do-not-edit surfaces, required reads, expected outputs, required tests or validators, dependencies, evidence to return, parent-owned decisions, and stop conditions
- subagents must read the docs, tests, code, examples, and diagrams needed for their owned slice before editing
- keep parallel subagent edit surfaces separated
- make every subagent aware of the real user task, the approved plan, and the relevant WBS/work package rather than giving it a context-free patch brief
- when a second pass or independent check matters, use a review-only subagent explicitly
- while a delegation wave is running, the parent waits instead of making proactive repo-tracked edits
- after each delegation wave, the parent agent must verify scope, revert out-of-scope edits, integrate, validate, review, and patch before starting another wave
- for larger docs or codebase tasks, prefer multiple bounded slices over one overloaded child, but keep concurrency intentionally low and ownership explicit
- post-implementation review must verify that delegation respected ownership boundaries
- review-only slices must not edit files; if they do, the parent must stop the slice and revert those edits before integration

### Subagent brief standard

- every subagent brief must name the slice type (`edit` or `review-only`)
- every subagent brief must name the owner docs and bounded slice it serves
- every subagent brief must name owned surfaces and explicit do-not-edit surfaces
- every subagent brief must name the required docs, code, tests, examples, and diagrams the slice must read before editing
- every subagent brief must name expected outputs, required tests or validators, dependencies, evidence to return, parent-owned decisions, and stop conditions
- every subagent brief must tell the slice to stop and report back if the work needs surfaces outside owned or allowed collateral scope

### Wave safety standard

- while a subagent wave is running, the parent agent must not edit repo-tracked files proactively
- the parent agent must wait for the full wave before integrating or patching
- after the wave returns, the parent agent must compare each returned diff against the briefed owned surfaces and slice type before integrating
- the parent agent must revert any out-of-scope edits and any edits produced by review-only slices before integration
- the parent agent must run integration, validation, review, and patch after each wave before starting another wave

### Phase barrier rule

- a subagent may not advance work into a different owner surface or unrelated lane on its own
- if landing a slice would require a different owner doc, a canon patch, or surfaces outside the approved slice, the subagent must stop and return the blocker or handoff instead of continuing

## Review and closeout rule

Do not claim work complete until:

- the owner docs and approved bounded slice still agree with the landed diff
- code, docs, tests, and evidence are present together
- the mandatory review gate passes
- the reset gate passes when the touched surface owns DB schema, runtime record contract, package/install path, or public CLI/API truth
- docs-only progress is not being used where code or tests were required
- inspected-only evidence is not standing in for executed proof when executed tests were required and viable
- no locked-surface drift remains without an explicit re-scope or canon update
- no install, upgrade, or reset proof depends on test-only schema creation, direct helper invocation, or other non-shipped setup
- no behavior still reads authority from repo files after canon assigns that authority to controller-owned DB truth
- relevant stale migration terms have been searched before completion
- the final diff is clean against `AGENTS.md`, `STYLE.md`, and the relevant `.agents/standards/*` guidance
- any skipped lane, retained debt, or exception is written down with an exact owner and reason
- touched Python-owned surfaces do not retain unaccessed private helpers, duplicated logic, redundant branches, or underscore-private shared helpers without exact review justification

## OpenAI docs rule

When touching OpenAI, Codex, or API behavior and repo canon is silent or stale, use official OpenAI docs as the primary external source. Treat external blogs, issue threads, or examples as secondary support only.

## If the docs are silent

If design, current, execution, and the relevant standards are still silent:

1. verify the current code and tests
2. use primary framework docs for the exact technology involved
3. record the canon gap
4. patch the owning canonical surface before calling the answer settled
