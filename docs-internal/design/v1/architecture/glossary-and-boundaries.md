# Glossary And Boundaries

Status: Reference

This page is the compact reference for live v1 runtime vocabulary, public boundaries, ref families, and removed terms.

## Core Rule

- controller/DB state owns runtime truth
- manifest, assignment, checkpoint, artifact-currentness projections, and observability projections are derived surfaces over that truth
- observability projections are not ordinary node-visible runtime context

## Public Boundaries

| Boundary   | Direction                 | Exact meaning                                                                                          |
| ---------- | ------------------------- | ------------------------------------------------------------------------------------------------------ |
| `dispatch` | controller -> node        | Ingress turn for exactly one current node.                                                             |
| `yield`    | parent/root -> controller | Non-terminal closure of the current dispatch after exactly one continuation outcome is already staged. |
| `green`    | node -> controller        | Terminal success of the current assignment and attempt.                                                |
| `retry`    | node -> controller        | Terminal request for a new attempt on the same assignment.                                             |
| `blocked`  | node -> controller        | Terminal inability to complete the current assignment as assigned.                                     |

Rules:

- `yield` is boundary-only; it is never a checkpoint outcome
- tool success does not close a dispatch
- worker and leaf nodes normally close with `green`, `retry`, or `blocked`
- parent/root nodes normally use `yield` for non-terminal closure

## Parent/Root Control Tools

Use `tool` as the canonical runtime term. Use `plugin` only for adapter-specific or OpenClaw-specific surfaces.

| Tool              | Exact meaning                                                           |
| ----------------- | ----------------------------------------------------------------------- |
| `assign_child`    | Stage one fresh child assignment as the next continuation outcome.      |
| `add_child`       | Add one new child under a parent inside the current owned subtree.      |
| `update_child`    | Update one descendant node in place while preserving identity.          |
| `remove_child`    | Remove one descendant node and its owned subtree.                       |
| `release_green`   | Commit upward green release readiness for the current parent/root node. |
| `release_blocked` | Root-only commit of whole-flow terminal blocked state.                  |

## Canonical Runtime Terms

| Term                       | Exact meaning                                                                                                  |
| -------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `task`                     | Durable top-level user or business unit of work.                                                               |
| workflow definition YAML   | Hidden authored source material. Nodes do not read it directly.                                                |
| workflow manifest          | Controller-generated rendered workflow contract the node sees.                                                 |
| `node`                     | One structural workflow unit.                                                                                  |
| parent/root node           | Node that may use control tools during an open dispatch.                                                       |
| worker/leaf node           | Node that normally executes the current assignment and closes with `green`, `retry`, or `blocked`.             |
| `assignment`               | Forward-looking mission contract for one node.                                                                 |
| `attempt`                  | One execution try of one assignment.                                                                           |
| `checkpoint`               | Durable summary of what happened and what should happen next.                                                  |
| `criteria`                 | Explicit acceptance or constraint refs for the current assignment.                                             |
| `consumes`                 | Must-read durable refs surfaced for the current assignment now.                                                |
| `produces`                 | Durable outputs required for `green`.                                                                          |
| artifact                   | Durable published output or durable evidence.                                                                  |
| `transient_refs`           | Optional explicit carryover only. Not durable truth.                                                           |
| `support_runtime_file_ref` | Shared observability-only runtime file ref for delivery, continuity, watchdog, and provider-event projections. |
| observability lane         | Operator-facing monitoring lane for dispatch delivery, continuity, watchdog, and provider-event reads.         |

## Runtime Ref And Filesystem Terms

| Term                                 | Exact meaning                                                                             |
| ------------------------------------ | ----------------------------------------------------------------------------------------- |
| `workspace/`                         | Mutable work in progress for the current assignment.                                      |
| `_runtime/criteria/`                 | Controller-generated explicit criteria projections.                                       |
| `context/wiki/`                      | Curated reference pages and synthesized reusable notes.                                  |
| other curated files under `context/` | Source or reference material such as docs, PDFs, screenshots, and notes.                  |
| `outputs/artifacts/`                 | Durable published outputs and evidence.                                                   |
| `tmp/transfers/`                     | Optional transient carryover.                                                             |
| `_runtime/attempts/<attempt_id>/`    | Deterministic controller-generated assignment and checkpoint projections for one attempt. |
| `_runtime/dispatch/<dispatch_id>/`   | Deterministic controller-generated observability projections for one dispatch.            |

Ref rules:

- surfaced runtime and evidence refs stay path-first and compact
- `support_runtime_file_ref` is legal on observability/operator carriers only
- nodes do not learn task meaning by scanning `_runtime/dispatch/`
- if a transport incident matters durably, bridge it into checkpoint or surfaced refs

## Assignment, Attempt, Checkpoint, And Recovery Rules

- parent -> child context comes from assignment
- child -> parent, parent -> parent, and same-node retry context comes from checkpoint
- retry is node-self only:
    - same assignment
    - new attempt
    - full prompt
    - prior terminal checkpoint as durable handover
- controller recovery actions are `redispatch_same_attempt`, semantic `create_new_attempt`, and `escalate`
- any retained `same_session_continue` detail is current/debt transport compatibility only and not the live redispatch model
- progress checkpoints use `checkpoint_kind: progress` with `outcome: null`
- terminal checkpoints use `checkpoint_kind: terminal` with `outcome: green | retry | blocked`

## Removed From Live V1 Vocabulary

Do not use these as live canonical runtime terms:

- `parent_gate`
- `BoundaryAction`
- `scope_key`
- operator parity lane
- generic support lane naming for observability
- bundle or handoff vocabulary as the live context model
- flow or scope manifest split vocabulary
- old child retry or reassignment verbs
