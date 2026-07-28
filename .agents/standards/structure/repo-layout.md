# Repo layout standard

Status: Reference

Use this guide when the work includes moving files, splitting packages, renaming families, or cleaning flat tree sprawl.

## Goals

- keep one dominant responsibility per directory and module family
- make ownership obvious from the path alone
- keep long-lived shared surfaces named and intentional
- stop repeating prefix families once a named package can own the concern cleanly
- keep public docs, public reference docs, and internal canon docs distinct in both naming and layout
- keep transport surfaces thin and domain owners explicit
- optimize for coherence, locality, and obvious dependency direction before raw file-count neatness

## Root map

- `src/banksia/**`: the one canonical Banksia backend package
- `tests/**`: backend proof organized by unit, integration, and end-to-end ownership
- `console/**`: the Banksia browser Console
- `src/banksia/workflows/resources/starter_workflows/**`: provider-neutral bootstrap inputs, not runtime authority
- `docs/**`: public product, operator, reference, and help docs
- `docs-internal/architecture/**`: runtime and product architecture
- `docs-internal/interfaces/**`: controller, Console, Operator, and tool contracts
- `docs-internal/operations/**`: configuration, recovery, packaging, and reset behavior
- `docs-internal/adr/**`: durable accepted decisions
- `scripts/docs/**`: docs and prompt tooling
- `scripts/testing/**`: test runners and support scripts
- `.agents/standards/**`: agent-only long-form standards

## Structure principle

File size is a guardrail, not the architecture.

A file may be large, but it may not be structurally ambiguous.

Prefer keeping code together when:

- the file has one dominant responsibility
- related logic changes together
- top-down reading still works
- the dependency direction is obvious
- splitting would create fake abstraction, import churn, or cross-file ping-pong

Prefer splitting when:

- the file mixes responsibilities that can be named separately
- helper families serve different owners
- readers must jump around to recover the main flow
- side-effect boundaries are buried
- the current slice already touches multiple unrelated concern groups

## Package extraction rules

- if three or more sibling files share the same family stem, extract a package or support module named for the real responsibility
- if one file mixes unrelated concerns and the current slice touches both, split it now instead of adding more branches
- if a shared helper is imported across modules, move it into a named shared module instead of importing another module's local implementation
- if a path already names the responsibility cleanly, prefer extending that owner over adding a parallel directory
- prefer bounded-context or product-owner packages before top-level implementation-mechanic packages when one owner can hold the concept cleanly
- do not split a coherent file just to satisfy a metric if the new boundary would reduce locality or create a weaker owner surface

## Naming rules

- prefer names that expose the domain concern directly
- use one stable family stem for one concern; do not drift between near-duplicate stems unless ownership truly differs
- file names should describe the dominant responsibility, not chronology, migration status, or implementation leftovers
- package names should represent ownership, not generic categorization buckets
- avoid placeholder names such as `utils`, `helpers`, `misc`, `common`, `support`, or `wrapper` unless the directory truly owns that narrow concern
- avoid version suffixes or temporary migration names in steady-state code paths
- keep Banksia canon versionless and do not add version-suffixed owner files
- keep public shared helpers non-underscored
- keep test filenames aligned with the feature or contract they verify, not with incidental helper names

Extended guidance: [Naming](../code/naming.md)

## Backend layout guidance

- keep one coherent taxonomy under `src/banksia/**` and do not open a parallel `banksia_v2` tree
- prefer public interfaces under `src/banksia/interfaces/**`
- keep HTTP surfaces under `src/banksia/interfaces/http/**`
- keep HTTP-only support contracts, presenters, and transport models under `src/banksia/interfaces/http/contracts/**`
- keep noun-owned HTTP route modules under `src/banksia/interfaces/http/routers/**`
- keep CLI entrypoints and noun-family orchestration under `src/banksia/interfaces/cli/**`
- keep MCP or similar server-facing entrypoints under `src/banksia/interfaces/mcp/**`
- keep interface packages thin; parsing, dependency wiring, dispatch, and rendering belong there, not long-lived runtime or registry business logic
- keep authored-definition families grouped under `src/banksia/definitions/**`
- keep definition-owned contracts under `src/banksia/definitions/contracts/**`
- keep persistence and ORM models under `src/banksia/persistence/**`
- keep runtime-owned contracts under `src/banksia/runtime/contracts/**`
- keep runtime orchestration under `src/banksia/runtime/**`
- keep platform-owned setup and environment code under `src/banksia/platform/**`
- when provider integration becomes substantial, keep reusable substrate under `src/banksia/integrations/**` and keep runtime usage under the owning runtime family

## Frontend layout guidance

- keep package manager, Vite, TypeScript, ESLint, Prettier, Vitest, Playwright, and Tailwind config app-local unless a second JS app later proves a shared workspace is needed
- keep generated OpenAPI output under `console/src/api/generated/**` and treat it as generated contract input, not authored source
- keep API wiring under `console/src/api/**` and keep feature components behind view-model mappers instead of direct raw-payload rendering
- keep reusable primitives under `console/src/components/ui/**` and layout shells under `console/src/components/layout/**`
- keep product-owned feature folders under `console/src/features/**`; prefer `workflows`, `workflow-studio`, and `runs`
- avoid stale feature folders such as `approvals`, `flows`, `registry`, or `observability` unless a later controller-backed page contract reintroduces that exact user-facing owner
- keep test fixtures and MSW data API-shaped and visibly fake; do not let browser fixtures become shadow controller truth

## Test layout guidance

- keep unit, integration, and e2e surfaces separate
- do not let helper-heavy test families hide what lane they belong to
- if an integration or e2e family grows into several concerns, extract subpackages by responsibility rather than by repeated filename prefixes
- phase-numbered test trees are transitional only; steady-state test layout should converge toward feature, boundary, or product ownership

## Docs layout guidance

- do not place product truth in `.agents/standards/**`
- do not place execution evidence in public docs or shipped-behavior contrast pages
- do not use archive pages as living source of truth
- keep public docs under `docs/**`
- keep internal canon under `docs-internal/**`
- keep internal owners in the architecture, interfaces, operations, or ADR lane named by their responsibility
- keep Banksia owner paths versionless
- do not use the public docs tree as a catch-all for versioned implementation programs, historical design drafts, or execution artifacts

## Local instruction files

If local guidance becomes necessary later, the first candidates should be:

- an `AGENTS.md` near the backend package root
- an `AGENTS.md` near the backend tests root
- an `AGENTS.md` under the public docs tree
- an `AGENTS.md` under the internal canon tree

Add them only when a subtree genuinely needs different local routing or validator rules.

Extended guidance: [Source Layout](./source-layout.md)
