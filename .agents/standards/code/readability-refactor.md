# Readability and refactor standard

Status: Reference

Use this guide when a touched slice is drifting into structural cleanup, large-function repair, compatibility-shim deletion, naming cleanup, or layout/readability work that a formatter alone will not solve.

## Purpose

Every touched slice should leave the code easier to read than it was before the edit.

Readability in this repo means:

- a reviewer can follow the main control flow top-down
- ownership is obvious from names and paths
- side effects are easy to see
- the happy path is not buried in nesting
- related lines stay visually close
- phase boundaries are visible without whitespace noise
- coherence and locality survive the refactor rather than being traded away for arbitrary file-count neatness

## Precedence and baseline

- `STYLE.md` owns the measurable triggers and repo-wide minimum rules
- this file explains how to apply those rules in real refactor work
- Ruff formatting is the mechanical baseline for touched Python code
- PEP 8, PEP 257, Black-style formatter discipline, and mainstream Python readability guidance are the baseline influences; repo-specific rules here win when more specific

Do not fight the formatter over local aesthetics. If formatter output is hard to read, refactor the code shape instead of trying to hand-style around it.

## Formatting versus refactoring

Use the formatter for:

- indentation
- quotes
- import layout
- line wrapping
- trailing commas where the formatter wants them
- basic whitespace normalization

Use refactoring for:

- large functions
- unclear phase boundaries
- nested control-flow pyramids
- vague naming
- duplicated payload assembly
- mixed responsibilities
- generic helper sprawl
- module layout and ownership cleanup

A formatter can make code uniform. It cannot decide where the code should be split, what a helper should be called, or which branch owns a side effect.

## Import and interface rules

- keep imports at module top except for narrow type-checking or optional-import cases
- separate standard-library, third-party, and local package imports
- avoid wildcard imports except on deliberate package export surfaces
- prefer clear package imports over deep relative-import ladders when the package path reads more clearly
- decide whether a touched surface is public, shared-internal, or module-local before renaming, extracting, or moving it
- if another module imports the helper, it is not module-local anymore: promote it or move it into a named shared owner

## Rewrite versus patch

Prefer a rewrite-shaped change when:

- the current structure hides the target contract
- stale compatibility logic is forcing parallel truth paths
- the function or file crosses the `STYLE.md` thresholds and the excess is structural rather than temporary
- the same ambiguity would recur if you only patched one more branch
- the current slice already touches enough of the surface that leaving the structure alone would preserve obvious debt

Prefer a bounded patch when:

- the phase owns a narrow contract repair and the surrounding structure is still phase-appropriate
- a wider rewrite would cross owned-surface boundaries without approval
- the cleanup can be deferred cleanly and recorded as an exact later-phase exception
- the touched branch is genuinely isolated and the broader surface would not become materially clearer from a rewrite now

## Structure principle

Coherence matters more than raw size.

A file may be large, but it should still be readable as one owner surface. Large-file cleanup should optimize for:

- one dominant responsibility
- clear dependency direction
- top-down navigability
- locality for code that changes together
- explicit side-effect boundaries

When a repo or package split is under review, choose the boundary that keeps one domain flow readable together before choosing a boundary that merely groups the same code by implementation mechanism.

Do not split a coherent file merely to satisfy a metric if the split would make ownership less obvious or force readers to bounce across files to recover one conceptual flow.

## Top-down reading rule

Code should read from the outside in and from top to bottom.

At module level, prefer this order:

1. imports
2. constants, type aliases, exported contracts
3. public entrypoints
4. shared public helpers
5. module-local helpers

At function level, prefer this order:

1. normalize or unpack inputs
2. guard clauses and preconditions
3. derive local state
4. perform the core action
5. run post-action validation or reconciliation
6. build output payload or render result
7. return

If the natural reading order differs, that should be because the contract truly needs it, not because the file accreted over time.

## Vertical whitespace rules

### Module level

- keep **two blank lines** between top-level classes and functions in Python
- keep **one blank line** between methods inside a class unless a formatter or docstring rule requires otherwise
- keep small related constants or aliases vertically close; do not scatter them with decorative spacing

### Inside functions

Use **one blank line** to separate major phases.

Good uses:

- after guard clauses, before the main flow
- between input normalization and derived-state preparation
- between pure computation and side effects
- between the core action and output construction
- between conceptually separate assertion groups in tests

Do not add blank lines:

- after every nested `if`, `try`, `with`, or `for` block
- inside tiny one-concern branches
- between lines that are part of one uninterrupted thought
- just to make the function look longer or more dramatic

The goal is phase separation, not visual decoration.

## Multiline formatting rules

- prefer parentheses over backslashes
- accept the formatter's wrapping and closing-bracket shape instead of freezing bespoke local formatting
- use one obvious multiline shape per expression or call
- if a multiline call, literal, or comprehension is still hard to scan after formatting, extract names or payload builders rather than hand-packing the layout

## In-function layout rules

Inside a non-trivial function, prefer this rhythm:

1. input unpacking or normalization
2. guard clauses
3. derived local names
4. side-effect-free preparation
5. side effects
6. result shaping
7. return

Rules:

- keep the happy path as flat as possible
- prefer early returns over wrapping the main flow in a large `else`
- keep exceptional paths narrow
- keep output assembly near the return, unless it is large enough to deserve a helper
- when a local variable exists only to explain one branch, keep it inside that branch

## Function extraction rules

- extract by responsibility, not by arbitrary line-count chopping
- prefer a few named helpers over one deeply nested orchestration block
- do not create helper soup where the reader must jump constantly to recover the main flow
- when extracting, place the new surface near the code that owns the concern
- keep public/shared helpers above module-local helpers
- if the extracted code has no meaningful name, you probably have not found the right seam yet

Extract a helper when it:

- performs one coherent sub-step
- would otherwise force heavy inline nesting
- has a name that improves the readability of the caller
- isolates payload assembly, validation, normalization, or a side-effect boundary

Do not extract just to:

- satisfy a length threshold mechanically
- hide a confusing branch without naming the actual concern
- move unrelated state through a long helper parameter list

When a large file keeps spilling into helper groups that belong to different bounded contexts, prefer a package or module split by domain owner rather than creating a new generic mechanical bucket.

## Naming rules

Names carry most of readability.

Prefer names that expose:

- the domain concept
- whether the value is raw, normalized, selected, resolved, or persisted
- whether a function validates, builds, maps, reads, writes, launches, or reconciles
- whether a boolean is a fact, permission, or decision
- whether a type is a request, response, state, snapshot, result, or persisted model

Apply these repo-wide naming rules:

- use one canonical term per domain concept; do not keep competing synonyms alive in the same touched slice
- public names should be descriptive out of context; local shorthand should stay local
- use verb-led function names and make side effects visible with the verb choice
- keep boolean names fact-shaped with `is_*`, `has_*`, `should_*`, or `can_*`
- avoid weak generic heads and tails such as `data`, `info`, `helper`, `manager`, `processor`, `wrapper`, `flag`, and `check`

Good patterns:

- `selected_phase`
- `resolved_revision`
- `build_runtime_record()`
- `validate_dispatch_payload()`
- `persist_attempt_transition()`
- `should_force_reset`
- `is_worker_ready`
- `has_pending_children`

Avoid names such as:

- `data`
- `item`
- `obj`
- `thing`
- `helper`
- `handle`
- `process`
- `flag`
- `check`
- `done`
- `do_stuff`
- `misc`

Avoid names that hide side effects. If a function writes to the DB, filesystem, network, or controller state, the name should make that unsurprising.

Extended guidance: [Naming](./naming.md)

## Conditional and control-flow rules

- prefer early returns to reduce indentation
- flatten condition pyramids when the branches can be named or split cleanly
- isolate `try/except` to the smallest block that can actually fail
- do not let a single function alternate repeatedly between normalization, branching, DB writes, and rendering
- when branches differ by responsibility, extract them instead of stacking `elif` towers forever

When a condition is hard to read:

- give the predicate a meaningful name, or
- extract the branch into a helper with a domain name

Do not introduce named intermediates that merely restate obvious syntax without adding meaning.

## Error-handling and side-effect shaping

- keep `try` blocks narrow and wrap only the statements that can actually fail
- avoid broad catch-all branches that log and continue unless the fallback is an explicit contract
- prepare payloads and derived state before writes when that makes the side effect boundary easier to see
- do not interleave large payload assembly with repeated writes unless the interleave is the real behavior under test or review

## Call-site readability rules

- keep calls boring
- move complex decisions above the call site
- use named intermediate variables when they reveal meaning, not when they simply duplicate an expression
- do not inline giant dicts, tuples, or nested constructors into important calls unless the literal is static and obvious

If a call becomes unreadable, first try:

1. naming the inputs
2. extracting payload assembly
3. extracting branch-specific preparation

Only after that should you accept a visually heavy call shape.

## Frontend readability rules

Frontend code should preserve the same top-down reading shape as backend code: route ownership, data loading, view-model mapping, component rendering, and primitive styling should stay distinct.

Component files should read in this order when practical:

1. type imports and runtime imports
2. local constants and small helper types
3. exported component
4. small local subcomponents when they are not reusable
5. local pure helpers

Rules:

- keep page and route components as orchestration surfaces; extract rows, forms, drawers, tabs, log blocks, and disclosure bodies when they own their own behavior
- keep reusable primitives in `components/ui/**` and layout shells in `components/layout/**`; do not hide product-specific behavior inside generic primitives
- prefer feature-local helpers before global `lib/**`; promote a helper only after at least two owners use the same responsibility
- keep raw controller payload handling inside API helpers, generated-type adapters, or view-model mappers
- React components should receive view-models, primitive props, and event callbacks, not generated OpenAPI payloads directly
- keep server state, selected IDs, local form drafts, modal state, and derived render facts visibly separate
- do not duplicate derived state; if a fact can be calculated from props, route params, API data, or existing state during render, derive it instead of storing it
- when multiple state fields always change together, use one state object or a reducer instead of several loosely coordinated `useState` calls
- use `useReducer` when UI transitions become event-shaped, multi-field, or easy to contradict
- use React context only when sibling branches genuinely share state; do not create context just to avoid passing one or two local props
- use effects for external synchronization, subscriptions, focus management, or imperative browser APIs; do not use effects to mirror props into state when rendering can derive the value
- use `memo`, `useMemo`, and `useCallback` only when they protect a real expensive calculation, stabilize an API that needs identity, or solve measured render churn; blanket memoization makes code harder to read

## Tailwind readability rules

Tailwind utility classes are acceptable at the component boundary, but repeated or conditional class strings should not become the real component model.

Rules:

- prefer design tokens and named primitives over ad hoc color, radius, shadow, and spacing choices
- use the implementation token namespace `--ac-*` for console CSS variables, not prototype prefixes from the design repo
- translate design-repo shared CSS into semantic token families and primitives before building pages
- when the same utility cluster repeats across product features, extract a primitive, layout component, variant helper, or token-backed CSS class
- keep class strings stable and scan-friendly; if a `className` needs complex branching, compute the named branch above the JSX
- keep responsive, state, and dark/light variants near the element they affect; do not hide important interaction styling in distant helper magic
- avoid dynamic Tailwind class construction such as `` `bg-${status}` ``; map status or variant names to explicit class strings instead
- keep `@apply` rare and token-backed; prefer React primitives for reusable UI structure
- do not use raw arbitrary values for core UI structure unless the design handoff requires the exact value and a token would be misleading
- if a Tailwind string is long but belongs to one obvious primitive, keep it with that primitive instead of splitting by visual mechanics

## Accessibility readability rules

- choose semantic HTML before ARIA
- keep labels, descriptions, `aria-*` relationships, and keyboard behavior near the component they describe
- stateful controls must expose text or accessible names that match the user-visible action
- color-only state is not enough; pair state color with text, icon semantics, or a visible label
- interactive components should make focus order and disabled/loading states obvious in the JSX

## Comments and docstrings

- comment the intent, invariant, or non-obvious contract
- do not comment what the code already says clearly
- keep comments short and local to the code they explain
- keep inline comments rare; if one survives, it should justify itself
- TODO comments must include an owner, issue, owning slice, or concrete removal condition
- public modules, public functions, and public classes should follow normal docstring expectations
- use docstrings for interface or contract explanation, not for line-by-line narration

When a comment is doing the job of a better name or cleaner extraction, prefer the refactor.

If a TODO cannot say who owns it or what removes it, it is backlog noise rather than a useful code marker.

## Test readability rules

- prefer one behavioral scenario per test
- structure tests so arrange, act, and assert phases are easy to spot
- use one blank line between those major phases when the test is non-trivial
- keep fixture and helper setup explicit enough that the reader can tell what state is real and what is synthetic
- name tests by the behavior under proof, not by incidental helper mechanics

Do not hide the real assertion target behind long helper stacks.

## Compatibility and migration discipline

- do not keep long-lived import-only shims as steady-state layout
- do not carry both old and new truth paths once the owning phase has reopened the surface
- if a temporary compatibility path is unavoidable, document the exact owner and removal point in review
- do not preserve vague wrapper layers just because several callers already route through them

## Refactor workflow

When the slice includes readability cleanup:

1. identify whether the work is format-only, structure-only, or behavior plus structure
2. stabilize the target contract first
3. remove dead or duplicate paths before extracting helpers around them
4. run the formatter after the structure is clear
5. verify that names, ordering, and blank-line phases now read naturally

If the diff is getting too mixed, split the cleanup so the review can still tell which part changed behavior and which part clarified structure.

## Touched-surface checklist

- remove dead code and unreachable branches
- remove duplicate logic and duplicated normalization paths
- delete compatibility shims that no longer protect a real public surface
- move shared helpers out of module-local underscore-private names
- keep top-down control flow readable without deep helper hopping
- rename vague helpers and data structures to domain names
- split mixed-responsibility modules when the current slice already touches both concerns
- keep comments for non-obvious intent, not for restating the code
- collapse naming drift so one concept keeps one canonical term across touched code, tests, and docs
- for frontend work, keep API client, view-model, component, Tailwind token, and interaction-state responsibilities visible rather than folding them into one page component

## Review checklist

Before claiming the refactor clean:

- check the touched functions against the line-count thresholds
- check that blank lines separate phases rather than decorating nesting
- search for retained duplicate helpers or underscore-private shared imports
- check for synonym drift, vague suffixes, and side-effecting functions whose names still sound pure
- verify the rename or extraction did not silently widen ownership into another phase
- confirm that side-effect boundaries are still obvious from the top-level flow
- record any retained exception with the exact contract reason
