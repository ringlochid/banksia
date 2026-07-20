# Install and start AutoClaw locally

Status: Current

Last verified: 2026-07-19

AutoClaw needs Python 3.12 or newer.

## Install

For repository development:

```bash
python3.12 -m venv .venv
.venv/bin/pip install --upgrade -e ".[dev]"
```

For a built release, install the wheel into a dedicated virtual environment instead.

## Initialize

```bash
.venv/bin/autoclaw init
.venv/bin/autoclaw setup
.venv/bin/autoclaw providers status
```

On a terminal, `init` confirms local paths and database settings. `setup` asks for the primary/default provider, checks it, always offers the Codex/Claude subscription or API-key choice, and offers OpenClaw token or password with its route before asking whether to add providers. An existing Codex/Claude method is the method prompt default rather than an implicit selection. Selecting it opens a separate reuse confirmation; declining runs a fresh same-method login. Setup checks that a newly selected method actually became effective. OpenClaw remains selectable and default-eligible while its experimental, externally managed Gateway/MCP boundary is disclosed.

For scripts, add `--non-interactive` and provide resolved inputs. Non-interactive provider setup configures the selected route; login and checking remain explicit commands.

## Start

Run in the foreground:

```bash
.venv/bin/autoclaw serve
```

Or install the Linux user service:

```bash
.venv/bin/autoclaw service install
.venv/bin/autoclaw service status
```

Rerun `service install` after an AutoClaw upgrade to reconcile the generated unit. It always preserves the canonical config-relative provider-secret environment and enforces owner-only file permissions. The unit reads its data-directory setting from the selected TOML file rather than a second service-only override. Installation checks a new or stopped service's bind target, while a running named unit may reclaim its own configured target during reconciliation. If start fails, follow the printed `systemctl status` and `journalctl` commands; validation errors identify obsolete fields without printing their values.

The default API is `http://127.0.0.1:18125`. The packaged console is on the same origin.

## Verification

```bash
curl --fail http://127.0.0.1:18125/healthz
curl --fail http://127.0.0.1:18125/readyz
```

`readyz` must succeed before starting tasks.

Do not run `autoclaw db reset` as a routine startup command. It destroys controller runtime data and controller-owned task roots.
