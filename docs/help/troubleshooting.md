# Troubleshooting

Start with read-only checks:

```bash
autoclaw status --json
autoclaw config show --json
autoclaw providers status
autoclaw service status --json
curl -sS http://127.0.0.1:18125/healthz
curl -sS http://127.0.0.1:18125/readyz
```

Run `autoclaw providers check <provider> --json` when a fresh provider diagnostic matters. Inspect the separate authentication and reachability axes. For Codex and Claude, a supported credential source may be found while model reachability remains `not_checked` because the check sends no model request.

| Symptom | Help page |
| --- | --- |
| install, `init`, or `setup` fails | [Install and setup problems](install-and-onboard.md) |
| server, service, health, or readiness fails | [Service and health problems](service-and-health.md) |
| provider check or OpenClaw fails | [Provider and OpenClaw problems](openclaw-integration.md) |
| launch is rejected | [Task start failures](task-start-failures.md) |
| task is waiting, paused, or unclear | [Task stuck or waiting](task-stuck-or-waiting.md) |
| Postgres connection fails | [Postgres and database problems](postgres-and-database.md) |

Do not delete the data directory, edit controller rows, or change generated task files before reading the failing state. Preserve the exact error and use the [diagnostic bundle](diagnostic-bundle.md) when you need to report it.
