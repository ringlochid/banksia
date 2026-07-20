# Test structure standard

Status: Reference

Use this guide when adding tests, reorganizing test trees, or deciding what counts as acceptable proof for a touched slice.

## Goals

- each lane should prove one clear level of behavior
- shipped persistence and runtime truth should be exercised through shipped paths
- evidence should be easy to audit and hard to fake

## Lane ownership

- `make test-api` and `make test-api-unit`: unit behavior under `apps/api/tests/unit`
- `make test-api-integration`: canonical repo-native SQLite and runtime-template integration behavior
- `make test-api-integration-local`: compatibility alias for the same local integration lane
- `make test-api-db`: specialized Docker/Postgres-backed integration behavior using shipped schema/setup paths
- `make test-api-e2e-bounded|reviewed|staged`: progressive end-to-end behavior
- `make console-test`: frontend unit and component behavior under `apps/console/tests/unit` and `apps/console/tests/component`
- `make console-test-integration`: MSW-backed frontend flow behavior under `apps/console/tests/integration`
- `make console-e2e`: browser end-to-end behavior under `apps/console/tests/e2e`
- `make console-e2e-real`: focused browser behavior against a disposable real AutoClaw backend
- `make console-openapi-check`: generated frontend API type drift against the current FastAPI OpenAPI schema

## Placement rules

- put pure unit behavior in `apps/api/tests/unit/**`
- put local integration flows in `apps/api/tests/integration/**`
- put end-to-end workflow and public-surface behavior in `apps/api/tests/e2e/**`
- keep reusable helpers under `apps/api/tests/helpers/**` and keep them support-only
- put frontend mapper, reducer, API helper, and small state-machine tests in `apps/console/tests/unit/**`
- put frontend primitive and feature component tests in `apps/console/tests/component/**`
- put MSW-backed browser-flow tests in `apps/console/tests/integration/**`
- put Playwright page-flow and accessibility checks in `apps/console/tests/e2e/**`
- put screenshot/parity fixtures and visual audit helpers in `apps/console/tests/visual/**`
- put reusable API-shaped frontend fixtures in `apps/console/tests/fixtures/**`

## Steady-state test tree

Phase-numbered test trees are transitional only.

The steady-state layout should converge toward feature-, boundary-, or product-owned folders beneath each main lane.

Preferred direction:

```text
apps/api/tests/
  unit/
    cli/
    compiler/
    registry/
    runtime/
    integrations/
    schemas/
  integration/
    api/
    cli/
    db/
    registry/
    runtime/
    integrations/
  e2e/
    workflows/
    gateway/
    operator/
    onboarding/
```

For console frontend tests, use app-local proof lanes:

```text
apps/console/tests/
  unit/
    api/
    mappers/
    reducers/
    view-models/
  component/
    ui/
    layout/
    features/
  integration/
    tasks/
    task-detail/
    human-requests/
    command-runs/
    definitions/
    definition-editor/
    task-start/
  e2e/
    runtime/
    authoring/
  visual/
  fixtures/
```

Rules:

- keep the top-level lanes `unit`, `integration`, and `e2e`
- beneath those lanes, prefer product or feature ownership over redesign-phase history
- use provider or integration subfolders only when the external boundary is a real owner surface
- phase history is not the long-term primary source of test ownership
- when migrating an old phase-owned test family, keep the new feature-owned location authoritative and reduce the old phase bucket to a temporary compatibility path

## Proof rules

- do not use mocks as the primary proof for shipped persistence, runtime truth, or public API/CLI behavior
- do not manually install missing schema or synthesize missing setup paths inside tests and then treat that as install or runtime proof
- if the behavior reaches a public route, public CLI noun family, end-to-end workflow, or support-state readback, use the lane that exercises that surface for real
- once a progressive e2e lane becomes viable for a surface, later work should keep it green
- use `make test-api-integration` as the default final-proof integration lane
- reserve `make test-api-db` for Docker/Postgres-specific proof such as schema/reset coverage, DB-shell changes, or Postgres-only behavior
- frontend MSW tests may prove rendering, state transitions, and API-client behavior, but they do not prove backend persistence, runtime legality, or route implementation
- frontend API fixtures must be generated or hand-shaped from OpenAPI/current contracts and must stay visibly fake
- frontend e2e must use real browser behavior for navigation, focus, disclosure, forms, SSE-facing flows, and responsive layout when those surfaces changed
- visual parity checks should compare against accepted design screenshots or fixture routes, not inferred layout math alone
- accessibility checks should cover shell navigation, rows, tabs, modals/drawers, forms, disclosure lists, request resolution controls, and command-run log disclosure

## Test authoring rules

- where practical, start with a failing or gap-revealing test
- keep test names aligned with the contract or behavior under proof
- keep fixture setup explicit and narrow
- avoid helper stacks that hide what state or side effect the test is actually proving
- when reorganizing tests, preserve or improve readable progress output

## Runtime wait and timing rules

- publish the exact after-commit signal owned by the test, then reread the minimum controller state that proves its result
- test duplicate and stale signals by publishing that same exact source more than once; do not build a broad runtime-drain helper
- for deadline behavior, use a controlled clock and invoke the exact due handler or scheduler boundary; do not poll provider output or wait for provider shutdown
- use bounded condition polling only when the boundary is a real child process, SSE connection, or separately managed server
- keep any direct sleep narrow and explain why a committed-state read or exact signal cannot express the proof
- do not add a generic runtime driver, watchdog driver, provider-output wait, or widened global timeout to make one test pass

## Review checklist

- did the touched slice update the right lane
- if the test tree was reorganized, did it move toward feature/domain ownership rather than deeper phase history
- does the lane exercise the shipped boundary that changed
- did any helper or fixture silently substitute for real runtime or DB behavior
- if a lane was skipped, is the exact reason written down in review or evidence
- for frontend work, did the tests cover mapper/view-model drift separately from component rendering
- for frontend work, did the test prove keyboard/focus, responsive, and a11y behavior when the touched surface is interactive or page-level
