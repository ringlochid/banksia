# ADR-0006: revision-safe replan and adopt

Status: Accepted

## Decision summary

Runtime structural change is adopt-based, revision-safe, and validator-checked. It does not hot-mutate current truth in place and does not re-run the launch compiler.

## Context

Runtime structural change must preserve legality, currentness, and auditability without hot-mutating the active graph in place.

The live v1 model also distinguishes launch-time compiler work from runtime structural CRUD on already-running truth.

## Decision

Runtime structural change is revision-safe adopt, not in-place mutation.

Structural CRUD must flow through:

1. build the candidate change against current controller truth
2. validate authority, currentness, role/policy compatibility, and candidate-graph dependency legality
3. commit/adopt one new active structural revision atomically
4. regenerate stable runtime projections through the materializer/projector

The validator must prove dependency legality on the candidate adopted graph before commit.

Every successful structural edit creates a new active structural revision. Older revisions remain auditable and must not silently regain currentness.

This runtime CRUD path does not invoke the launch compiler.

## Historical contrast

This ADR rejects two older shortcuts:

- mutating the active graph in place without explicit revision adopt
- treating runtime replan as a hidden compile step

The live path is:

1. build candidate change against current truth
2. validate
3. atomically adopt a new active structural revision
4. regenerate projections

## Consequences

- stale-base structural adoption fails closed instead of silently overwriting newer truth
- structural history remains queryable for operator inspection and recovery work
- manifest and other generated files are projections of already adopted truth, not proposal files waiting for acceptance
- legality, adoption, and projection regeneration can be reasoned about as separate controller responsibilities

## Search keywords

- revision-safe replan
- structural adopt
- Kahn topological sort
- stale revision
- runtime CRUD not compiler
- materializer projector

Canonical references:

- `../design/v1/architecture/runtime-boundary-and-controller-loop-contract.md`
- `../design/v1/architecture/runtime-records-and-lifecycle.md`
- `../design/v1/architecture/runtime-database-and-object-contract.md`
- `../design/v1/architecture/manifest-contract.md`
