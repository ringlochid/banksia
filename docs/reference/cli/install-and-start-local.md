# Install and start locally

AutoClaw requires Python 3.12 or newer.

## Repository development

```bash
python3.12 -m venv .venv
.venv/bin/pip install --upgrade -e ".[dev]"
.venv/bin/autoclaw init
.venv/bin/autoclaw setup
.venv/bin/autoclaw serve
```

The terminal flow confirms local settings, asks for the primary/default provider, handles Codex/Claude subscription or API-key authentication or OpenClaw token/password authentication, checks the route, and offers additional providers. OpenClaw remains experimental; its Gateway and compatibility MCP configuration remain user-managed.

For automation, use `--non-interactive` and pass the provider explicitly:

```bash
.venv/bin/autoclaw init --non-interactive
.venv/bin/autoclaw setup --provider codex --non-interactive
.venv/bin/autoclaw providers login codex --method subscription
.venv/bin/autoclaw providers check codex
```

## Built distribution

Install a release wheel into a dedicated virtual environment. On Linux, the repository installer can create the environment and user service:

```bash
scripts/install-systemd-user.sh --wheel dist/autoclaw-*.whl
```

Use `--no-start` when installation proof must not start the service. The installer initializes config and data, installs the unit, and reports the exact paths it used.

Rerun `autoclaw service install` after upgrading to reconcile an older generated unit. It preserves the canonical config-relative provider-secret environment and restores owner-only permissions. A failed lifecycle command prints the relevant systemd detail and exact status, journal, and reconciliation commands.

## Verify

```bash
autoclaw status
autoclaw service status
curl --fail http://127.0.0.1:18125/healthz
curl --fail http://127.0.0.1:18125/readyz
```

The packaged console uses the same origin. Run `providers check <provider>` only when you want a live provider diagnostic.
