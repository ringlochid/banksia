# Run focused end-to-end lanes

The repository has three backend workflow lanes. Each uses real SQLite controller records. The bounded lane uses the shipped task-start service; the other lanes call the exact runtime operations they verify.

## Bounded

```bash
make test-backend-e2e-bounded
```

Proves registry compilation, immutable launch-revision pinning, task bootstrap, root-dispatch opening, provider acceptance, and one managed Node MCP binding with its exact tool allowlist.

## Reviewed

```bash
make test-backend-e2e-reviewed
```

Proves a recursively replanned team, nested parallel Delegation Waves, out-of-order child returns, one continuation at each local join, and the exact root Result after the lead integrates the complete team response.

## Staged

```bash
make test-backend-e2e-staged
```

Proves human-wait exclusion, answer continuation, one watchdog replacement, and a duplicate deadline signal losing without another replacement.

Focused runtime integration tests own command exit, cancellation, timeout, reap, restart ownership loss, and watchdog replacement-cap cases. This staged lane does not repeat them.

Run the three named targets separately when all progressive lanes apply. During rewrite-heavy work, run only the lane that owns the change.

The exact backend test paths live in `scripts/testing/run_backend_pytest_groups.sh`.

## Browser proof during migration

WP-09 intentionally has no supported real-backend browser lane. The imported app remains an unserved reference surface only. WP-10 owns the independently authored root Console and its real-backend browser proof.
