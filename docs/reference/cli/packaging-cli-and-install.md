# Packaging, CLI, and install baseline

`pyproject.toml` is the distribution contract. The wheel and source distribution include the Python package, definition seeds, prompt instruction assets, built console assets, and systemd user-service template.

The installed console entry point is `autoclaw`. Runtime resource reads must use packaged resources, not repository-relative paths.

Build both artifacts with:

```bash
make package-build
```

Release proof must inspect both artifacts, install the wheel in a fresh virtual environment, run outside the repository without `PYTHONPATH`, enter application lifespan, and exercise the service installer with `--no-start` in an isolated home. See [Maintain packaging](../../maintainers/maintain-packaging.md).
