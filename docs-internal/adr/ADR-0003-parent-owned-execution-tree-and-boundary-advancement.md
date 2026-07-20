# ADR-0003: tree-owned execution and boundary advancement

Status: Accepted

## Decision summary

The live authored model is tree-only, and runtime advancement uses explicit tools plus the public `dispatch` / `yield | green | retry | blocked` boundary set.

## Context

Older redesign materials mixed tree ownership with flat workflow language, `parent_gate` advancement, boundary subtypes, and callback-style controller decisions.

## Decision

The authored workflow model is tree-only.

Parent/root ownership comes from the workflow tree. Runtime assignment control is limited to explicit direct children, while structural replan control may target explicit descendants inside the caller's owned subtree.

The only canonical public runtime boundaries in v1 are:

- ingress: `dispatch`
- egress: `yield | green | retry | blocked`

Parent/root nodes drive continuation through explicit control tools during an open `dispatch`:

- `assign_child`
- `add_child`
- `update_child`
- `remove_child`
- `release_green`
- `release_blocked`

Tool success does not close the current dispatch.

One open parent/root dispatch may commit exactly one continuation outcome:

- one staged child assignment from `assign_child`
- one committed `release_green`
- one committed root `release_blocked`

`yield` is legal only after exactly one continuation outcome already exists for that open dispatch.

The live v1 runtime model no longer uses `parent_gate`, gate-era boundary families, callback decision envelopes, or public child retry/reassignment verbs.

## Historical contrast

This ADR removes the older gate-era mental model:

- no `parent_gate`
- no public child retry or reassignment control
- no inferred continuation from boundary subtypes
- no callback decision envelope that hides the actual control mutation

Parent/root control is now explicit enough to validate directly.

## Consequences

- authored structure, owned-subtree structural control, direct-child assignment, and runtime advancement use one consistent tree model
- parent/root continuation is explicit and validator-checkable instead of inferred from gate callbacks or boundary subtypes
- prompt, legality, monitoring, and recovery docs can normalize around the `dispatch` / checkpoint / tool / boundary split

## Search keywords

- tree-only workflow
- dispatch ingress
- yield green retry blocked
- explicit parent tools
- one continuation outcome
- removed parent gate

Canonical references:

- `../design/v1/architecture/runtime-boundary-and-controller-loop-contract.md`
- `../design/v1/architecture/runtime-records-and-lifecycle.md`
- `../design/v1/architecture/glossary-and-boundaries.md`
