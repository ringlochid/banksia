# Release and install strategy

During WP-09, the root Python distribution is a backend-only migration artifact. Build one wheel and one source distribution from `pyproject.toml` for package proof:

```bash
./.venv/bin/python -m build
```

The wheel must contain the backend, Starter Workflow seeds, prompt instruction assets, and systemd user-service template. It must not contain the imported migration-baseline Console. Verify it from a clean environment outside the repository without `PYTHONPATH`.

This interim artifact is not publishable. WP-10 must add the independently authored root Console and restore a single integrated release build before Banksia has a release artifact.

For a built artifact, the Linux helper can install into a dedicated virtual environment and user service:

```bash
scripts/install-systemd-user.sh --wheel dist/banksia_ai-*.whl --no-start
```

`--no-start` is the safe release-proof path. Starting a real user service is a separate operator action.

SQLite is included by default. PostgreSQL requires the `postgres` extra and an explicit database URL. Installing the extra does not select or create PostgreSQL automatically.

After the integrated surface exists, publish only immutable versioned artifacts from the root package surface.
