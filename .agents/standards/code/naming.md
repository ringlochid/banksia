# Naming standard

Status: Reference

Use this guide when naming or renaming symbols, files, packages, routes, CLI surfaces, schemas, or docs-era paths.

## Goals

- make ownership and behavior obvious from the name alone
- keep one concept mapped to one canonical term
- make side effects and boundary roles visible
- keep structural names shallow, stable, and responsibility-oriented

## Core rules

- use the same term for the same concept across touched code, docs, and tests
- use different terms for genuinely different concepts
- prefer familiar, specific words over broad or clever ones
- public names should still make sense when read out of local file context
- if a name needs surrounding explanation to be safe, the name is probably weak

## Canonical term discipline

- pick one canonical noun for each important domain concept and keep it stable
- do not alternate between near-synonyms such as `task`, `job`, `step`, `event`, or `message` unless canon defines them as different things
- when a concept already has a canonical repo term, reuse it instead of introducing a cleaner-sounding synonym
- when a rename is necessary, migrate the family together instead of leaving mixed terminology behind
- do not encode internal execution routing labels, waves, or package chronology into shipped default identifiers, public strings, or persisted metadata unless the field is explicitly historical or test-only

Questions to ask:

- what exact concept does this name refer to
- does the repo already have a stronger canonical term for it
- would a new reader mistake it for a different existing concept

## Acronyms and abbreviations

- avoid private team abbreviations, deleted vowels, and initials that only make sense to the author
- treat acronyms as words inside TypeScript and JavaScript identifiers unless a generated type or platform name forces the spelling
- prefer `taskId`, `apiClient`, `sseClient`, `openApiSchema`, and `httpStatus`
- avoid `taskID`, `APIClient`, `SSEClient`, `OpenAPISchema`, and `HTTPStatus`
- keep API wire field names exact when reading generated OpenAPI types; translate only in explicit mappers or view-model builders

## Public versus local names

- public modules, exported functions, shared helpers, schema classes, ORM models, and CLI/API surfaces should be descriptive out of context
- local loop variables and short-lived temporary names may be shorter, but they still need to reflect the real role they play
- do not promote local shorthand into a shared API surface

Prefer:

- `reconcile_current_dispatch`
- `resolved_revision`
- `dispatch_transition_result`

Avoid:

- `run_step`
- `value`
- `result_data`

## Function naming rules

- use verb-led names for functions and methods
- the verb should reveal the dominant effect or contract
- use neutral verbs only for genuinely generic infrastructure or extremely local helpers

Preferred verb lanes:

- `build_*`: construct a value without external side effects
- `validate_*`: enforce a contract or invariant
- `read_*`, `load_*`, `list_*`, `get_*`: query existing state
- `parse_*`, `normalize_*`, `resolve_*`, `select_*`: transform or derive state
- `create_*`, `start_*`, `write_*`, `persist_*`, `delete_*`: perform external or durable side effects
- `reconcile_*`, `sync_*`, `merge_*`: align two truths or state views
- `render_*`, `map_*`, `present_*`: shape output for another surface

Avoid vague verbs when a stronger one exists:

- `handle`
- `process`
- `run`
- `do`
- `apply`
- `check`

If a function writes to the DB, controller state, filesystem, network, or support-state artifacts, the name should make that unsurprising.

## Boolean naming rules

- booleans should read like facts, capabilities, or decisions
- prefer `is_*`, `has_*`, `should_*`, and `can_*`
- use positive predicates unless the negative form is the true domain concept
- avoid bool names that read like bags, statuses, or half-phrases

Prefer:

- `is_terminal_checkpoint`
- `has_active_assignment`
- `should_retry_dispatch`
- `can_resume_session`

Avoid:

- `terminal_status`
- `retry_flag`
- `session_check`
- `not_ready`

## Variable naming rules

- make data-state transitions visible in the name when that distinction matters
- prefer names that reveal whether the value is raw, normalized, selected, resolved, persisted, current, target, or previous
- do not use container-shaped names when the real meaning is known

Prefer:

- `raw_payload`
- `normalized_request`
- `persisted_run_record`
- `target_revision`

Avoid:

- `data`
- `obj`
- `item`
- `stuff`
- `payload_info`

## Type and schema suffix rules

Use suffixes intentionally. Do not reuse them as decoration.

- `*Model`: ORM or persisted model truth
- `*Request` / `*Response`: API or RPC wire contract
- `*Payload` / `*Body`: transport-shaped payload
- `*State`: runtime logical state
- `*Record`: stored or emitted structured record
- `*Snapshot`: assembled read-only view
- `*Result`: operation outcome
- `*Config` / `*Settings`: configuration
- `*Error` / `*Failure`: failure type or structured error lane

Rules:

- do not call a non-ORM domain object `*Model`
- do not use `*Payload` for authoritative persisted truth
- do not mix `*State`, `*Snapshot`, and `*Result` casually; they mean different things

Frontend-specific suffixes:

- `*Props`: React component props only
- `*ContextValue`: value returned by a React context provider
- `*Action`: reducer or state-machine action union
- `*Row`, `*Item`, `*Summary`, `*Details`, `*View`: render-ready view-model shapes
- `*Draft`: unsaved browser-local form or editor state

Rules:

- do not suffix React render shapes with `*Model`; controller and ORM truth already use model vocabulary elsewhere
- do not prefix TypeScript interfaces with `I`
- do not use `VM` when a readable suffix such as `Row`, `Item`, `Summary`, or `View` would say more
- do not name browser-local state `Record`, `Snapshot`, or `Payload` unless it really has that contract role

## Weak names to avoid

Avoid these unless the repo has a very specific canonical meaning for them:

- `helper`
- `manager`
- `processor`
- `wrapper`
- `service`
- `common`
- `misc`
- `data`
- `info`
- `thing`
- `item`
- `flag`
- `check`

These names usually hide responsibility rather than exposing it.

## File and module naming rules

- file and module names should name the dominant responsibility directly
- do not encode chronology, migration state, or local sentiment into steady-state paths
- keep one stable family stem per concern
- when three or more siblings share a stem, prefer a responsibility-named package over more flat-prefix growth

Prefer:

- `task_reconcile.py`
- `definition_catalog.py`
- `operator_trace.py`

Avoid:

- `runtime_helpers.py`
- `dispatch_common.py`
- `new_flow_service.py`
- `task_reconcile_v2_final.py`

## Frontend TypeScript and React naming rules

Use the ecosystem conventions where they carry framework meaning, then apply AutoClaw domain vocabulary inside them.

- React components use `PascalCase`: `TaskTable`, `HumanRequestDrawer`, `CommandRunLog`
- component files use `PascalCase.tsx` when the file primarily exports one component: `TaskTable.tsx`
- hooks use `use` plus a domain verb or noun phrase: `useTaskEvents`, `useHumanRequestResolution`
- hook files should stay feature-local and use a readable module name such as `use-task-events.ts`
- non-component TypeScript modules use lower kebab-case by responsibility: `task-event-mappers.ts`, `command-run-actions.ts`
- feature folders use product route nouns in kebab-case: `task-detail`, `human-requests`, `command-runs`
- exported type aliases, interfaces, reducer actions, and context values use `PascalCase`
- variables, local functions, mappers, and non-component helpers use `camelCase`
- constants use `UPPER_CASE` only for true module-level constants that behave like immutable configuration; otherwise use `camelCase`
- event props use `on*`: `onResolve`, `onCancel`, `onSelectTask`
- local event handlers use `handle*`: `handleResolve`, `handleCancel`, `handleTaskSelect`
- boolean props and state use `is*`, `has*`, `can*`, or `should*`
- reducer actions should name the event that occurred, not the implementation: `taskEventAppended`, `humanRequestResolved`
- context owners use one family stem: `TaskSelectionContext`, `TaskSelectionProvider`, `useTaskSelection`
- console CSS custom properties use the `--ac-*` namespace; do not keep ambiguous prototype prefixes from the design handoff

Avoid:

- generic component names such as `Card`, `Panel`, `List`, or `Dialog` outside `components/ui/**` unless the primitive itself owns that generic role
- route or page components named only `Index`, `Screen`, `Page`, or `View`
- hook names such as `useData`, `useFetch`, `useStuff`, or `useApi` when the owned route family is known
- props such as `data`, `item`, `info`, `callback`, or `setThing` when the component contract can name the product concept
- `index.ts` barrels that hide ownership or create circular import temptation; use them only for deliberate package surfaces

Generated OpenAPI names are allowed to follow generator output. Do not rename generated types manually; wrap them in domain mappers when React needs a clearer render name.

## Package and directory naming rules

- package levels should reflect ownership and responsibility, not generic categorization
- one or two meaningful levels are usually enough
- avoid adding directory layers merely to group similar leftovers
- use version directories, not filename suffixes, for internal docs eras

Prefer:

- `runtime/watchdog/`
- `registry/revisions/`
- `docs-internal/design/<version>/`

Avoid:

- `runtime/internal/shared/common/`
- `services/helpers/misc/`
- `runtime-v2-final.md`

## API, CLI, and route naming rules

- resource or noun surfaces should use nouns
- action helpers should use verbs
- do not name a stable public surface after a transport accident or vague implementation detail
- route modules should usually be noun-oriented owners, while internal helpers can be verb-oriented
- prefer one stable interface family such as `interfaces/http/**`, `interfaces/cli/**`, and `interfaces/mcp/**` over several unrelated top-level transport stems
- keep non-route support modules out of route-only packages; contract, presenter, or translation helpers should live under a clearly named owner rather than under `routes/**`
- avoid route-package support filenames such as `*_models.py` when the real owner is a contract or presenter surface

Prefer:

- route modules: `definitions.py`, `runtime.py`, `operator.py`
- support owners: `interfaces/http/contracts/health.py`, `interfaces/http/errors.py`
- methods: `list_definitions`, `create_task`, `reconcile_runtime_state`

Avoid:

- route modules: `do_runtime.py`, `misc_routes.py`
- route support modules: `routes/health_models.py`
- methods: `handle_runtime`, `process_definition`

## Renaming discipline

- when a canonical term changes, update docs, tests, schemas, and call sites in the same slice when practical
- do not leave comment text, test names, and helper names on the old term after code moved to the new one
- if a full rename is too wide for the phase, document the remaining exact exceptions in review

## Review checklist

- does the name expose the real domain concept
- would a reader understand the symbol or path without reading the whole file
- is the effect type obvious for side-effecting functions
- are boolean names fact-shaped
- is the suffix semantically correct
- does this family use one stable stem
- did the rename remove synonyms rather than adding another one
