# Maintain packaging

Use this guide when changing package data, dependencies, service resources, entry points, or versions.

## Package contract

`pyproject.toml` owns the distribution. Banksia requires Python 3.12 or newer and installs `banksia = banksia.interfaces.cli.main:main` from `src`.

The WP-09 distribution includes Starter Workflow seeds, shared and family prompt instructions, and the systemd user-service template. It does not include the imported migration-baseline Console. Add every new runtime resource to package data and read it through `importlib.resources` or another installed-package path.

## Build

```bash
./.venv/bin/python -m build
```

Remove stale `build/`, `dist/`, and egg-info output first. This command builds the interim backend wheel and source distribution; inspect both artifacts. It is package-contraction proof, not a releasable Banksia candidate. WP-10 owns the independently authored root Console and the restored integrated build.

## Installed proof

Run the repository verifier against the built artifacts:

```bash
./.venv/bin/python scripts/testing/verify_installed_distribution.py \
  --dist-dir dist \
  --workspace /tmp/banksia-installed-proof
```

The verifier installs the wheel in a fresh virtual environment, runs outside the checkout without `PYTHONPATH`, checks packaged resources, enters FastAPI lifespan, starts a Task through the shipped JSON CLI while the server is live, proves semantic Task readback after restart, and exercises the Linux user-service installer in an isolated home with `--no-start`.

Editable installs and source-tree imports do not prove a release artifact.

## Closeout

Run `make check-backend`, `make check-console`, `make check-docs`, and the runtime, database, or E2E lanes affected by the changed resource.
