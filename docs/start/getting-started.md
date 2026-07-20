# Install and set up AutoClaw

This is the shortest local path from installation to a running controller.

## Install

Use an isolated tool environment:

```bash
pipx install autoclaw
```

You can use `uv tool install autoclaw` instead. Install `autoclaw[postgres]` only when you plan to use Postgres.

## Create local state

```bash
autoclaw init
```

On a terminal, `init` shows the recommended local paths, database, and loopback API address before it writes. It creates the local configuration, prepares the controller database, and installs the packaged definitions. It binds the server to `127.0.0.1:18125` by default.

Rerunning `init` keeps and verifies an existing config by default. Replacing config requires an explicit selection and confirmation. It never resets a mismatched database; use `autoclaw db reset` only when destructive replacement is intended.

Use `--data-dir`, `--database-url`, `--host`, or `--port` when the defaults do not fit your machine. Keep the server on loopback for the supported local lane.

## Configure a provider

Start the provider guide:

```bash
autoclaw setup
```

The guide asks for the primary/default provider, checks it, configures authentication when needed, checks again, and asks whether to add providers. Codex and Claude offer subscription login or API key. OpenClaw asks for Gateway URL/profile and token or password; it is selectable and may be the default, but its Gateway and compatibility MCP setup remain experimental and user-managed.

To change the default directly later, run:

```bash
autoclaw providers set-default claude
```

For scripts, use `--non-interactive`. Non-interactive setup configures one selected route; login and checking remain explicit. Secret login also requires an explicit method and `--secret-stdin`:

```bash
autoclaw init --non-interactive
autoclaw setup --provider codex --non-interactive
printf '%s\n' "$OPENAI_API_KEY" | \
  autoclaw providers login codex --method api-key --secret-stdin
autoclaw providers check codex
```

Run `autoclaw providers login codex --method subscription` directly on an interactive terminal when you want the provider-native browser or device login.

See [configuration and settings](configuration-and-settings.md) for provider behavior and authentication.

## Run AutoClaw

Start the foreground server:

```bash
autoclaw serve
```

Or install the Linux user service:

```bash
autoclaw service install
autoclaw service status
```

Open `http://127.0.0.1:18125/`. The packaged console, HTTP API, and MCP surfaces share this local server.

## Check local state

```bash
autoclaw status
autoclaw config show --json
autoclaw providers status
```

These commands read local state. Use `autoclaw providers check <provider>` for a fresh bounded diagnostic. The check must find a supported effective credential source before it reports ready. It never starts an agent, so Codex/Claude model reachability remains deferred until the first task and is shown as `not tested`.

Next, [start a task](start-a-task.md).
