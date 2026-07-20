# Release and install strategy

The root Python distribution is the release artifact. Build both wheel and source distribution from `pyproject.toml`:

```bash
make package-build
```

The wheel must contain the backend, definition seeds, prompt instruction assets, packaged console, and systemd user-service template. Verify it from a clean environment outside the repository without `PYTHONPATH`.

For a built artifact, the Linux helper can install into a dedicated virtual environment and user service:

```bash
scripts/install-systemd-user.sh --wheel dist/autoclaw-*.whl --no-start
```

`--no-start` is the safe release-proof path. Starting a real user service is a separate operator action.

SQLite is included by default. PostgreSQL requires the `postgres` extra and an explicit database URL. Installing the extra does not select or create PostgreSQL automatically.

Publish only immutable versioned artifacts from the root package surface.
