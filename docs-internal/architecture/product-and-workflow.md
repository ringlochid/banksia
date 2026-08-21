# Product and Workflow

Status: Reference

This page owns Oh My Subagents's product model, authored Workflow contract, authoring lifecycle, Task-start request, and Assignment contract.

## Product position

Oh My Subagents is a controlled agent-team runtime for work that benefits from explicit delegation without losing one accountable owner. It productizes a familiar subagent practice:

```text
user suggests a reusable team
  -> Task lead receives one concrete prompt
  -> Managers choose and revise actual work from evidence
  -> teammates return durable Checkpoints with optional file references
  -> controller records authority, causality, joins, and recovery
  -> Task lead returns one integrated Result
```

“Reproducible” means Oh My Subagents preserves exact authored inputs, resolved Dispatch requests, provider selections, structural history, Assignments, Attempts, continuations, Checkpoints, `FileReference` values, and controller decisions. It does not archive referenced-file bytes or promise deterministic provider output or deterministic replay of concurrent agents writing one shared workspace. Exact file reconstruction depends on the user's own workspace/version-control state.

The tree answers **who owns which responsibility**. It does not answer when a member runs. Runtime Work Plans and Delegation Waves record the actual timing.

## Canonical product language

Oh My Subagents uses a small canonical vocabulary across the Workflow schema, system prompt, controller API, Activity, and documentation. Some of these words have broader meanings in other agent products, so Oh My Subagents defines them explicitly instead of relying on industry shorthand.

| Term | Oh My Subagents meaning |
| --- | --- |
| **Workflow** | A reusable, publishable team definition: one responsibility hierarchy plus optional team-specific guidance and provider intent. It is not a prescribed step sequence or executable graph. Use **Workflow definition** on first mention when the distinction matters. |
| **Task** | One commissioned execution pinned to one Workflow revision, one workspace, and one accountable Task lead. |
| **Member** | One responsibility holder in the Task's recursive team hierarchy. It is the structural noun, not a provider process or authored role kind. |
| **Task lead** | The top Member and owner of the exact Result shown to the user. |
| **Manager** | The current behavior of a Member with direct children. A Manager retains the complete Assignment and integrates child contributions. |
| **Contributor** | The current behavior of a Member without direct children. A Contributor performs the substantive work of its Assignment. |
| **Assignment** | One immutable, complete, task-specific request owned by one Member, with optional file references. |
| **Delegation Wave** | One controller-managed fan-out/fan-in group of direct-child Assignments. When the Task remains eligible, the parent resumes once after every Wave member reaches a terminal outcome. |
| **Checkpoint** | A durable, teammate-facing work report tied to an exact Assignment execution. It is not a saved graph or process-state snapshot. |
| **FileReference** | One ordered `{path, description?}` navigation value pointing to an ordinary loose workspace file. It is not a file resource, attachment copy, or byte snapshot. |
| **Continuation** | The exact successor context created from one committed controller source after delegation, replan, an external wait, retry, or recovery. |
| **Result** | The accepted terminal `green` or `blocked` Checkpoint from the Task lead, exposed to the user without a second model-authored summary. |

`notes/` and `artifacts/` are lowercase workspace conventions, not additional controller domain resources. A note is mutable working memory for coordination or recovery. An artifact file is a reviewable deliverable created for another Member or the user. Both remain ordinary loose files and use the same `FileReference` value for an explicit navigation handoff when needed.

Documentation may mention familiar equivalents such as *subagent*, *orchestrator-worker*, *fan-out/fan-in*, *prompt chaining*, or *evaluator-optimizer* when comparing systems. Oh My Subagents contracts and model-facing prompts use the canonical nouns above. In normative prose, an initial capital may distinguish the named product concept when ambiguity matters; code identifiers keep their defined casing, and ordinary generic uses remain lower case.

## One authored definition

A Workflow is the only authored, draftable, publishable definition. It contains one recursive responsibility tree:

```text
Workflow
  kind = workflow
  id
  catalog description
  optional shared note
  lead: Member
    id
    optional title / description / instruction
    optional provider override
    optional built-in capabilities
    optional children: Member[]
```

The lead uses exactly the same Member schema as every descendant. `children` remains the relationship name because it states the recursive tree directly. There is no separate Role, Policy, manager object, worker kind, or node type.

### Field meanings

| Field | Meaning |
| --- | --- |
| Workflow `id` | Stable catalog identity, not a revision, runtime ID, or hash. |
| Workflow `description` | Required nonblank explanation of when this Workflow is useful. |
| Workflow `note` | Optional shared Markdown for purpose, preferences, non-goals, caveats, and heuristics. It is never parsed as policy or a plan. |
| Member `id` | Stable identity within the complete Workflow tree. IDs are unique and non-reused within that Workflow tree and immutable after creation; no cross-Workflow global namespace is implied. |
| Member `title` | Optional human display text. UI falls back to the ID or “Untitled member” while drafting. |
| Member `description` | Optional responsibility or routing hint. |
| Member `instruction` | Optional reusable, team-specific contribution guidance. It is not the current Task, Assignment, or Oh My Subagents operating manual. |
| Member `provider` | Optional per-member provider selection intent. |
| Member `capabilities` | Optional grants for Human Request kinds and managed Command Run. Omitted grants deny. |
| Member `children` | Ordered direct responsibilities. Order is organizational and never execution order. |

Blank optional text, whitespace-only text, empty strings, and explicit `null` normalize to omission before canonical draft/revision persistence. Top-level Workflow description remains required and nonblank. Sparse members are valid because every execution Assignment still contains a required prompt.

Workflow-authored prose never owns general Oh My Subagents behavior. The Workflow `note` may describe this team's suggested collaboration, purpose, preferences, non-goals, and caveats. A Member `instruction` may specialize that Member's responsibility or independent lens. Accountable management, work-pattern choice, replan, notes/artifacts/file references, Checkpoints, Human Request, Command Run, Continuation, and controller-action rules come from the [system prompt](system-prompts.md), even when an example Workflow uses them.

### JSON and YAML

The maintained [Workflow schema](../../docs/reference/workflows/workflow-definition.schema.yaml) is a JSON Schema document serialized as YAML. It validates the JSON-compatible value created by either a strict JSON parser or a strict YAML parser.

- Workflow Studio and browser APIs exchange structured JSON only.
- CLI import accepts `.json`, `.yaml`, and `.yml` by extension.
- CLI stdin requires an explicit `--format json|yaml`; it never guesses.
- Both parsers require one object document, unique string keys, finite JSON-compatible values, and bounded input.
- YAML aliases, merge keys, and application-specific tags are rejected.
- Comments, whitespace, key order, and scalar style are not preserved as Workflow meaning.
- Drafts and revisions store one normalized structured object, not editable YAML plus a JSON shadow.
- Export renders JSON or YAML from the same normalized object.

Schema validation covers local shape. Semantic validation additionally enforces member-ID uniqueness within the complete Workflow tree, controller-owned input and responsibility-tree bounds, currently supported provider settings, and deterministic authored child order.

All accepted authored and task prose uses one normalization rule: convert CRLF and lone CR to LF; preserve every other whitespace code point and Unicode code point exactly; use trimming only to decide whether a required value is nonblank or an optional value should be omitted; reject NUL and every XML 1.0-illegal character. Never replace, drop, or Unicode-normalize accepted characters. XML rendering later escapes the stored value rather than changing it.

### What `$ref` and `$defs` mean

The schema repeats the Member and provider shapes recursively, so it names them once:

- `$defs` is a dictionary of reusable schema fragments inside this schema. It does not add fields to a Workflow document.
- `$ref` points to one of those fragments. For example, `#/$defs/workflowMember` means “validate this value using the `workflowMember` fragment in this same file.”
- The leading `#` means the current schema document. The slash-separated part is a JSON Pointer locating the named fragment.

`lead` and every item in `children` reference the same `workflowMember` definition. That is how the schema expresses an arbitrarily nested tree without copying the Member definition many times. Authors never write `$ref` or `$defs` inside their Workflow YAML or JSON.

## Provider configuration

`provider.kind` is the closed adapter discriminator. `name` is not used because Codex and Claude are implementation kinds, while title is human display text and model is provider-native selection.

Managed providers:

```yaml
provider:
  kind: codex # or claude
  model: provider-native-model-id # optional, exact, no fallback
  effort: high # optional provider-supported value
  sandbox: # optional as a whole
    mode: full_access
    network: allow
```

Rules:

- Omitting `provider` resolves the controller’s configured default provider.
- An explicit provider never silently falls back to another provider or model.
- Omitted fields resolve from that provider’s controller configuration, not from the parent member.
- Omitted managed-provider sandbox resolves to `full_access` plus `allow`.
- If `sandbox` is authored, both fields are required and only these portable pairs are legal: `read_only/deny`, `workspace_write/allow|deny`, and `full_access/allow`.
- The Workflow contains no credentials, endpoint, executable, environment, provider home, CLI arguments, session IDs, or fallback routes.
- Controller/deployment enforcement can narrow a request and every Dispatch records the exact requested/resolved provider configuration and provenance.

Existing immutable Workflow revisions or drafts may still contain the retired `openclaw` discriminator. That value is readback-only historical truth. It is not present in authoring options, cannot be supplied by an import or mutation, and makes the draft invalid until the affected Member selects Codex, Claude, or no explicit provider. Oh My Subagents never rewrites the old value automatically.

## Built-in capabilities

Workflow authors may grant only two built-in controller operations per Member:

```yaml
capabilities:
  human_request:
    - input
    - direction
    - approval
    - review
  command_run: allow
```

- Omitted `capabilities`, omitted fields, and descendants without their own block deny the corresponding operation.
- Human Request kinds are explicit and unique. An empty list or empty capability block rejects rather than adding noise.
- `command_run` accepts only the literal `allow`; deny is represented by omission.
- Capabilities do not inherit from a parent Member.
- Controller/deployment policy may narrow an authored grant but never widen it. Every Dispatch records the requested and effective set with provenance and exposes only currently legal tools.
- Capabilities authorize operations. They do not contain general instructions, tool schemas, limits, retries, budgets, arbitrary tool names, provider-native permissions, or external MCP configuration.

General teaching such as when a material user decision warrants a Human Request, when a long-running process warrants Command Run, and the requirement to stop after opening a wait belongs exclusively to the [controller-owned system prompts](system-prompts.md). Workflow `note` and Member `instruction` remain team-specific guidance.

## Authoring lifecycle

Keep a Workflow-specific controller catalog:

```text
normalized mutable draft
  -> validate
  -> explicit publish
  -> immutable Workflow revision
  -> current-published pointer
  -> Task pins exact revision atomically at start
```

The controller may keep private integrity hashes and ETags for corruption, idempotency, and concurrent authoring. They are not Workflow fields, agent input, file versions, or human-authored identifiers.

There is no generic `DefinitionKind`, Role/Policy lookup, runtime definition search, or compiled dependency graph. Replace compilation with:

1. `normalize_workflow` and `validate_workflow`; and
2. `materialize_initial_task_team` from the pinned revision.

Browser and Operator creation use one controller-owned draft-opening boundary:

```text
create new
  -> Workflow ID + required description + optional ID-less lead settings
  -> controller allocates the lead Member ID
  -> complete active draft readback

open for editing
  -> Workflow ID
  -> return the existing active draft, or atomically clone the current
     published revision and pin its base revision
  -> complete active draft readback
```

The unified Workflow library includes draft-only, published-only, and published-with-draft entries. Draft-only truth must not depend on a retained browser URL, local storage, or an Operator transcript. Library and detail readbacks expose semantic state, last controller update time, and the closed currently legal action set. Full JSON/YAML CLI import remains a separate ingestion path that may carry authored stable Member IDs through the complete Workflow definition.

The draft-opening response distinguishes creation from idempotent reuse: creation returns HTTP `201 Created` with the draft resource location, while returning an already-active draft uses `200 OK`. HTTP and Operator use the same discriminated request and domain operation. Workflow detail is assembled from one coherent controller snapshot so concurrent open, edit, publish, or discard cannot produce a state/draft/publication combination that never existed.

Removing a Workflow discards its active draft and clears its current-published pointer. This releases the Workflow ID for an explicit user creation while preserving immutable revisions required by existing Task pins. Re-creation opens a fresh draft with no base revision; publishing it appends or reselects immutable user history through the ordinary publication boundary. Starter bootstrap never reactivates a removed Workflow implicitly.

### Reference examples and packaged Starter Workflows

The maintained [Workflow examples](../../examples/workflows/README.md) are documentation and validation fixtures. They demonstrate the full authoring language, including optional provider, sandbox/network, model/effort, and capability settings. They are never package seeds and are never automatically installed, published, or selected for a user.

The separate packaged Starter Workflow resources define the eight Workflows installed during bootstrap:

- `production-feature-delivery`
- `incident-investigation-and-recovery`
- `migration-and-modernisation`
- `deep-research-and-decision-brief`
- `decision-through-competing-prototypes`
- `idea-to-validated-demo`
- `experiment-and-replication-program`
- `security-audit-and-hardening`

They upgrade complex daily and ambitious developer/researcher work through distinct responsibility, evaluation, and verification boundaries. Every seeded Member omits `provider`, so the active installation resolves its own default provider. Starters may include narrow built-in Human Request or managed Command Run grants where interaction or a durable process is intrinsic to that responsibility. Every omitted capability remains denied, capabilities never inherit, and the Workflow library and Task-start selection disclose the effective authored grants before use.

The maintained advanced reference inventory is separate: `advanced-reviewed-code-change`, `advanced-cross-layer-delivery`, and `advanced-technical-decision`. Those files may demonstrate justified provider, sandbox, network, Human Request, and Command Run choices, but bootstrap never installs them.

On first initialization or reset, seed bootstrap validates normalized content and transactionally creates immutable published revisions with package-owned provenance. Repeating identical seed content is idempotent. A changed packaged seed advances currentness only while the current revision remains package-owned; it must not replace a user-authored current revision. After bootstrap, the controller catalog is authority and Tasks pin exact revisions; runtime never rereads packaged YAML.

## Task start

Remove Task Compose completely. All entry points converge on:

```text
TaskStartRequest {
  workflow: WorkflowId,
  prompt: nonblank Markdown,
  workspace?: absolute or transport-resolved path,
  files?: [{path, description?}]
}
```

Workspace omission is transport-specific and never resolves from the server process working directory. Interactive and machine CLI use the invocation cwd. HTTP, Console, and Operator use the controller-configured workspace for that transport; if none is configured, admission returns a semantic 422 requiring a workspace instead of guessing.

The request is transient. Its facts move to their natural owners: Task pins the Workflow revision and workspace, the root Assignment owns the exact prompt and ordered file references, and the controller creates Task identity.

Task-start `files` therefore name existing regular files beneath the selected workspace. They cannot predict the controller-allocated Task directory. Later Assignments, Checkpoints, and Human Requests may reference files under the created `.banksia/t_<id>/` path.

Interactive CLI:

```text
oms task start
  -> choose one published Workflow
  -> edit one prompt
  -> use current directory as workspace
  -> start and print a human receipt
```

Machine CLI:

```text
oms task start --json '{"workflow":"delivery-review","prompt":"Fix and verify the bug."}'
oms task start --json @request.json
oms task start --json - < request.json
```

`--json` always takes exactly one request source, never prompts, emits one JSON receipt, and uses a stable JSON error envelope. Unknown request fields reject. An accepted receipt means the start transaction committed, not that provider startup or the Task completed.

HTTP, Console, CLI, and Operator invoke the same start service. Validation must complete before Task/workspace mutation or provider I/O. There is no separate Compose preview; Workflow validation and atomic Task-start validation are the two honest boundaries.

## Assignment

Root and child Assignments use one contract:

```yaml
prompt: |
  Complete, task-specific request owned by this member.
files:
  - path: .banksia/t_7m4k2d9x/artifacts/research-brief.md
    description: Reviewable evidence brief to inspect rather than assume.
```

- `prompt` is required, nonblank, bounded Markdown and immutable for one Assignment.
- It contains objective, context, boundaries, evidence expectations, and return guidance naturally when relevant; none becomes mandatory structured fields.
- It is rendered in full in every Dispatch, child return, and current-context projection.
- Same-Assignment retry/recovery reuses the exact stored prompt.
- A materially changed request or feedback creates a fresh Assignment.
- UI lists may derive an excerpt, but no excerpt is persisted or sent as a second instruction.
- File-reference entries are immutable path/description values on the Assignment, not controller-owned file resources. The referenced file remains mutable workspace state and is opened through native filesystem access. It may be an ordinary project file, a free-form Task note, a reviewable loose artifact file, or a Command Run log.

## Intentionally absent

Workflow and Task authoring contain no Role, Policy, Skill definition, generic capabilities, limits, arbitrary tools, external MCP configuration, steps, stages, handoffs, edges, dependencies, loop/batch mode, criteria, consume, produce, expected-output declaration, slots, transient refs, hashes, semantic versions, current pointers, controller-owned Artifact resources, arbitrary provider options, or standalone network field. A managed provider's `extension_mode` only selects whether already configured user and project Skills plus MCP servers may be visible; it does not define, install, configure, or authorize them. The lowercase `artifacts/` workspace directory is only a loose-file convention and does not contradict this resource-model exclusion.

Provider-native tools remain adapter capability. Oh My Subagents's structural and Checkpoint actions derive from current runtime legality. Human Request and Command Run additionally require the narrow authored grant above; neither is a generic Workflow extension system.
