# Prepare a release

Release-ready means code, docs, examples, package data, install behavior, and the required proof lanes agree.

## Before the build

- Confirm the version and release scope.
- Check that public docs describe only shipped behavior.
- Regenerate prompt or console outputs when their inputs changed.
- Select focused unit, integration, DB, browser, and workflow lanes from the changed surfaces.

## Build and verify

```bash
make package-build
./.venv/bin/python scripts/testing/verify_installed_distribution.py \
  --dist-dir dist \
  --workspace /tmp/autoclaw-installed-proof
make check-docs
```

Also run `make check-api`, `make check-console`, and every applicable focused test lane. Use `make test-api-db` for schema, reset, or PostgreSQL changes. Use `make console-e2e-real` when browser behavior depends on the real backend.

Inspect the wheel and source distribution before publishing. Do not mutate an already published artifact; publish a new version for a fix.

## After publication

Install the published artifact in a clean environment outside the checkout. Check `autoclaw --version`, passive status, initialization, service installation with no start, and health/readiness when the service is intentionally started.
