# Artifact Ref And Storage Contract

Status: Target

This page defines the canonical durable artifact storage model, the shared runtime-file versus evidence-ref split, and the artifact currentness rules for the design v1 runtime.

It owns:

- immutable durable artifact publication layout
- artifact publication lineage and explicit current-pointer meaning
- the artifact subset of the shared surfaced-ref taxonomy
- the boundary between compact ordinary artifact refs and controller-owned provenance/currentness carriers
- the split between authoritative durable currentness and attempt-local publication ledgers

It does not own:

- route exposure or public definition-upload response carriers
- launch binding or runtime graph currentness outside artifact current pointers
- prompt assembly rules
- `ContextManifest`, which is transitional/private only if it exists at all
- assignment or checkpoint field ownership, which belongs to the standalone assignment and checkpoint contracts

## Core rule

Durable artifacts are immutable published outputs under `outputs/artifacts/`.

They are:

- controller-accepted durable publications
- versioned per `(owner_node_key, slot)`
- backed by `artifact_publications` history rows plus `artifact_current_pointers`
- surfaced to agents through compact `evidence_ref` values with `kind: artifact`
- kept distinct from transient carryover, checkpoints, and observability-only runtime refs

Durable artifacts are not:

- workspace scratch files
- mutable latest aliases
- prompt-only references
- object-store-only blobs whose meaning exists only outside the task root

Freeze the durable versus transient split:

- durable artifacts live under `outputs/artifacts/` and are governed by controller rows plus `current.json`
- transient carryover is surfaced explicitly through assignment/checkpoint `transient_refs`
- no transient `current.json` or equivalent transient current-pointer family exists

## Shared surfaced-ref taxonomy

V1 uses three shared surfaced-ref families. Do not collapse them into one generic path object.

```yaml
node_runtime_file_ref:
    kind: manifest | assignment | checkpoint | artifact_index | transient_index
    path: string
    description: string

support_runtime_file_ref:
    kind: delivery_state | continuity_state | watchdog_state | provider_events
    path: string
    description: string

evidence_ref:
    kind: artifact | criteria | doc | wiki | transient
    slot: string | null
    version: integer | null
    path: string
    description: string
```

Rules:

- `node_runtime_file_ref` points at controller-generated runtime projections that may be surfaced in ordinary node-visible carriers
- `support_runtime_file_ref` points at controller-generated observability-only projections
- `support_runtime_file_ref` kinds are legal only on observability/operator carriers; manifest, assignment, checkpoint, and ordinary prompt context do not surface them
- `evidence_ref` points at durable evidence/support material or explicit surfaced transient carryover
- `artifact` is the only `evidence_ref` kind that carries `version`

## Authored slot identity versus runtime storage identity

Artifact slot identity splits cleanly between authored workflow meaning and runtime persistence.

Rules:

- authored artifact `slot` ids are globally unique across one workflow
- because authored slots are globally unique, a consumer selector does not carry a producer node id in v1
- runtime still resolves the publishing node for the selected artifact slot
- durable artifact publication and currentness are tracked by `(owner_node_key, slot)`
- `version` increments within that `(owner_node_key, slot)` pair only
- the durable path namespace is `outputs/artifacts/<owner_node_key>/<slot>/...`

Most important distinction:

- `slot` is the authored selector identity readers use
- `(owner_node_key, slot)` is the persisted runtime storage/currentness identity controllers use

Do not collapse those into one field family.

### When `owner_node_key` is persisted but not surfaced

Rules:

- `owner_node_key` must be persisted in controller-owned publication and currentness truth
- `owner_node_key` must appear in durable storage paths, publication ledgers, `current.json`, and DB/object records
- ordinary agent-visible artifact refs in manifest, assignment, checkpoint, and API read carriers do not surface `owner_node_key` as a top-level ref field
- ordinary refs stay compact because authored artifact slots are already globally unique

If provenance matters for audit/operator/debug questions, expose `owner_node_key` through controller-owned lineage or publication carriers, not by widening every ordinary artifact ref.

## Canonical durable layout

Use this exact durable layout:

```text
outputs/
  artifacts/
    <owner_node_key>/
      <slot>/
        <slot>.v01.<ext>
        <slot>.v02.<ext>
        current.json
```

Rules:

- durable storage is namespaced first by publishing `owner_node_key`, then by produce `slot`
- the storage/currentness identity is `(owner_node_key, slot)`, not `slot` alone across the whole task
- each committed durable publication creates one new immutable versioned file
- the filename stem is the slot id
- insert the version label immediately before the extension: `<slot>.vNN.<ext>`
- if there is no extension, use `<slot>.vNN`
- `vNN` is a derived filename/display convention from canonical integer `version`; it is not a separate stored metadata field
- never overwrite an earlier durable version file
- never use mutable durable-body aliases such as `<slot>.md`, `<slot>.latest.md`, or `<slot>.current.md`
- `current.json` is the explicit current pointer for the slot; it is not the artifact body

## Compact ordinary artifact ref contract

Ordinary manifests, assignments, checkpoints, and prompt renders should surface only the compact artifact evidence form:

```yaml
evidence_ref:
    kind: artifact
    slot: string
    version: integer
    path: string
    description: string
```

Rules:

- use `path`, not `url` or `uri`
- runtime must localize any external resource into the task root before surfacing it to agents
- `version` is the canonical machine field; `vNN` is only a derived display or filename convention
- `path` is the exact readable local file path the agent should inspect
- `description` is required; agents must not infer meaning from filenames alone
- ordinary prompt rendering should not inline full current-pointer internals or controller-only lineage metadata
- exact assignment/checkpoint field semantics are owned by [Assignment contract](assignment-contract.md) and [Checkpoint contract](checkpoint-contract.md)

## Description ownership by ref kind

Description ownership is explicit. Do not fall back to filename guesswork or ad hoc agent prose.

Rules:

- `node_runtime_file_ref.description` and `support_runtime_file_ref.description` are controller-generated wording that says why that exact runtime file matters now
- `artifact.description` comes from the authored produce-slot meaning only
- `criteria.description` inherits its base meaning from the authored criteria declaration
- `doc.description` comes from a curated file title or controller-curated catalog label
- `wiki.description` comes from the curated wiki page title
- `transient.description` comes from explicit transient surfacing text in assignment, checkpoint, or transient publication, never from filename guesswork

## Immutable publication metadata

Every committed durable publication must record, at minimum:

- `owner_node_key`
- `slot`
- `version`
- `path`
- `description`
- `assignment_key`
- `attempt_id`
- `published_at`
- prior published path superseded by this publication, if any

Controller/runtime may also keep richer internal metadata such as:

- internal artifact id
- content hash
- media type
- renderer metadata

Those internal fields are not part of the ordinary surfaced artifact-ref contract.

## Explicit current pointer

Runtime owns durable artifact currentness through one explicit current pointer per `(owner_node_key, slot)` pair.

Recommended generated file:

```yaml
artifact_current_pointer:
    owner_node_key: investigate_issue
    slot: findings_report
    current_version: 2
    current_path: C:/tasks/task_2026_0042/outputs/artifacts/investigate_issue/findings_report/findings_report.v02.md
    description: Current durable findings report for this slot.
    assignment_key: investigate_issue.assign-01
    attempt_id: attempt.investigate_issue.02
    published_at: 2026-04-30T00:18:42Z
    supersedes_path: C:/tasks/task_2026_0042/outputs/artifacts/investigate_issue/findings_report/findings_report.v01.md
```

Rules:

- `current.json` is a persisted runtime surface; do not replace it with prompt-only wrapping
- `current.json` is the authoritative currentness projection for one durable `(owner_node_key, slot)` pair
- advancing currentness is an explicit controller mutation
- currentness must not be inferred from filename ordering, mtime, prompt prose, or provider chronology
- if publication fails or is partial, currentness must not advance
- once currentness advances, the pointer must reference a real immutable versioned file
- if `artifact-index.json`, checkpoint prose, and `current.json` disagree about what is current now, controller/DB state plus `current.json` win

## Attempt-local artifact index

The current attempt may also have an attempt-local publication ledger:

```text
_runtime/
  attempts/
    <attempt_id>/
      artifact-index.json
```

Recommended shape:

```yaml
artifact_index:
    attempt_id: attempt.investigate_issue.02
    node_key: investigate_issue
    assignment_key: investigate_issue.assign-01
    publications:
        - owner_node_key: investigate_issue
          slot: findings_report
          version: 2
          path: C:/tasks/task_2026_0042/outputs/artifacts/investigate_issue/findings_report/findings_report.v02.md
          description: Findings for downstream implementation.
          published_at: 2026-04-30T00:18:42Z
          became_current: true
```

Rules:

- `artifact-index.json` is attempt-local historical publication evidence
- it is not the authoritative currentness owner
- it is not a whole-slot history owner across attempts
- it answers which durable artifacts this attempt published and which exact versioned paths later readers should inspect

## Publication algorithm

Freeze this controller-side sequence:

1. validate that the publish targets a legal durable slot for the current node/assignment
2. allocate the next `version` for that `(owner_node_key, slot)` pair
3. persist publication metadata linking slot, relational node ownership, assignment, and attempt
4. advance `artifact_current_pointers`
5. commit the authoritative artifact/currentness rows
6. after commit, materialize the immutable versioned file under `outputs/artifacts/<owner_node_key>/<slot>/`
7. regenerate `outputs/artifacts/<owner_node_key>/<slot>/current.json`
8. regenerate `_runtime/attempts/<attempt_id>/artifact-index.json`
9. surface the exact published version through checkpoint, manifest, and later assignment refs when relevant

Atomicity rule:

- advancing the explicit current pointer is illegal unless the authoritative publication metadata commit succeeded first
- later agents must be able to trust that the surfaced version/path points to a real immutable file

## Assignment pinning and read rules

Currentness selection and attempt consumption remain separate.

Rules:

- the controller may use the current pointer when resolving authored `consumes` during assignment materialization
- when a parent/root turn depends on child durable publications, the controller may also surface the exact current child artifact refs from those current pointers in manifest `current_relevant_paths` and prompt `consumed_durable_refs`
- that artifact surfacing does not choose `current_context.latest_relevant_checkpoint_path`; checkpoint handoff stays a separate controller-selected field and must not be inferred from artifact or checkpoint list order
- once an assignment is minted, it must pin exact concrete versioned refs
- a later currentness advance must not silently mutate an already minted assignment, and the older pinned artifact ref remains valid if the surfaced file still exists
- nodes should read the exact surfaced versioned paths from assignment and checkpoint files, not rescan artifact folders guessing what is current
- this version does not reject an already surfaced artifact ref solely because the slot's current pointer later advanced; broader pointer-freshness enforcement is a later currentness-security design, not a release/boundary precondition in this model

See [Assignment contract](assignment-contract.md) for the semantic selector rules that apply before those exact refs are pinned.

This is the critical split:

- currentness is a controller selection input
- concrete versioned refs are the attempt's consumed truth

## Durable artifact versus transient versus checkpoint versus support-runtime ref

These surfaces must not drift together:

| Surface                    | Exact meaning                                                                              | Must not be confused with                                  |
| -------------------------- | ------------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| durable artifact           | immutable published output or durable evidence body                                        | workspace scratch, transient carryover, checkpoint summary |
| `current.json`             | explicit controller-owned current pointer for one durable `(owner_node_key, slot)` pair    | artifact body, release decision, or operator suggestion    |
| `artifact-index.json`      | attempt-local artifact publication ledger                                                  | whole-slot history, currentness owner, assignment          |
| transient ref              | explicit optional carryover under `tmp/transfers/`                                         | durable output                                             |
| checkpoint                 | durable attempt summary of what happened and what should happen next                       | artifact body or transient file                            |
| `support_runtime_file_ref` | observability-only runtime file ref for delivery, continuity, watchdog, or provider events | ordinary node-visible artifact or checkpoint evidence      |

Rules:

- checkpoints summarize and point; durable artifacts carry durable body content
- transient files may help later work, but they are not durable truth
- transient surfacing has no authoritative current-pointer file
- observability-only runtime refs stay on observability/operator surfaces and do not become ordinary runtime context
- currentness of durable artifacts does not imply review acceptance, criteria satisfaction, or release readiness

## Object-store and remote-resource rule

This contract is local-path first.

If an implementation also mirrors artifacts to object storage or a remote backend, that is additional infrastructure detail.

What remains canonical in v1 is:

- local materialized versioned file under the task root
- local persisted current pointer
- local path-only surfaced refs

Do not make object-store identifiers, remote URLs, or `storage_uri` the primary agent-visible truth surface.

## Related contracts

- [Runtime database and object contract](runtime-database-and-object-contract.md)
- [Task root layout and generated files](task-root-layout-and-generated-files.md)
- [Manifest contract](manifest-contract.md)
- [Assignment contract](assignment-contract.md)
- [Checkpoint contract](checkpoint-contract.md)
- [Worker context contract](worker-context-contract.md)
- [Filesystem layout and roots](filesystem-layout-and-roots.md)
- [Runtime records and lifecycle](runtime-records-and-lifecycle.md)
