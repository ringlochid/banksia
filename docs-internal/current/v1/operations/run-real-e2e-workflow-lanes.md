# Run real workflow lanes

Status: Current

Last verified: 2026-07-19

The workflow end-to-end suite has three focused lanes. Each uses real SQLite controller records. The bounded lane starts from the shipped task-start service; the other lanes exercise the exact runtime operations named below.

## Bounded workflow

```bash
make test-api-e2e-bounded
```

This proves registry compilation, immutable launch-revision pinning, task start, root-dispatch opening, provider acceptance, and one managed Node MCP binding with its exact tool allowlist.

## Reviewed workflow

```bash
make test-api-e2e-reviewed
```

This proves parent-to-child assignment, role-scoped tools, child completion, parent resumption, release, and final flow completion.

## Staged workflow

```bash
make test-api-e2e-staged
```

This proves that a human wait excludes watchdog recovery, an answer opens one successor, one stale open dispatch gets a watchdog replacement, and a duplicate deadline signal loses without another replacement.

Focused runtime integration tests own command exit, cancellation, timeout, reap, restart ownership loss, and watchdog replacement-cap behavior. This staged lane does not duplicate those cases.

## Browser with real backend

```bash
make console-e2e-real
```

This builds packaged console assets and lets Playwright own a disposable AutoClaw backend. The smoke reads stored definitions, starts a task, performs guarded pause and cancel mutations, reads their SSE events, checks cursor reset, and verifies loopback Host/Origin admission without a browser API key.

## Verification

`make test-api-e2e` runs all three backend workflow lanes. During iteration, run only the lane that owns the change. A passing unit test or mocked transport is not a substitute for these controller-path checks.

The exact grouped paths are declared in `scripts/testing/run_api_pytest_groups.sh`.
