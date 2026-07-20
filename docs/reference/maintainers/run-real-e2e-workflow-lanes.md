# Run focused end-to-end lanes

The repository has three backend workflow lanes. Each uses real SQLite controller records. The bounded lane uses the shipped task-start service; the other lanes call the exact runtime operations they verify.

## Bounded

```bash
make test-api-e2e-bounded
```

Proves registry compilation, immutable launch-revision pinning, task bootstrap, root-dispatch opening, provider acceptance, and one managed Node MCP binding with its exact tool allowlist.

## Reviewed

```bash
make test-api-e2e-reviewed
```

Proves parent-to-child assignment, role-scoped tools, child completion, parent resumption, release, and final completion.

## Staged

```bash
make test-api-e2e-staged
```

Proves human-wait exclusion, answer continuation, one watchdog replacement, and a duplicate deadline signal losing without another replacement.

Focused runtime integration tests own command exit, cancellation, timeout, reap, restart ownership loss, and watchdog replacement-cap cases. This staged lane does not repeat them.

`make test-api-e2e` runs all three. During rewrite-heavy work, run only the lane that owns the change.

## Browser with real backend

```bash
make console-e2e-real
```

Playwright starts a disposable AutoClaw backend, waits for `/healthz`, runs the focused browser smoke, and stops the process. The smoke reads stored definitions, starts a task, performs guarded pause and cancel mutations, receives their SSE events, checks cursor reset, and verifies local Host/Origin admission without a browser API key. It does not contact a live provider or mutate a real user service.

The exact backend test paths live in `scripts/testing/run_api_pytest_groups.sh`. The browser server is owned by `apps/console/playwright.real-backend.config.ts` and `scripts/testing/run_console_real_backend.py`.
