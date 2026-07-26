# Banksia coding agent contract

Status: Reference

This is the canonical root instruction surface for coding agents in this repo. Keep this file and `STYLE.md` short, stable, and authoritative. Put extended, example-heavy standards in [`.agents/standards/`](.agents/standards/README.md). If those standards disagree with this file or `STYLE.md`, the root files win.

## Product purpose

Banksia is an accountable agent-team runtime for complex work that must remain auditable, reproducible, trackable, and operationally recoverable.

- controller-owned runtime truth stays separate from provider behavior
- explicit routing and boundaries beat hidden conversational continuity
- Task-member, Operator, product, and support/audit lanes stay distinct
- prompts, Work Plans, loose files, reviews, and observability stay explicit enough to validate and recover

## Design philosophy

- start from the owning product contract and verify the shipped code against it
- change one ownership seam at a time while preserving controller invariants
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
- treat Banksia as one-process and local-tool-first until canon explicitly adds distributed delivery
- do not assume retries are safe to replay across queued or distributed delivery
- do not assume support-state files are authoritative controller truth
- do not introduce compatibility aliases without an explicit product contract
- do not assume provider terminal success implies assignment success
- do not assume missing contract details can be reconstructed safely from nearby code shape
- keep exact inline-versus-after-return timing and sync/async ownership with the owning subject page

## Authority split

- `AGENTS.md` owns shared repo policy, routing, verification expectations, and delegation rules
- `STYLE.md` owns measurable coding standards and refactor triggers
- `.agents/standards/*` owns long-form structural, readability, test, docs, and boundary guidance
- [Naming standard](.agents/standards/code/naming.md) owns long-form symbol, module, and package naming guidance
- [Source layout standard](.agents/standards/structure/source-layout.md) owns long-form monorepo, package-root, domain-first runtime, transport-thinness, and test-layout guidance
- public product docs, public reference/internals docs, and internal canon docs should remain distinct methodology layers
- `docs-internal/README.md` routes factual internal product and implementation owners under `architecture/`, `interfaces/`, `operations/`, and `verification/`
- durable accepted decisions live under `docs-internal/adr/**`
- public reference owns the external Workflow schema; internal interface and verification owners keep exhaustive prompt, operation, payload, and proof detail

## Instruction layering

- read this file first
- read `STYLE.md` second
- start from `docs-internal/README.md`, then read the smallest relevant internal owner pages before implementation work
- use `.agents/standards/*` for extended cleanup and layout guidance after the root surfaces
- if a closer subtree `AGENTS.md` is added later, treat it as local routing for that subtree, not a silent replacement for root canon

## Docs layout rule

The documentation layout is:

- public docs under `docs/**`
- maintained examples under `examples/**`
- factual internal owners under `docs-internal/{architecture,interfaces,operations,verification}/`
- durable accepted decisions under `docs-internal/adr/**`

Rules:

- keep public docs versionless by default
- do not create version-era, current-versus-target, archive, or migration authority lanes
- do not recreate deleted execution or archive trees just to satisfy stale references

## Source of truth rule

- subject pages routed from `docs-internal/README.md` are the internal product and implementation source of truth
- public reference owns external schemas and maintained examples; generated readbacks remain subordinate to their named internal owner
- frontend work consumes the product/interface owner, generated controller contracts, and the tracked n8n reference protocol as its data and study boundaries
- external design repos, ignored source clones, screenshots, and static HTML handoffs are visual, state, and interaction references only; they do not override controller-owned routes, fields, states, or legality
- code and tests can expose drift, but they do not silently overrule an owning contract; patch the owner and implementation together

## Mandatory read order

Read these in order before non-trivial implementation:

1. `STYLE.md`
2. `docs-internal/README.md`
3. the primary internal owner page for the touched surface
4. named public schema, generated-contract, prompt-readback, or reference-protocol owners when applicable
5. the smallest relevant subset of `.agents/standards/*`

For non-trivial frontend or UI-facing backend implementation, also read the relevant product contract and route sources before touching components:

1. `docs-internal/interfaces/console-and-operator.md`
2. `docs-internal/architecture/product-and-workflow.md`
3. `docs-internal/architecture/runtime.md` and `docs-internal/interfaces/runtime-tools.md`
4. `docs-internal/architecture/workspace-files-and-prompt.md`
5. `docs-internal/verification/gates.md`
6. `docs-internal/verification/n8n-reference-protocol.md`, including the exact packet and upstream files named for the slice
7. generated product contracts and current route sources for the implementation being changed

For non-trivial runtime implementation, start with these owner pages before provider-specific detail:

1. `docs-internal/architecture/runtime.md`
2. `docs-internal/interfaces/runtime-tools.md`
3. `docs-internal/architecture/workspace-files-and-prompt.md`
4. `docs-internal/architecture/system-prompts.md`
5. `docs-internal/architecture/product-and-workflow.md`
6. `docs-internal/operations/recovery-and-observability.md`
7. `docs-internal/verification/gates.md`

## Implementation fast path

1. Identify the smallest owner-contract/code delta.
2. Read the owner page and exact schema or generated contract.
3. Patch canon before implementation when the owner is silent or stale.
4. Add or update tests early.
5. Implement the bounded slice only.
6. Run the applicable tests, docs validators, and review checks before claiming completion.
7. If the blocker depends on exact case-sequence timing or sync/async ownership, patch the owning subject page instead of inventing shared catch-all canon.

## Answer-source hierarchy

Use this order when a design or implementation question comes up:

1. subject owners routed from `docs-internal/README.md`
2. named public schemas, internal generated contracts, and verification protocols
3. accepted ADRs under `docs-internal/adr/**`
4. repo code and tests

Rules:

- do not ask the user for answers already covered by an owning contract
- start from `docs-internal/README.md` and the named subject owner
- if canonical docs are silent, record the exact gap and patch canon before treating the answer as settled

## Shared implementation stance

- treat owning product contracts as override-first
- remove stale core logic instead of leaving parallel truth paths alive
- keep controller truth, provider behavior, projections, and product readbacks separate
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

- `make check-backend` runs lint, mypy, and pyright only; it is not a test command
- `make test-backend` and `make test-backend-unit` run `tests/unit`
- `make test-backend-integration` runs the canonical repo-native SQLite and runtime-template integration groups
- `make test-backend-db` runs the Docker/Postgres-backed integration groups only
- `make test-backend-e2e-bounded`, `make test-backend-e2e-reviewed`, and `make test-backend-e2e-staged` are the progressive e2e lanes
- `make console-format-check`, `make console-lint`, `make console-typecheck`, `make console-openapi-check`, `make console-test`, `make console-test-integration`, and `make console-build` are the console proof lanes
- `make console-e2e` runs route-controlled browser interaction, responsive, visual, and accessibility proof when Playwright browser dependencies are available
- `make console-e2e-real` runs the serialized disposable-controller browser persistence lane; route interception must not replace controller truth in this lane
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

For touched backend behavior under `src/banksia/**` or `tests/**`, run every applicable lane before claiming completion:

- `make test-backend`
- `make test-backend-integration` when the touched slice owns repo-native SQLite or runtime-template integration behavior
- `make test-backend-db` when the touched slice owns the Docker/Postgres verification shell, Postgres-specific behavior, or schema/reset proof that needs the stronger lane
- the relevant e2e lane when the touched slice reaches parent-first runtime flows, support-state truth, public CLI/API semantics, or other shipped end-to-end behavior

Prefer focused pytest selection while iterating, but do not claim completion until the applicable command matrix for the touched surface is green.

For touched frontend behavior under `console/**`, run every applicable lane before claiming completion:

- `make console-format-check`
- `make console-lint`
- `make console-typecheck`
- `make console-openapi-check` when API types, route usage, view-models, or API client code are touched
- `make console-test` for unit/component behavior
- `make console-test-integration` when the touched slice owns API-backed flows, SSE handling, request resolution, command-run actions, definition authoring, or task start
- `make console-build`
- `make console-e2e` when the touched slice changes navigation, page-level flows, browser-only behavior, visual parity, or accessibility-critical interaction and the local browser dependencies are available
- `make console-e2e-real` when the touched slice claims browser-visible persistence, restart/readback, optimistic-concurrency recovery, or another shipped controller boundary

## Repo-native quality gates

For touched Python backend surfaces:

- `ruff format`
- `ruff check`
- `mypy`
- `make pyright-backend`
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
