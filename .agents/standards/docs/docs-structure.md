# Docs structure standard

Status: Reference

Use this guide when adding, moving, splitting, versioning, or redesigning docs pages.

## Core model

AutoClaw docs should separate **audience**, **task**, **page type**, and **version**.

Do not treat the docs tree as a direct mirror of the code tree, the execution program, or the implementation timeline.

Use three layers:

1. **Public product and operator docs**
   - for onboarding, workflows, concepts, operations, troubleshooting, and user-visible behavior
2. **Public reference and internals docs**
   - for exact CLI, schema, API, contract, maintainer, and stable implementation reference
3. **Internal canon docs**
   - for design truth, shipped-behavior contrast, migration notes, ADRs, and version-era implementation contracts

## Public versus internal versioning

Version public docs only when AutoClaw intentionally supports multiple public product versions in parallel.

Default rule for public docs:

- keep public docs versionless by default
- do not add `v1`, `v2`, or `vnext` folders under public docs just because the internal design changed
- only add public version selectors or versioned public folders when multiple supported public releases must coexist for readers

Default rule for internal canon:

- version internal docs explicitly by directory
- prefer `v1/`, `v2/`, and `vnext/`
- use directory-level versioning, not filename suffixes such as `runtime-v2-final.md`
- freeze one internal version when it becomes historical and move active future design into `vnext/`

## Current layout rule

The current layout is:

- public docs under `docs/**`
- V2 target design truth under `docs-internal/design/v2/**`
- V1 target baseline under `docs-internal/design/v1/**` for surfaces V2 has not superseded
- shipped-behavior contrast under `docs-internal/current/v1/**`
- durable accepted decisions under `docs-internal/adr/**`

Treat that as the live information architecture.

Do not recreate deleted execution or archive trees just to satisfy stale references.

## Authority metadata rule

Use `Status:` lines only where authority metadata helps maintainers distinguish internal truth surfaces.

Do not expose `Status:` or `Last verified:` headers in public reader-facing docs under `README.md` or `docs/**`. Those headers are internal context, not useful product documentation. Public pages should open with the product claim, task, or answer.

Allowed live status values for canon docs are:

- `Status: Target` Use for live design owner pages and design appendix owners under `docs-internal/design/**`.
- `Status: Current` Use for shipped-behavior contrast pages under `docs-internal/current/**`.
- `Status: Reference` Use for standards, ADR front doors, internal routers, and any secondary internal search page that is not the live owner of target or current truth.
- `Status: Template` Use only for reusable templates.
- `Status: Accepted` Use only for individual ADR decision records under `docs-internal/adr/**`.

Rules:

- avoid custom status labels such as `Owner index` or `Current appendix`; put that role in the title or opening paragraph instead
- keep `README.md` as the canonical live front door for a subtree when a live front door is needed
- if an `INDEX.md` is retained for search or legacy-entry compatibility, it must stay secondary, point back to `README.md`, and use `Status: Reference`

## Retired execution-program wording rule

Execution-program wording should not leak into reader-facing or owner-truth pages.

Rules:

- remove stale execution-program terms such as phase selectors, execution-owner page labels, delivery-scope labels, reopen-flow language, and canon-repair language from live docs
- route target truth to design owner pages, shipped-behavior contrast to current pages, and durable rationale to ADRs
- do not recreate deleted execution or archive trees as a hiding place for stale control language

## Target public docs methodology

The long-term public docs structure should follow reader intent first. Recommended top-level public lanes are:

- `docs/start/**`
- `docs/concepts/**`
- `docs/operator/**`
- `docs/runtime/**`
- `docs/openclaw/**`
- `docs/authoring/**`
- `docs/reference/**`
- `docs/help/**`

Stable implementation-heavy public material should live under dedicated reference lanes such as:

- `docs/reference/internals/**`
- `docs/reference/maintainers/**`

The exact folder names can change during the redesign, but the three-layer model must stay intact.

## Target internal canon methodology

Internal canon should be explicit about version era.

Recommended internal top-level structure:

- `docs-internal/design/v1/**`
- `docs-internal/design/v2/**`
- `docs-internal/design/vnext/**`
- `docs-internal/current/v1/**`
- `docs-internal/current/v2/**`
- `docs-internal/current/vnext/**` only when current shipped contrast genuinely exists for a next-era branch or long-lived prerelease line
- `docs-internal/adr/**`

Rules:

- `design/` replaces `redesign/` as the steady-state name
- `current/` remains contrast, not target truth
- `adr/` is for durable accepted decisions, not speculative plans or raw design notes

## Placement rules

### Put a page in public product or operator docs when:

- a reader needs it to install, onboard, author, operate, troubleshoot, or use AutoClaw safely
- the page teaches a workflow, concept, responsibility boundary, or operational behavior
- the behavior is part of the supported product surface
- the page can stand on supported behavior without page-local internal review evidence headings such as `## Evidence` or `## Verification`

Examples:

- install and first-run flows
- onboarding and local setup
- workflow and task-compose authoring
- operator workflows and observability entry points
- runtime mental models and user-facing lifecycle explanations
- troubleshooting and migrations readers must perform

### Put a page in public reference or internals when:

- the page is stable lookup material
- the audience is contributor, integrator, operator, or maintainer
- the material is implementation-aware but still useful as durable reference
- the detail is too mechanical or exhaustive for a guide or topic page

Examples:

- exact CLI flag and output contracts
- schema and payload reference
- operator surface reference
- runtime record or dispatch contract reference
- stable load pipeline or adapter internals
- maintainer templates and release/reference material

### Put a page in internal canon docs when:

- the page exists to drive implementation, migration, design landing, or execution control
- the page compares current and target behavior
- the page records target design, current contrast, migration rationale, or a durable accepted decision
- the page is temporary or version-era-specific implementation-control truth rather than stable product/reference truth

Examples:

- design architecture truth
- current-behavior contrast pages
- migration-only decision records
- version-era specific implementation specs

## Implementation-detail rule

Implementation details are allowed in docs, but they must be placed by **stability** and **audience**.

- if the detail explains a stable public boundary, put it in a public architecture or topic page
- if the detail is deep but stable contributor reference, put it in `reference/internals` or an equivalent public internals lane
- if the detail is design-only, migration-only, version-era-only, or execution-only, keep it in internal canon docs

Do not dump active implementation-program material into public onboarding, concept, or troubleshooting pages.

## Current closeout heading rule

`docs-internal/current/**` pages should make their shipped-proof closeout obvious with exact headings.

Rules:

- for non-front-door current pages, use either exact `## Evidence` or exact `## Verification`
- reserve `## Verification` for pages whose primary closeout is a runnable verification procedure or command lane
- use `## Evidence` for shipped-behavior contrast pages that close with proof, examples, traces, or source-backed observations
- subtree front doors such as `README.md` may stay routing-only when they clearly act as routers rather than proof-owning pages

## Page-type rules

Separate page types clearly.

- **Overview / topic page**: what the surface is, what it owns, how to use it safely
- **Guide**: one workflow from prerequisites to verification
- **Reference**: exhaustive fields, flags, schemas, enums, contracts, outputs
- **Internals**: stable implementation mechanics for contributors and maintainers
- **Troubleshooting**: symptom -> checks -> cause -> fix
- **Plan / review / evidence**: internal canon only
- **ADR**: durable accepted decision, context, alternatives, and consequences

Do not let one page try to be all of these at once.

## Writing and freshness rules

- open with the page's main claim, task, or decision in the first paragraph
- keep one main audience and one main scope per page
- prefer descriptive headings and short sections over long mixed-purpose walls of text
- put examples near risky or non-obvious steps instead of far away in an appendix when the example is needed to execute safely
- update or retire affected docs in the same change window as behavior changes whenever practical
- do not let `design`, `current`, public reference, and troubleshooting pages silently disagree; reroute, archive, or mark stale pages once one surface stops being true

## Architecture plus internals pattern

For important technical surfaces, prefer the OpenClaw-style pairing:

- `surface.md` -> boundary, purpose, ownership, supported behavior
- `surface-internals.md` -> pipeline, state model, mechanical details, tables, and deeper contributor reference

Use this pattern only when both pages have a clear audience and durable value. Do not create an `-internals` page just to park temporary notes.

## Navigation rules

- public docs navigation should be curated by reader intent, not derived mechanically from folders
- internal canon pages should not become the default public browsing surface
- maintainer-heavy public pages should live under reference or maintainer lanes, not under onboarding
- internal canon should not be mixed into the public nav by default
- if a page is private, scratch, or mirror-only, keep it out of public nav and publish paths
- do not keep redirect-style wrapper, router, or compatibility pages after moving public docs; delete the old page, update real links, and let missing old paths fail visibly
- do not keep parallel live `README.md` and `INDEX.md` front doors that both claim owner authority for the same subtree
- use human-readable link labels such as `docs structure guide` or `current runtime read models and operator surfaces` for navigation; do not expose `.md` filenames as link text unless the filename itself is the subject

If an unpublished scratch area is needed later, prefer:

- `docs-internal/scratch/**`

Do not let scratch pages compete with design, current, execution, archive, or public reference owners.

## Duplication rules

- keep one canonical owner for each truth surface
- do not duplicate the same contract across public guide, public reference, and internal canon pages unless one page is intentionally a short routing summary
- if a public page depends on deep implementation detail, summarize the implication and link to the owning reference or internals page
- if an internal design or current page exists only to preserve temporary contrast, keep it out of stable public reference lanes
- if a version split exists internally, avoid repeating the same stable content across `v1/`, `v2/`, and `vnext/` unless the contract truly changed

## Migration rules

When redesigning the docs tree:

1. classify the page as public product/operator, public reference/internals, or internal canon
2. decide the page type before moving or rewriting it
3. decide whether the content belongs to a specific internal version era
4. preserve canonical transitional truth until a replacement owner is explicit
5. move stable reader-facing material into the public `docs/**` lanes
6. move internal versioned material into `docs-internal/**`
7. add redirects or routing notes when a moved page had meaningful prior entry points
8. when renaming `redesign` to `design`, update routing language together with the path move so truth does not fork

Do not flatten `docs-internal/design/v1` and `docs-internal/current/v1` directly into one public tree without reclassifying the audience, page type, and version ownership first.

## Cross-checks

- if the page claims target truth, verify it matches the active design canon path for this repo stage
- if the page claims shipped truth, verify it matches current behavior or explicit migration notes
- if the page claims public reference, verify the contract is stable enough to expose as durable reference
- if the page claims internals, verify the audience is contributor or maintainer and the mechanics are not just temporary execution notes
- if the page is guidance only, verify it does not silently compete with root canon
- if the page sits under internal canon, verify its version-era home is explicit or intentionally versionless for ADR reasons
