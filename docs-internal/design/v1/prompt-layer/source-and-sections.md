# Prompt Source And Sections

Status: Target

This page defines prompt source provenance, stable section ids, and the section contracts for the frozen v1 prompt layer.

## Source Surfaces

Shipped exact prompt blocks are app-owned assets under `apps/api/src/autoclaw/runtime/prompt/assets/`. The prompt-pack docs in this folder mirror those assets for review, routing, and validator-backed drift detection.

| Source surface                                       | Canonical fields                                                                                                                                                                                                                                                                      | Rendered destination                                                                                                              |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| controller/runtime rule pack                         | boundary model, `AssignChildPayload` semantics, `record_checkpoint` handoff model, durable-vs-transient rules, filesystem rules                                                                                                                                                       | `operating_model`, `allowed_actions_now`, `publication_rule`                                                                      |
| `_runtime/workflow-manifest.*`                       | task identity, current node purpose, whole-workflow structure, filesystem path bindings, current surfaced paths                                                                                                                                                                       | `task_identity`, `node_purpose`, `workflow_manifest`, and AutoClaw-owned current-node instruction assembly                        |
| internal dispatch/session state                      | current bound turn, caller node kind, live controller send mode, closure expectations                                                                                                                                                                                                 | `current_dispatch`, `capabilities_now`, `allowed_actions_now`                                                                     |
| current semantic assignment handoff                  | `summary`, optional `instruction`, reduced `criteria`, reduced `consumes`, `produces` requirements, explicit `transient_refs`                                                                                                                                                         | `current_assignment`, part of `publication_rule`                                                                                  |
| `_runtime/attempts/<attempt_id>/latest-checkpoint.*` | `checkpoint_kind`, `outcome`, `summary`, `next_step`, `blockers`, `risks`, surfaced refs                                                                                                                                                                                              | `latest_checkpoint_context`, `boundary_followup_guidance`                                                                         |
| runtime-resolved durable refs                        | exact current criteria, checkpoint, artifact, doc, and wiki refs surfaced for this turn                                                                                                                                                                                               | `consumed_durable_refs`                                                                                                           |
| surfaced transient refs                              | explicit transient carryover paths                                                                                                                                                                                                                                                    | `transient_refs`                                                                                                                  |
| surfaced role/policy guidance for structural edits   | current node role/policy descriptions and instructions, plus the compact registry-backed `structural_edit_palette` of currently valid role/policy names for structural edits and optional current-only definition lookup availability when that read-only escalation lane is surfaced | AutoClaw-owned `instructions_text`, `workflow_manifest`, and `allowed_actions_now` when parent/root structural edits are relevant |

## Section Contracts

### `operating_model`

This section must teach:

- controller/DB truth versus generated projections
- `dispatch` ingress, `record_checkpoint` durable publication, and `yield | green | retry | blocked` egress
- parent/root tools versus worker/leaf terminal outcomes
- semantic assignment handoff versus runtime-resolved durable refs
- monitoring files are not normal assignment truth

### `task_identity`

This section must expose:

- `task_id` or `task_key`
- task title when present
- task summary from the manifest
- optional task instruction from the manifest

Rules:

- task identity is task-wide and visible to every node
- it is not root-only metadata
- the first/root assignment may be generated from task identity plus current node purpose and node instruction, but task identity itself remains separate from assignment prose

### `node_purpose`

This section must expose:

- `node_key`
- node kind
- role
- current node description from the manifest
- optional current node instruction from the manifest

Rules:

- the current node purpose and optional node instruction also belong in the AutoClaw-owned instruction layer for every node
- this section is a short visible runtime echo, not the only place node purpose is taught

### `current_dispatch`

This section must expose:

- that this prompt is for the current bound turn of the current node
- send mode, which is `full_prompt` in the live v1 contract
- whether the current node is worker/leaf or parent/root
- non-terminal versus terminal closure expectation
- `task_id` for v1 static node-MCP tool calls
- `session_key` for v1 static node-MCP tool calls
- one exact instruction: “When calling node tools, include the exact `task_id` and `session_key` shown here. Do not print them in normal output, checkpoint prose, or artifacts.”

Internal route ids such as `dispatch_id` may exist in transport or persistence, but they are not part of the canonical node-facing prompt section. Stable manifest, assignment, and checkpoint projections must not carry `session_key` or this tool-call context; it is dispatch-local only.

The live target section contract does not preserve a second send-mode-specific section variant.

### `capabilities_now`

This section must expose controller-derived effective capability truth for the current dispatch:

- execution scope
- whether human request kinds are allowed or denied
- whether command-run is allowed or denied
- denial reason and next legal action when a capability is denied

Rules:

- omitted or denied capabilities render explicitly rather than disappearing
- adapter, UI, or local-tool restrictions may narrow but must not widen controller-owned capability truth
- this section explains capability authority; it does not replace `allowed_actions_now`
- capability-use instruction overlays render separately only when an effective capability family is allowed: human-request guidance and command-run guidance are independent

### `workflow_manifest`

This section must expose:

- stable manifest path
- short description that this is the whole-workflow visible contract
- current node anchor in that manifest
- compact `structural_edit_palette` entries when the current node is `root` or `parent`
- the compact `structural_edit_palette` as the default surfaced discovery lane for structural edits
- current relevant surfaced paths when they matter to orientation

### `current_assignment`

This section must expose the semantic assignment handoff only:

- stable assignment path
- `summary`
- `instruction`
- `criteria`
- `consumes`
- `produces`
- `transient_refs`

Rules:

- `assignment_path` points at the current deterministic assignment projection for the turn.
- `summary` plus optional `instruction` are the node-authored handoff prose
- for the first/root assignment, runtime/system generates `summary` and `instruction` from task identity plus current node purpose, node instruction, and resolved role/policy wording
- parent/root child-assignment staging should treat `instruction` as an acquisition plan that tells the child what to read first, what to compare, what evidence to return, and what not to touch
- `criteria` and `consumes` render reduced durable claims only
- `produces` render requirements only
- exact `path` or `version` metadata for durable refs does not belong here
- final published durable ref metadata does not belong here
- reduced criteria claims still keep `kind: criteria`

Render like:

```text
### Current Assignment
- path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.implement_fix.11/assignment.md
- summary: repair the auth-refresh defect and publish the required evidence
- instruction: keep the fix scoped to the surfaced evidence and close only after the required outputs exist
- criteria:
  - kind: criteria
    slot: fix_acceptance
    description: bounded implementation acceptance criteria
- consumes:
  - kind: checkpoint
    description: upstream investigation handoff for the current fix
  - kind: artifact
    slot: findings_report
    description: current findings the fix must satisfy
- produces:
  - slot: patch
    description: bounded code change artifact required before green
  - slot: verification_report
    description: scoped verification evidence required before green
- transient_refs:
  - path: C:/tasks/task_2026_0042/tmp/transfers/implement_fix/repro-commands.txt
    description: optional transient repro commands from the prior attempt
```

### `latest_checkpoint_context`

This section must expose the durable handoff published through `record_checkpoint`:

- `path`, rendered from `latest_relevant_checkpoint_path` when present and otherwise from `latest_checkpoint_path`
- `checkpoint_kind`
- `outcome`
- `summary`
- `next_step`
- `blockers` when present
- `risks` when present
- `produced_artifacts` when present
- `transient_refs` when present

It must not teach `yield` as a checkpoint outcome. It must not teach or surface `control_effects`.

If there is no current relevant checkpoint yet, the section should say so explicitly rather than implying the worker should discover one by directory scan. This section must not silently rewrite the manifest's `latest_checkpoint_path`; current-attempt checkpoint truth and surfaced relevant-checkpoint handoff stay split. If `path` resolves from `latest_relevant_checkpoint_path`, that same checkpoint path should not be repeated in `consumed_durable_refs`. Do not infer `latest_relevant_checkpoint_path` by scanning other surfaced checkpoints in `current_relevant_paths`; that path comes only from controller-selected truth already projected into the manifest.

### `boundary_followup_guidance`

This section must interpret why this dispatch exists now from current checkpoint outcome and node kind:

- no terminal outcome means initial or ordinary current dispatch
- `retry` means same assignment, new attempt, prior terminal checkpoint as handoff, and no hidden session-memory dependency
- worker `blocked` means resolve the blocker only if current assignment and refs provide a lawful path forward
- parent/root `blocked` means routing input, not automatic whole-flow failure
- parent/root `green` means child evidence to inspect, not automatic release authority

Rules:

- this section does not create new prompt families
- it must direct parent/root toward sharper reassignment, specialist review, structural replan, release, or current-node blocked closure from current evidence
- it must preserve root-only `release_blocked` for whole-flow blocked closure

### `consumed_durable_refs`

This section must expose the exact current durable refs the runtime resolved for the current turn from the union of:

- assignment `criteria`
- assignment `consumes`
- manifest `current_relevant_paths`

Rules:

- de-duplicate repeated durable refs before rendering
- omit any `kind: transient` entry from this section
- omit the checkpoint path already rendered in `latest_checkpoint_context`
- keep `kind` on non-artifact refs and `version` only where the live ref contract allows it
- worker prompts render an explicit empty state when no durable refs are surfaced for the turn
- parent/root prompts may omit the section when no durable refs are surfaced for the turn
- parent/root release rereads may surface controller-staged descendant checkpoint and artifact refs here even when those refs are not limited to the current direct-child set

These refs are path-only in v1 and must include descriptions. This is where final durable ref metadata belongs in the prompt.

### `transient_refs`

This section must expose only explicitly surfaced transient carryover for the current assignment.

It must teach that these refs are optional and not durable truth.

### `allowed_actions_now`

This section must expose the bounded next-action surface that is legal now:

- parent/root control tools during an open parent/root dispatch
- bounded research aimed at better child assignment or release and routing decisions
- `record_checkpoint` when the handoff must survive redispatch
- `yield` for non-terminal parent/root closure after exactly one staged child assignment exists
- `green | blocked` for parent/root terminal closure when justified, with root-only `release_blocked` required only for whole-flow blocked closure
- `green | retry | blocked` for worker/leaf terminal closure when justified
- callback is a write-only semantic lane and not a context-discovery mechanism

When structural edits are in scope, this section should also teach:

- research only enough to understand the task, choose the right refs, and tighten the next child brief
- research is for better delegation quality, not for quietly doing the child task in place
- child briefs should be specific about objective, boundaries, key refs, what to read or compare before acting, what evidence to return, and what not to touch
- reread the current manifest first
- start with role/policy names from the surfaced `structural_edit_palette` in the current prompt or manifest
- if the needed current role/policy choice is still not surfaced and current-only definition lookup tools are surfaced for the current dispatch, use that read-only lookup lane before guessing
- definition revision history, upload proof, and registry provenance remain operator-only and are not normal dispatched planning inputs
- reread the regenerated manifest after `add_child`, `update_child`, or `remove_child` before deciding whether one child assignment should be staged
- if a required rule or path is still unclear after reread and hinted search, do not guess

Render like:

```text
## Allowed Actions Now
- tools:
  - assign_child
  - add_child
  - update_child
  - remove_child
  - release_green
  - release_blocked (root only)
  - record_checkpoint
- do bounded research to sharpen delegation, then turn that into a tighter child brief plus the right surfaced refs
- emit `yield` only after exactly one staged child assignment already exists
- start structural edits from surfaced role/policy names, and if the palette is still insufficient, use the current-only definition lookup lane before the edit
- do not use definition revision history, upload proof, or registry provenance as dispatched planning input; reread the regenerated manifest after the edit
- emit `green` only when this parent/root node itself is closing its own assignment; emit `blocked` only after this node cannot complete its current assignment and has published a terminal blocked checkpoint; root whole-flow blocked closure also requires committed `release_blocked`
```

### `publication_rule`

This section must teach:

- `produces` are requirements that gate `green`
- runtime authors final durable publication metadata after those requirements are satisfied
- ordinary prompt surfaces use compact artifact refs only
- later agents learn what happened from checkpoint plus surfaced refs, not from session memory

## Runtime-private execution plumbing

The following are not canonical prompt sections and must not be rendered into prompt-visible semantic context:

- callback auth token values
- callback env var names
- callback auth-file paths
- private dispatch-binding envelopes
- host-process secret plumbing
- hidden header/plugin injection as the canonical v1 node-MCP path

## Removed From The Live Section Model

- `task_launch_instructions`
- `workflow_and_node_purpose`
- `current_task_state`
- `resource_access_and_write_targets`
- `required_inputs_and_materialized_refs`
- `handoff_and_evidence_summary`
- checkpoint `control_effects`

## Related Contracts

- [Prompt contract](contract.md)
- [Prompt machine contract](machine-contract.md)
- [Rendered examples](generated/rendered-examples.md)
