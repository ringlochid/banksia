# Verify the current install and runtime

Start with read-only checks:

```bash
autoclaw --version
autoclaw status --json
autoclaw config show --json
autoclaw service status --json
```

If the service should be running, verify both endpoints:

```bash
curl --fail http://127.0.0.1:18125/healthz
curl --fail http://127.0.0.1:18125/readyz
```

Use `autoclaw providers status` for passive provider configuration and `autoclaw providers check <provider>` for an explicit live diagnostic. Do not use task start, database reset, provider login, or service restart as a status check.

For release artifact proof, run the installed-distribution verification described in [Maintain packaging](../../maintainers/maintain-packaging.md).
