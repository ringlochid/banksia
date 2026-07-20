# Run the design target on local SQLite

Status: Target

This page defines the frozen local SQLite lane.

## Procedure

1. Install or update the package: `pipx install autoclaw`
2. Run onboarding: `autoclaw onboard`
3. Keep SQLite as the default local DB, or set `AUTOCLAW_DATABASE_URL=sqlite+aiosqlite:///...`
4. Run migrations through the package surface: `autoclaw db upgrade`
5. Confirm health: `autoclaw doctor`
6. Verify the OpenClaw integration side without writing: `autoclaw openclaw check`
7. Start the managed service: `autoclaw service start`

`autoclaw init` remains available as a low-level AutoClaw-local bootstrap primitive for automation, tests, and package smoke. `autoclaw serve` remains available as a foreground debug runner and as the process a service manager may execute.

## Lane rule

SQLite is the local-first smoke lane. It is not the strong concurrency or release-proof lane.
