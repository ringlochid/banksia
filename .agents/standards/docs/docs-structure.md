# Docs structure standard

Status: Reference

Use this guide when adding, moving, splitting, or retiring documentation.

## Core model

Oh My Subagents separates documentation by audience, task, page type, and authority. The documentation tree does not mirror the code tree or implementation chronology.

Use three layers:

1. **Public product and operator docs** teach supported setup, authoring, operation, concepts, and troubleshooting.
2. **Public reference and internals docs** provide exact CLI, configuration, schema, API, tool, maintainer, and stable implementation lookup.
3. **Internal docs** own architecture, interface contracts, operational mechanics, and durable decisions.

## Maintained layout

- `README.md` is the public product front door.
- `CONTRIBUTING.md` is the public contributor front door.
- `docs/**` contains public product, guide, concept, help, and reference pages.
- `examples/**` contains maintained user-facing examples.
- `docs-internal/architecture/**` owns runtime and product architecture.
- `docs-internal/interfaces/**` owns controller, Console, Operator, and tool contracts.
- `docs-internal/operations/**` owns configuration, recovery, packaging, and reset behavior.
- `docs-internal/adr/**` owns durable accepted decisions.

Keep public and internal docs versionless unless the product intentionally supports multiple reader-facing versions at once. Do not create current-versus-target, execution, archive, or version-era authority lanes.

## Authority metadata

Public pages under `README.md`, `CONTRIBUTING.md`, and `docs/**` do not expose `Status:` or `Last verified:` headers. Open them with the product claim, task, or answer.

Maintained internal pages and routers use `Status: Reference`. Individual ADRs use `Status: Accepted`, `Status: Superseded`, or `Status: Reference`. `Status: Template` is reserved for reusable templates.

Avoid custom status labels. Put a page's role in its title and opening paragraph.

## Placement rules

Put a page in public product or operator docs when a reader needs it to install, author, run, inspect, recover, or troubleshoot Oh My Subagents.

Put a page in public reference or internals when it is stable lookup material for users, integrators, contributors, operators, or maintainers. Examples include exact CLI flags, configuration precedence, schemas, HTTP payloads, controller tools, and testing commands.

Put a page in internal docs when it owns implementation architecture, an exhaustive internal contract, an operational boundary, or a durable decision.

Scratch research and temporary execution notes belong under ignored `tmp/**`, not the maintained documentation tree.

## Page types

- **Overview or concept:** what the surface is and how to reason about it.
- **Guide:** one workflow from prerequisites through a checked outcome.
- **Reference:** exhaustive fields, flags, schemas, enums, contracts, and outputs.
- **Internals:** stable implementation mechanics for contributors and maintainers.
- **Troubleshooting:** symptom, checks, cause, and fix.
- **Verification:** executable gates and expected proof.
- **ADR:** durable decision, context, alternatives, and consequences.

Keep one main audience and one main page type per page.

## Writing and freshness

- open with the page's main claim, task, or decision
- use descriptive headings and short, cohesive sections
- place examples next to risky or non-obvious instructions
- update or retire affected docs with behavior changes
- keep one canonical owner for each truth surface
- summarize an owned contract at another layer only when the summary serves that layer's audience, and link back to the owner
- do not preserve redirect-only wrapper pages after moving documentation; update real links and let deleted paths fail visibly

## Navigation

- curate public navigation by reader intent
- route every maintained internal page from `docs-internal/README.md`, directly or through a linked owner page
- keep internal docs out of public navigation by default
- use human-readable link labels rather than filenames
- keep generated files under their named generated directory and regenerate them through the owning command

## Change procedure

When changing the docs tree:

1. identify the audience, page type, and canonical owner
2. move or rewrite the maintained content into its final lane
3. update links, tooling paths, generated outputs, tests, and front doors together
4. delete replaced pages instead of leaving parallel truth
5. run the complete docs gate and any focused contract tests

## Cross-checks

- public behavior matches the shipped interface
- public reference is stable enough to support as a durable contract
- internal mechanics match code, generated contracts, and verification gates
- guidance does not compete with `AGENTS.md`, `STYLE.md`, an internal owner, or an accepted ADR
- no maintained page depends on ignored scratch content, except an explicitly bounded reference protocol
