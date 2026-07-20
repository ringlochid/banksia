# Recover a broken release

Preserve evidence, identify the failed shipped surface, fix its owner, and publish a new verified version.

## Preserve

- package version, artifact type, platform, and Python version
- exact install command and error
- `autoclaw status --json` and `autoclaw config show --json`
- service status or foreground logs
- task ID, current runtime read, and task events when runtime work failed

Redact database credentials and provider secrets.

## Repair and prove

Use the smallest owner and the lane that reproduces the public failure. Package failures need a fresh installed-distribution proof outside the checkout. Database failures need the matching SQLite and PostgreSQL lanes. Runtime failures need the focused workflow E2E lane. Docs failures need `make check-docs`.

Do not use database reset, provider login, or service restart as a diagnostic shortcut. Do not replace a released file in place.
