# Maintainer verification

Repository policy and the complete command matrix live in the [repository agent contract](../../AGENTS.md). Use the smallest focused lane while iterating, then run every applicable gate before claiming a shipped boundary is complete.

Common non-mutating gates are:

```bash
make check-backend
make test-backend
make check-console
make check-docs
```

Use the integration, PostgreSQL, end-to-end, browser, and reset lanes only when the touched surface owns those contracts. Mocks do not replace real persistence or shipped public-surface proof.

Public docs under `docs/` explain the product to users. Versionless internal architecture, interface, and verification owners under `docs-internal/` define implementation truth. Frozen migration evidence is never fallback target authority.
