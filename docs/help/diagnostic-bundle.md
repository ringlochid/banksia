# Diagnostic bundle

Collect the smallest evidence that explains the failure.

## Local state

```bash
autoclaw --version
autoclaw status --json
autoclaw config show --json
autoclaw providers status
autoclaw service status --json
```

Add `autoclaw providers check <provider> --json` only when a fresh provider diagnostic is relevant. Inspect its separate authentication and reachability axes rather than assuming that a found credential source also proves model reachability.

For a failed managed service, also collect:

```bash
systemctl --user status autoclaw.service --no-pager
journalctl --user -u autoclaw.service -n 50 --no-pager
```

Review journal output locally before sharing it. A dependency or older AutoClaw release may have logged a rejected configuration value even though the current CLI redacts validation inputs.

## Server state

```bash
curl -sS http://127.0.0.1:18125/healthz
curl -sS http://127.0.0.1:18125/readyz
```

For a task problem, include the task id, current task read, operator snapshot, and the smallest relevant trace or event page. Include the human-request or command-run record when it owns the wait.

## Redact before sharing

Remove provider credentials, database passwords, private host paths, private task instructions, command output, and artifact content unless each item is necessary and safe to disclose. Preserve IDs and state names when they help correlate controller records.
