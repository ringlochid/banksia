# AutoClaw coding standards

Status: Reference

This file holds the repo-wide measurable engineering rules for touched code. Keep it short. Put long-form examples and cleanup playbooks in [`.agents/standards/`](.agents/standards/README.md).

## Core engineering rules

- prefer explicit domain names over generic helpers
- keep side effects visible and centralized
- keep current truth and target truth separate
- delete stale abstractions instead of carrying them forward as ghosts
- remove dead code, duplicated logic, and unaccessed private helpers in touched owned surfaces unless a phase-bounded exception is recorded
- keep one canonical import package for shipped backend code; compatibility import paths may exist only as temporary migration shims
- group backend concerns under clear owners such as `api/`, `compiler/`, `core/`, `db/`, `registry/`, `runtime/`, `schemas/`, and `services/`
- do not scatter one concern across unrelated modules when a named owner can hold it cleanly
- reserve underscore-prefixed top-level names for module-local implementation only
- when another module imports the helper, promote it to a public shared surface or move it into a named shared module
- record any phase-bounded exception explicitly in review

## Refactor triggers

- any touched function over **80** non-comment, non-blank lines must be extracted or carry an explicit review exception
- any touched file over **600** lines must be reviewed for splitting when responsibilities can separate cleanly
- any touched file over **600** lines should not grow further unless one dominant responsibility remains clear and a review exception records why splitting would reduce clarity or locality
- mixed-responsibility files should be split once the current slice touches the overlapping concerns anyway, even when they are below the size threshold
- any touched compatibility shim, redundant branch, or duplicated logic path must be removed or carry an exact contract reason
- file size is a guardrail, not the primary design rule; dominant responsibility, dependency direction, and top-down navigability matter more than raw line count

## Module layout and naming

- keep one dominant responsibility per module
- prefer domain-first packages over top-level mechanism buckets when one bounded context can own the code coherently
- keep transport surfaces thin: `api/**` and `cli/**` should parse, dispatch, and render, not become the long-term owner of runtime, registry, or integration business logic
- keep provider or platform integration substrate separate from runtime/domain usage when the external boundary is substantial
- decide whether a touched surface is public, shared-internal, or module-local; do not let accidental interfaces leak across modules
- use one canonical term per domain concept; do not keep multiple synonyms for the same runtime or controller concept across touched files
- keep the same term for the same concept and a different term for a different concept
- public names should be understandable out of context; prefer domain nouns over local shorthand
- a file may be large, but it may not be structurally ambiguous
- large files are acceptable only when the owner surface stays coherent, navigable, and easier to understand together than split apart
- when a second responsibility becomes reusable or independently testable, extract it into a sibling module or package named for that responsibility
- when three or more sibling files share the same family stem, stop growing the flat family and extract a responsibility-named package or support module
- in `apps/api/tests/**`, ignore the required `test_` prefix when evaluating family stems
- keep one stable family stem for one concern; do not drift between names such as `dispatch_*`, `task_dispatch_*`, and `runtime_dispatch_*` unless ownership truly differs
- name files and modules for their dominant responsibility, not for migration leftovers, chronology, or vague categorization
- avoid new generic names such as `utils.py`, `helpers.py`, `misc.py`, `common.py`, or `support.py` when the responsibility can be named directly
- avoid steady-state path names with temporary or migration suffixes such as `new`, `old`, `temp`, `final`, or `v2`
- prefer one canonical backend package such as `autoclaw/**` over parallel long-lived source trees with duplicated ownership
- keep top-level shared surfaces explicit: shared helpers, adapters, selectors, and mappers should be public and non-underscored
- keep only explicit public-boundary exceptions flat: real `__init__.py` package surfaces, thin `cli.py` entrypoints, and required `conftest.py` discovery surfaces
- do not keep long-lived compatibility wrappers, import-only shims, or placeholder-only tracked trees as steady-state layout

## Source tree rules

- keep the monorepo root organized by product/app, docs, infra, scripts, and authored inputs rather than by language-specific leftovers
- prefer one backend package root under a packaging-aware source tree; a `src/` layout is the steady-state default when packaging and import-path safety matter
- keep public package wrappers or re-export shims minimal and explicitly temporary
- phase-history folders are acceptable in execution docs, but product and test source trees should converge toward feature/domain ownership in the steady state

Extended guidance: [Repo layout standard](.agents/standards/structure/repo-layout.md) Extended guidance: [Naming standard](.agents/standards/code/naming.md) Extended guidance: [Source layout standard](.agents/standards/structure/source-layout.md)

## Import rules

- keep imports at module top except for narrow type-checking or optional-import cases
- group imports as standard library, third-party, and local package imports
- avoid wildcard imports outside deliberate package export surfaces
- prefer clear package imports over deep relative import chains when readability improves

## Top-level function structure

- keep imports first, then constants, type aliases, and exported contracts
- place public entrypoints and shared helpers before module-local helpers
- order functions from high-level orchestration to lower-level helpers
- keep helper families adjacent to the entrypoint or responsibility block they support
- do not interleave unrelated helper groups

## Side effects and transactions

- keep transaction boundaries in service or domain layers, not routes
- keep orchestration in services, domain modules, or clearly named runtime packages
- keep externally visible side effects behind named functions with narrow call sites
- do not hide network, filesystem, or DB writes inside vague helper stacks

## Python rules

- prefer explicit return types
- prefer explicit typed interfaces and domain models
- prefer `pathlib.Path`
- prefer positive predicate names such as `is_*`, `has_*`, and `should_*` over vague boolean flags
- booleans should read as facts, capabilities, or decisions; prefer `is_*`, `has_*`, `should_*`, and `can_*`
- use verb-led function names and make side effects visible with effect-bearing verbs such as `build_*`, `validate_*`, `read_*`, `list_*`, `create_*`, `persist_*`, `delete_*`, and `reconcile_*`
- keep suffix meanings intentional: use names such as `*Model`, `*Request`, `*Response`, `*State`, `*Snapshot`, `*Result`, and `*Config` only for those actual roles
- avoid weak generic symbol names such as `data`, `info`, `item`, `thing`, `helper`, `manager`, `processor`, `wrapper`, `flag`, and `check` when a domain name exists
- prefer parentheses and formatter-friendly multiline shapes over backslashes or hand-packed wrapping
- comments should explain intent, invariant, or non-obvious contract, not narrate obvious mechanics
- TODO comments must name an owner, issue/phase, or concrete removal condition
- public modules, classes, and functions should carry docstrings when the contract is non-trivial; internal helpers usually should not
- treat `scripts/docs/*` as ordinary Python code with lint and typing gates when touched
- keep externally visible Pydantic models explicit and version-current
- prefer Pydantic `BaseModel` over stdlib `dataclass` for controller-owned schema, compiler, presenter, and readback contracts
- keep SQLAlchemy usage explicit, typed, and in 2.x declarative style

## FastAPI rules

- routes should only do parsing, dependency injection, service calls, response mapping, and HTTP translation
- do not bury runtime, prompt, artifact, compiler, or registry business rules inside routes
- prefer `route -> service -> presenter/schema` separation
- do not introduce vague generic `handler` layers unless canon names a concrete responsibility they own
- use `async def` only when the code actually awaits non-blocking I/O
- use plain `def` for sync libraries that do not support `await`
- do not wrap blocking DB or API code in fake async just to make the signature look modern

Source: [FastAPI async docs](https://fastapi.tiangolo.com/async/)

## Pydantic v2 rules

- prefer `model_config = ConfigDict(...)` over deprecated `class Config`
- use current Pydantic v2 APIs such as `ConfigDict`, `model_validate()`, `model_dump()`, `field_validator`, and `model_validator`
- use `model_validate()` and `model_dump()` instead of v1 parse or dict helpers
- keep aliasing, `populate_by_name`, and `from_attributes` explicit where contracts depend on them
- use `from_attributes=True` explicitly on ORM-backed read models instead of relying on implicit behavior
- when translating one typed object surface into another Pydantic contract, prefer `model_validate(..., from_attributes=True)` over wide field-by-field constructor calls when the source can be expressed as attributes cleanly
- use `frozen=True` on immutable contract models when callers should not mutate validated objects
- keep write models strict with `extra="forbid"` unless canon intentionally defines an open payload
- keep read models and audit/readback models explicit about where `extra="allow"` is intentional

Source: [Pydantic configuration](https://docs.pydantic.dev/latest/concepts/config/)

## SQLAlchemy rules

- use relationships, mapped columns, constraints, and explicit indexes when they encode contract or performance truth
- use enum-backed storage when kind/state/type semantics are real contract concepts
- use trigram, vector, or other dialect-specific search features only behind explicit compatibility-aware boundaries when the slice truly needs them
- use `DeclarativeBase`, `Mapped[...]`, and `mapped_column()` as the standard declarative mapping style
- apply the relationship-modernization rules below to new or touched mapped edges and the query paths that primarily traverse them; do not churn untouched legacy mappings only for style alignment
- on new or touched mapped relationships, declare the `relationship()` attribute with an explicit `Mapped[...]` type on each side that the owned slice maintains
- keep table-level `Index`, `UniqueConstraint`, and `CheckConstraint` explicit and named when they encode contract or migration truth
- on new or touched relationships, prefer explicit paired `relationship(..., back_populates=...)` attributes over new `backref`
- when a relationship has multiple foreign key paths or self-reference ambiguity, set `foreign_keys=` or `remote_side=` explicitly
- when a mapped relationship already exists on a touched path, prefer relationship-based navigation and relationship-aware joins/loaders over hand-stitched foreign-key logic unless the query is intentionally aggregate-shaped
- persist canonical controller relationships as real relational links with DB-enforced integrity rather than parallel string or JSON echoes
- prefer dialect-portable types and constraint patterns on shared SQLite/Postgres runtime paths
- prefer portable enum storage for shared cross-DB surfaces, for example `Enum(..., native_enum=False, create_constraint=True)`, unless canon explicitly freezes a Postgres-only enum strategy
- avoid Postgres-only column types or operators such as `JSONB`, `ARRAY`, or dialect-specific index/operator behavior on shared runtime paths unless canon explicitly requires them and review records the reason
- when a dialect-specific DB feature is unavoidable, isolate it behind a narrow persistence boundary and keep both SQLite smoke and Postgres strong-verification lanes explicit in tests and review evidence
- use child tables instead of JSON columns for authoritative relational runtime truth
- reserve JSON columns for secondary structured snapshots, authored bodies, debug material, or projections whose source of truth is explicit elsewhere
- choose relationship loading strategy deliberately and avoid N+1 by default
- use `selectinload()` by default for collection loading unless joined loading is clearly better for the query shape
- use `joinedload()` only when row explosion is understood and acceptable
- use `raiseload()` or equivalent guardrails where accidental lazy loads would hide correctness or performance problems
- do not hide business rules inside giant ad-hoc query blocks
- do not read canonical definition, registry, or runtime authority from repo files once that authority is assigned to controller-owned DB truth

Source: [SQLAlchemy declarative mapping](https://docs.sqlalchemy.org/en/20/orm/declarative_styles.html) Source: [SQLAlchemy basic relationships](https://docs.sqlalchemy.org/en/20/orm/basic_relationships.html) Source: [SQLAlchemy backref guidance](https://docs.sqlalchemy.org/en/20/orm/backref.html) Source: [SQLAlchemy join conditions](https://docs.sqlalchemy.org/en/20/orm/join_conditions.html) Source: [SQLAlchemy relationship loading](https://docs.sqlalchemy.org/en/21/orm/queryguide/relationships.html)

## TypeScript, React, and plugin rules

- keep typed TS surfaces explicit and `strict`-clean
- avoid implicit-any drift, broad `unknown` plumbing, and vague glue modules
- keep React and plugin modules cohesive and low-responsibility
- keep build and test behavior aligned with repo-native scripts
- use `PascalCase` for React components and exported type-like names
- use `camelCase` for variables, local functions, mappers, hooks, and non-component helpers
- use `UPPER_CASE` only for true immutable module constants
- use `use*` names for custom hooks and keep hook files feature-local by default
- use `*Props`, `*ContextValue`, `*State`, and `*Action` suffixes only for those actual frontend roles
- do not prefix TypeScript interfaces with `I`, and do not use `VM` when a readable render noun such as `Row`, `Item`, `Summary`, or `View` fits
- component files should use `PascalCase.tsx` when they primarily export one component; non-component frontend modules should use responsibility-named lower kebab-case
- event callback props should be named `on*`; local event handlers should be named `handle*`
- use generated OpenAPI types for controller-backed API payloads; do not hand-maintain duplicate TypeScript API contracts
- keep one narrow API/SSE client layer for base URL resolution, request headers, error envelopes, query construction, SSE cursor handling, backfill, and reset behavior
- V2 loopback console and control clients do not add a global operator API key or browser credential bootstrap; follow the owning V2 security contract for local admission
- render frontend view-models such as task rows, event items, human-request items, command-run rows, and definition summaries instead of passing raw controller payloads directly through component trees
- translate generated snake_case controller fields into camelCase view-model fields only inside explicit mappers
- keep controller vocabulary exact for route names, states, event families, command-run states, human-request kinds, and definition kinds
- keep UI-only labels and grouping out of API contracts, generated types, persistence models, and runtime docs
- use React Router or equivalent route ownership for multi-page console flows instead of large boolean or enum page switches
- keep page components as route orchestration; extract rows, forms, drawers, tabs, toolbars, log blocks, and disclosure bodies once they own behavior or repeat
- avoid duplicated or contradictory React state; derive render facts from props, route params, API data, and existing state when practical
- prefer `useReducer` over scattered `useState` when transitions are event-shaped, multi-field, or easy to contradict
- use effects only for external synchronization, subscriptions, focus management, and imperative browser APIs; do not mirror props into local state by default
- use `memo`, `useMemo`, and `useCallback` only for measured churn, expensive calculations, or identity-sensitive APIs
- keep shared visual language in tokens and reusable primitives; avoid page-local Tailwind utility sprawl once a pattern repeats
- use design tokens for colors, spacing, radius, shadow, typography, and status treatments instead of ad hoc utility values for controller surfaces
- console CSS custom properties use the `--ac-*` namespace; do not carry prototype-only token prefixes such as `--oc-*` into implementation
- derive reusable style tokens from the design handoff once, including color, typography, spacing, size, radius, border, shadow, and status treatments
- do not copy design-repo static HTML, page-local CSS selectors, or inline prototype JavaScript into the console app
- map state and variants to explicit Tailwind class strings; do not build dynamic classes such as `` `bg-${status}` ``
- extract repeated Tailwind utility clusters into primitives, variant helpers, or token-backed CSS rather than copying the cluster across features
- keep accessibility part of the component contract: semantic elements, labels, keyboard focus, color-with-text state, and stable responsive order
- do not invent frontend-only lifecycle states, fake metrics, progress percentages, ETA, run/request counts, or support-file-derived truth when the controller does not expose them
- keep browser-only template generation, diff, and local form state visibly separate from stored registry truth, flat draft truth, runtime truth, and task-start launch truth

Source: [React custom hooks](https://legacy.reactjs.org/docs/hooks-custom.html) Source: [React state structure](https://react.dev/learn/choosing-the-state-structure) Source: [TypeScript ESLint naming convention](https://typescript-eslint.io/rules/naming-convention/) Source: [Tailwind reusing styles](https://tailwindcss.com/docs/reusing-styles)

## Docs structure rule

- separate public product/operator docs, public reference/internals docs, and internal canon docs
- prefer `design/` over `redesign/` in steady-state internal naming
- keep internal canon under `docs-internal/**` in the steady state
- version internal canon explicitly with directories such as `v1/`, `v2/`, and `vnext/`
- keep public docs versionless by default unless multiple supported public product versions must coexist
- do not recreate deleted execution or archive trees just to satisfy stale references
- keep stable implementation-heavy reference in a dedicated internals or maintainer lane, not in onboarding or general concept pages
- keep design truth and current contrast in internal canon paths, and record durable accepted decisions under `docs-internal/adr/**`

Extended guidance: [Docs structure guide](.agents/standards/docs/docs-structure.md)

## Standards router

Use these long-form guides when the measurable rules above are not enough to make the code, layout, docs, tests, or boundaries obviously right:

- [Standards tree index](.agents/standards/README.md) — entry router and precedence for the long-form standards tree. Go here first when you need help choosing the right deeper guide.
- [Standards writing guide](.agents/standards/standards-writing.md) — structure, naming, and maintenance rules for `AGENTS.md`, `STYLE.md`, and `.agents/standards/**`. Go here when changing the standards stack itself.
- [Readability and refactor standard](.agents/standards/code/readability-refactor.md) — extraction, control-flow shaping, whitespace phases, helper boundaries, and readability cleanup. Go here when the change is more than a formatter pass.
- [Naming standard](.agents/standards/code/naming.md) — naming rules for symbols, files, packages, routes, CLI nouns, and schemas. Go here when naming drift or rename scope matters.
- [Repo layout standard](.agents/standards/structure/repo-layout.md) — repo tree, package splits, module-family cleanup, and ownership-by-path. Go here when moving files or cleaning structural sprawl.
- [Source layout standard](.agents/standards/structure/source-layout.md) — canonical backend package direction, transport-layer thinness, and long-term source-tree convergence. Go here when deciding package roots or steady-state source layout.
- [Test structure standard](.agents/standards/structure/test-structure.md) — proof-lane ownership and test placement. Go here when deciding unit versus integration versus e2e evidence or reorganizing test trees.
- [Integration boundaries standard](.agents/standards/structure/integration-boundaries.md) — seam ownership across API, services, runtime, registry, DB, CLI, OpenClaw, and support-state surfaces. Go here when logic placement across layers is ambiguous.
- [Docs structure guide](.agents/standards/docs/docs-structure.md) — public/internal docs placement, page types, versioning, and docs information architecture. Go here when docs scope or location is the real issue.

## Review exception rule

If a touched surface cannot meet these standards inside the current phase:

- record the exact exception
- explain why it is phase-bounded
- name the owning later phase or work package
- do not leave the deviation as an unexplained convenience shortcut
