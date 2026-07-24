# Prepare a release

Release-ready means code, docs, examples, package data, install behavior, and the required proof lanes agree.

## Before the build

- Confirm the version and release scope.
- Check that public docs describe only shipped behavior.
- Regenerate prompt or console outputs when their inputs changed.
- Select focused unit, integration, DB, browser, and workflow lanes from the changed surfaces.

## Build and verify

WP-09 has no releasable artifact: the imported Console has been withdrawn and the new root Console belongs to WP-10. The interim backend-only artifact can be proved, but must not be published:

```bash
./.venv/bin/python -m build
./.venv/bin/python scripts/testing/verify_installed_distribution.py \
  --dist-dir dist \
  --workspace /tmp/banksia-installed-proof
make check-docs
```

Also run `make check-backend` and every applicable focused backend lane. Use `make test-backend-db` for schema, reset, or PostgreSQL changes. The final release process must wait until WP-10 restores the root Console, its proof lanes, and one integrated candidate build.

Inspect the interim wheel and source distribution for contraction evidence only. Once the integrated release surface exists, do not mutate an already published artifact; publish a new version for a fix.

## After publication

Install the published artifact in a clean environment outside the checkout. Check `banksia --version`, passive status, initialization, service installation with no start, and health/readiness when the service is intentionally started.
