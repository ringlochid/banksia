# Source layout standard

Status: Reference

Use this guide when restructuring the repo tree, choosing package roots, consolidating transport layers, moving provider integrations, or deciding the steady-state layout for tests and runtime code.

## Goals

- keep one obvious owner for each major source tree
- keep the repository organized by shipped source, product surfaces, docs, infrastructure, scripts, and maintained examples
- keep shipped backend code under one canonical import package
- keep transport surfaces thin and runtime/domain packages owner-driven
- let tests mirror product and boundary ownership rather than redesign history

## Repository root rules

The final top level is product- and ownership-oriented:

- `src/banksia/**`: the one shipped Python backend package
- `tests/**`: backend proof mirroring package and boundary ownership
- `console/**`: the independently authored browser product
- `docs/**`: public docs
- `docs-internal/**`: internal canon docs
- `examples/**`: maintained importable examples, never runtime authority
- `infra/**`: deployment, runtime infrastructure, and packaging support
- `scripts/**`: repo, docs, and test tooling
- `tmp/**`: ignored research and orchestration material

Do not reserve an `apps/**` taxonomy for hypothetical future applications. Do not add top-level directories merely to sort by language, build tool, or temporary migration state when an existing owner fits.

During the ordered migration only, `apps/api/src/autoclaw/**`, `apps/api/tests/**`, and `apps/console/**` remain current AutoClaw baseline locations. They are migration evidence and temporary implementation hosts, not Banksia target layout or naming authority. Never create a parallel target package beside them before the planned root-layout cutover.

## Canonical backend package rule

- shipped backend Python code should converge to one canonical import package
- compatibility import paths may exist during migration, but they must stay thin and explicitly temporary
- do not let two long-lived source trees both act like the real backend owner

For Banksia, the canonical backend package is `src/banksia/**`. No parallel `autoclaw`, `banksia_v2`, or unwrapped package tree may remain in the final layout.

## Packaging-aware source root rule

- when packaging/import-path safety matters, prefer a packaging-aware source root such as `src/<package>/`
- the `src/` layout is the steady-state default when it helps prevent local import leakage and packaging mistakes
- use flat package layout only when the simplicity benefit clearly outweighs the import-path risk

For Banksia, the steady-state package boundary is:

```text
pyproject.toml
src/
  banksia/
tests/
```

## Transport-layer thinness

Transport owners exist to expose product surfaces, not to become business-logic dumps.

- `interfaces/http/**` should own HTTP parsing, dependency wiring, handler dispatch, and response mapping
- `interfaces/cli/**` should own command parsing, prompting, rendering, and exit-status mapping
- transport owners should not become the long-term home of runtime, registry, or provider-integration business logic

For Banksia, CLI code should converge toward one coherent owner inside `src/banksia/**`, such as:

```text
interfaces/
  cli/
    commands/
    output/
    prompts/
    main.py
    root.py
```

instead of splitting durable CLI ownership across several top-level lanes.

## Root taxonomy coherence

Choose one clear top-level organizing model per shipped package root.

- do not mix transport owners, domain owners, and generic substrate buckets as peer top-level families in the same steady-state package without an explicit canon reason
- when a backend package exposes several public edges, prefer one `interfaces/**` owner with subowners such as HTTP, CLI, and MCP instead of separate sibling transport trees
- when several source families belong to one bounded domain such as Workflows, prefer one domain owner such as `workflows/**` over separate root siblings for parsing, drafts, publication, history, and Starter seed resources
- prefer `persistence/**` for durable storage ownership, and prefer domain-owned contract lanes such as `workflows/contracts/**` and `runtime/contracts/**` over one generic root contract bucket when contract ownership is clear
- keep `runtime/**` as the owner of controller behavior, and keep reusable provider substrate under `integrations/**`

## Public interfaces rule

When the package exposes several public transport edges, group them under one explicit interface owner.

- prefer `interfaces/http/**` for HTTP route surfaces
- prefer `interfaces/http/contracts/**` for HTTP-owned transport contracts, presenters, and support models that exist only to serve the HTTP boundary
- prefer `interfaces/cli/**` for CLI noun-family surfaces
- prefer `interfaces/mcp/**` for MCP or similar server-facing surfaces
- prefer `interfaces/http/routers/**` for noun-owned route modules, with `router.py`, `dependencies.py`, and `errors.py` at the `http/` owner root
- keep route modules noun-owned and near the transport edge they expose
- do not keep support modules such as `*_models.py`, translators, or contract helpers inside route-only packages; move them to `interfaces/http/contracts/**` or another clearly named transport-contract owner
- do not keep DB transaction control, runtime effect-runner waits, or controller orchestration inside HTTP route modules

## Domain-first backend structure

Prefer bounded-context or product-owner packages before top-level implementation-mechanic packages.

- split first by domain owner: `tasks`, `workflows`, `assignments`, `attempts`, `waves`, `checkpoints`, `human_requests`, and `command_runs`
- split second by technical role inside that owner when needed: `service.py`, `writes.py`, `reads.py`, `recording.py`, `projection.py`
- avoid top-level owner buckets such as `control`, `effects`, or `helpers` when one bounded context can hold the same code more coherently

If a reader must hop across `control/`, `effects/`, and `projection/` to follow one lifecycle, the layout is probably too mechanism-first.

## Integration substrate rule

When an external system grows into a substantial boundary:

- keep reusable integration substrate under a dedicated integration owner
- keep runtime or domain behavior that uses that integration under the runtime or domain package that owns the workflow
- keep public packaging or wrapper exposure thin and separate from the runtime substrate

Example steady-state pattern:

```text
integrations/
  openclaw/

runtime/
  dispatch/
    openclaw/
```

Do not scatter the same provider boundary across unrelated runtime, CLI, and wrapper owners without an explicit split.

## Service-layer rule

- keep a `services/**` owner only if it has a precise, consistently applied meaning such as use-case orchestration
- do not keep an empty or generic `services/` bucket as a promise of future cleanliness
- if orchestration naturally belongs to a bounded context package, keep it there instead of inventing a generic service layer

## DB and schema ownership rule

- keep persistence truth under `persistence/**`
- keep shared typed contracts near the domain that owns them, for example `workflows/contracts/**` and `runtime/contracts/**`
- avoid parallel contract-model trees unless their semantic role is explicitly different from API/runtime schemas

If a runtime-specific contract lane exists, it must explain why it is not just another schema tree.

## Console frontend source rule

The final root `console/**` tree owns the browser Console only. The current `apps/console/**` tree is disposable AutoClaw migration evidence, not a source to rename or incrementally turn into the target.

It consumes controller-owned API truth and design handoff truth; it does not define runtime truth, registry truth, node-tool truth, or support-state truth.

Use one app-local package and toolchain:

```text
console/
  package.json
  index.html
  vite.config.ts
  vitest.config.ts
  playwright.config.ts
  src/
    app/
    api/
      generated/
    styles/
    components/
      ui/
      layout/
    features/
      workflows/
      workflow-studio/
      runs/
      run-studio/
      human-requests/
      actions/
      operator/
    mocks/
    lib/
  tests/
```

Rules:

- keep app bootstrap, router, providers, and runtime config under `src/app/**`
- keep generated OpenAPI types under `src/api/generated/**`; do not edit them manually
- keep the API client, SSE client, error handling, and request/query helpers under `src/api/**`
- keep shared design tokens and Tailwind entry CSS under `src/styles/**`
- keep Console CSS custom properties under the `--banksia-*` namespace, then expose reusable Tailwind theme tokens from them
- derive reusable color, typography, spacing, size, radius, border, shadow, and status tokens from the design handoff before building page components
- do not port design-repo static HTML, page-local CSS selectors, or inline prototype JavaScript into `console/**`
- keep reusable primitives under `src/components/ui/**` and layout shells under `src/components/layout/**`
- keep page and flow ownership under feature folders named for product pages, not stale backend nouns or design-process labels
- keep MSW handlers and API-shaped browser fixtures under `src/mocks/**` or `tests/fixtures/**`
- keep `src/lib/**` small and responsibility-named; do not let it become a generic dump for view logic
- route code may compose features, but feature components should not own global router, config, or API-client setup
- generated API types and raw controller payloads may feed mappers, but React components should render view-models and primitive props

Preferred first-page ownership is:

```text
features/
  workflows/
  workflow-studio/
  runs/
  run-studio/
  human-requests/
  actions/
  operator/
```

Avoid steady-state folders such as `flows`, `approvals`, `registry`, or `observability` when the product model is Workflows, Runs, Human Requests, Actions, and Operator.

## Test-tree rule

- steady-state tests should mirror product, feature, or boundary ownership
- phase-numbered trees are transitional only and should converge toward feature-owned lanes over time
- unit, integration, and e2e remain the top-level proof lanes, but the folders beneath them should reflect product concepts rather than redesign chronology

Prefer:

```text
tests/
  unit/
    cli/
    workflows/
    runtime/
    integrations/
  integration/
    api/
    cli/
    db/
    runtime/
    integrations/
  e2e/
    workflows/
    providers/
    operator/
```

Avoid keeping `phase2/`, `phase3/`, `phase4a/`, and similar folders as the long-term primary source of test ownership once the redesign history is no longer the important axis.

For Banksia, this test-tree direction is canonical enough that new structural test-layout work should follow it by default unless a documented migration exception is recorded.

## Banksia steady-state direction

The Banksia source layout target is:

```text
pyproject.toml
src/
  banksia/
    interfaces/
      http/
        router.py
        dependencies.py
        errors.py
        contracts/
        routers/
      cli/
        main.py
        root.py
        commands/
        terminal/
      mcp/
        node/
        operator/
    workflows/
      contracts/
    runtime/
      contracts/
    integrations/
    persistence/
    platform/
    config.py
    paths.py
    main.py
tests/
console/
```

Key implications:

- `src/banksia/` is the canonical backend package
- public edges group under one `interfaces/**` owner instead of several sibling transport trees
- Workflow families group under one `workflows/**` owner instead of generic Definition/compiler/registry siblings
- runtime packages become domain-first
- provider integration substrate becomes explicit
- persistence becomes an explicit storage owner while typed contracts stay with the domains that own them
- tests converge to feature/domain ownership
- the independently authored Console stays at root `console/**`

## Review checklist

- does each top-level source tree have one obvious owner
- is there one canonical shipped backend package
- is there one coherent top-level taxonomy inside that package root
- are transport layers thin
- is the main runtime layout domain-first rather than mechanism-first
- is provider integration substrate separated from runtime usage
- does the test tree reflect product or feature ownership rather than redesign chronology
