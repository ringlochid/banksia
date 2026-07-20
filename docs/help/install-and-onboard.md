# Install and setup problems

The interactive setup path is `autoclaw init` followed by `autoclaw setup`. The first command confirms local state. The second asks for the primary/default provider, checks it, offers supported login, and asks about additional providers.

## `autoclaw` is not found

Confirm the isolated tool installed and its executable directory is on `PATH`. For `uv`, run `uv tool update-shell` and restart the shell if needed.

## `init` fails

Check that:

- the config and data-directory paths are writable
- the selected port is valid
- the database URL is reachable
- the existing config is not being overwritten unintentionally

Rerun `autoclaw init` and choose the default `keep` action to verify existing config and database state. Use `autoclaw init --help` for explicit path and bind options. Do not select replacement or use `--force` until you understand which existing config it would replace. `init` does not reset an old database schema.

## Provider setup fails

Read the configured state, then check the exact provider:

```bash
autoclaw providers status <provider> --json
autoclaw providers check <provider> --json
```

Guided setup always offers the Codex/Claude subscription or API-key choice. If a working method is already detected, it is shown as the method default. Select it, then accept `Existing <Provider> <method> found. Use it? [Y/n]` to reuse it. Answer no to sign in again with the same method, or choose the other method to run that login directly. If a Claude API key or OpenClaw Gateway credential exists only in your current shell, setup offers to store it for the AutoClaw service before checking it again. OpenClaw setup records its resolved CLI path, asks for Gateway URL/profile and token or password, then confirms reuse of a working stored credential or asks for one. You can also use `autoclaw providers login <provider> --method <method>`. Noninteractive secret login also needs `--secret-stdin`; subscription login needs a terminal. Configure the OpenClaw route before saving its Gateway credential. A saved provider route is not automatically ready. Human checks show the effective method, whether a credential was found, and whether reachability was tested; use `--json` for stable values. An unverified credential source returns `local_prerequisites_ready` with a nonzero exit status rather than a false ready result.

## No default provider

Guided setup explicitly selects the primary/default provider and preserves it while adding providers. Set one directly when needed:

```bash
autoclaw providers set-default codex
```

AutoClaw will not fall back to another configured provider silently.

## Setup is waiting for input in a script

Add `--non-interactive` and pass required selections as options. `--json` and non-TTY invocation also do not prompt.

```bash
autoclaw init --non-interactive
autoclaw setup --provider codex --non-interactive
```
