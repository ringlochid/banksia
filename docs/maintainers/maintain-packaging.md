# Maintain packaging

Use this guide when changing package data, dependencies, console assets, service resources, entry points, or versions.

## Package contract

`pyproject.toml` owns the distribution. AutoClaw requires Python 3.12 or newer and installs `autoclaw = autoclaw.interfaces.cli.main:main` from `apps/api/src`.

The distribution includes definition seeds, shared and family prompt instructions, built console assets, and the systemd user-service template. Add every new runtime resource to package data and read it through `importlib.resources` or another installed-package path.

## Build

```bash
make package-build
```

This builds the console, copies its production assets into the package tree, and builds both a wheel and source distribution. Inspect both artifacts. Clear stale build output before diagnosing missing or extra files.

## Installed proof

Run the repository verifier against the built artifacts:

```bash
./.venv/bin/python scripts/testing/verify_installed_distribution.py \
  --dist-dir dist \
  --workspace /tmp/autoclaw-installed-proof
```

The verifier installs the wheel in a fresh virtual environment, runs outside the checkout without `PYTHONPATH`, checks packaged resources, enters FastAPI lifespan, and exercises the Linux user-service installer in an isolated home with `--no-start`.

Editable installs and source-tree imports do not prove a release artifact.

## Closeout

Run `make check-api`, `make check-console`, `make check-docs`, and the runtime, database, or E2E lanes affected by the changed resource.
