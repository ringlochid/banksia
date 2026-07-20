# ADR-0002: deterministic compiler and immutable compiled plans

Status: Accepted

## Decision summary

Compiler is launch-time only. Runtime structural CRUD does not re-run the compiler; it validates, adopts, and rematerializes current runtime truth.

## Context

The system needs deterministic executable provenance from the current workflow, role, and policy revisions plus task compose.

That compiler responsibility must stay separate from later runtime mutation of already-running truth.

## Decision

The compiler is launch-time only.

It reads current definition revisions plus task compose and produces:

- a deterministic compiled plan
- immutable compiled-plan provenance
- the initial runtime graph/materialization

Runtime executes the compiled plan's materialized result, not raw authored text.

Runtime CRUD does not invoke the launch compiler.

After launch:

- validator owns semantic graph legality, role/policy compatibility, currentness, dependency legality, and evidence/release legality
- commit/adopt owns runtime truth mutation
- materializer/projector regenerates stable runtime projections such as the manifest, assignment/checkpoint files, artifact indexes, and monitoring files

## Historical contrast

This ADR removes the earlier tendency to describe every runtime structural edit as a compile step.

The live split is:

- compiler -> current definition revisions plus task compose to initial runtime graph
- validator -> legality and currentness
- commit/adopt -> truth mutation
- materializer/projector -> regenerated projections

That split is intentional and should remain easy to search for.

## Consequences

- compiler output remains deterministic and reconstructable
- launch-time provenance stays separate from runtime assignment, retry, and structural-mutation lineage
- runtime CRUD can be validated and adopted against current controller truth without pretending that every structural edit is a recompile
- prompts and agents read controller-generated projections of adopted truth, not raw authored YAML

## Search keywords

- launch-time compiler only
- runtime CRUD does not compile
- validator and materializer
- immutable compiled plan
- adopted runtime truth

Canonical references:

- `../design/v1/workflows/compiler-contract-and-launch-materialization.md`
- `../design/v1/architecture/runtime-records-and-lifecycle.md`
- `../design/v1/architecture/runtime-database-and-object-contract.md`
- `../design/v1/architecture/manifest-contract.md`
