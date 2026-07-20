# Testing and release checklist

Status: Target

This page defines the frozen implementation-complete checklist for tests, package validation, release readiness, and docs parity.

## Hard rule

Release-ready means:

- code, tests, docs, and examples agree
- the required public and internal surfaces are exercised at the appropriate lane depth
- package, install, DB, and reset behavior are explicitly checked
- missing mandatory evidence blocks release

## Required evidence groups

### Unit and integration

- unit coverage for changed core logic
- integration coverage for changed runtime, DB, route, provider, CLI, package, or plugin behavior
- explicit note when a test category was not viable and why

### E2E lanes

The required workflow lanes follow the progressive lane matrix:

- bounded lane when prompt/runtime/bootstrap flow is viable
- reviewed lane when parent/review/closure flow is viable
- staged lane when multi-subtree/review/replan flow is viable

### Package, install, and DB

- package build success for the shipped package surface
- install smoke for the supported `pipx` path
- package resource presence checks for bundled console assets, definitions, migrations, and service templates
- SQLite local-smoke verification
- Postgres + Docker strong-lane verification
- reset or migration smoke when DB, package, or public-surface truth changed

### Docs and examples

- updated canonical docs for every changed contract
- updated examples for every changed canonical example contract
- regenerated prompt inventory and rendered examples when prompt-layer authorities changed
- validator pass for the canonical docs pack

## Related tracked material

- public verification commands in [root README](../../../../README.md)
- current runtime lane contrast in [Run real e2e workflow lanes](../../../current/v1/operations/run-real-e2e-workflow-lanes.md)
- repo-wide coding standards in [STYLE](../../../../STYLE.md)
