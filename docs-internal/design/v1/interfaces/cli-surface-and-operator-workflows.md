# CLI surface and operator workflows

Status: Target

This page defines the target root CLI surface and the operator-facing OpenClaw workflow nouns.

The canonical runtime term is `tool`. `plugin` is adapter or package-wrapper terminology only and does not replace the canonical tool surfaces.

Contrast: current CLI coverage and install posture live in [CLI Surface And Config Precedence](../../../current/v1/interfaces/cli-surface-and-config-precedence.md) and [Packaging CLI And Install](../../../current/v1/interfaces/packaging-cli-and-install.md).

The output, interaction, and visual rules below are also target CLI contract. They are not proof that the current shipped parser already exposes every target flag or rich styled command flow.

## Target root command groups

- `autoclaw init`
- `autoclaw serve`
- `autoclaw onboard`
- `autoclaw configure`
- `autoclaw doctor`
- `autoclaw config ...`
- `autoclaw db ...`
- `autoclaw definitions ...`
- `autoclaw task-compose ...`
- `autoclaw openclaw ...`
- `autoclaw service ...`

## Target primary user-facing commands

- `autoclaw onboard [--install-daemon]`
- `autoclaw configure [--section openclaw|service|runtime|definitions|web]`
- `autoclaw doctor`
- `autoclaw service start`
- `autoclaw service stop`
- `autoclaw service restart`
- `autoclaw service status`
- `autoclaw db upgrade`
- `autoclaw definitions import --file <definition_path> [--overwrite reject|allow_new_revision]`
- `autoclaw definitions import`
- `autoclaw task-compose start --file <task_compose_path>`
- `autoclaw openclaw check`

## Target support and admin commands

- `autoclaw init`
- `autoclaw serve`
- `autoclaw config path`
- `autoclaw config show`
- `autoclaw openclaw setup`
- `autoclaw openclaw doctor`
- `autoclaw service install`
- `autoclaw service render`

## OpenClaw lifecycle contract

- `autoclaw doctor` remains the top-level health and repair command for local config, DB, service prerequisites, and the AutoClaw-owned OpenClaw integration slice.
- `autoclaw doctor --fix` repairs AutoClaw-owned local state plus AutoClaw-owned OpenClaw integration. It may repair local config migrations, directories, DB schema or seed drift, packaged resource drift, AutoClaw-managed service metadata, selected worker/operator agent ids in local AutoClaw config, patched OpenClaw worker/operator agent profiles, OpenClaw-managed AutoClaw MCP server definitions, and AutoClaw wrapper-owned OpenClaw objects. It must not mutate OpenClaw Gateway auth, bind, TLS, or exposure policy.
- `autoclaw init` is a low-level AutoClaw-local bootstrap primitive for automation, packaging smoke, and tests. It owns local AutoClaw config, directories, and runtime prerequisites, but it is not the normal first-run path.
- `autoclaw serve` is a low-level foreground runner for debug, host proof, and service-manager execution. It is not the primary operator lifecycle command.
- `autoclaw onboard [--install-daemon]` is the primary guided first-run command. It contains the user-facing `init` class of local setup work, fail-fast checks supported OpenClaw host state before any local config/DB/service write, selects or bootstraps the OpenClaw worker/operator agents for AutoClaw, patches those OpenClaw agent profiles for the worker/operator split, reconciles the OpenClaw-managed AutoClaw MCP server definitions plus the local wrapper material, checks and adapts to supported host-owned OpenClaw state, and can optionally install the platform-native service manager.
- `autoclaw configure [--section ...]` is the top-level targeted re-entry command for guided changes after first-run. `service` refreshes the managed service install path, `runtime` refreshes local runtime prerequisites, `definitions` re-seeds the packaged registry defaults, `web` rewrites the default local `console_origins` allowlist, and `openclaw` reapplies the AutoClaw-owned OpenClaw integration slice. It fail-fast checks OpenClaw support before any selected OpenClaw/service mutation, but it must not become a hidden runtime dispatch surface.
- `autoclaw openclaw check` is read-only verification. It may report warnings or missing prerequisites, but it does not write config, workspace state, or MCP definitions.
- `autoclaw openclaw setup` is the direct low-level baseline-write path for the AutoClaw-owned OpenClaw integration slice. It is not a blind wrapper around `openclaw setup`; it may run preflight, select or bootstrap the worker/operator agents, patch those OpenClaw agent profiles, write the OpenClaw-managed AutoClaw MCP server definitions, and reconcile AutoClaw-owned wrapper material, but it must not mutate host-owned OpenClaw Gateway policy.
- `autoclaw openclaw doctor` is dual-surface repair and remediation only. It exists for migration, repair, and cleanup of previously written AutoClaw-owned OpenClaw integration state.
- `bootstrap` is not the primary canonical noun for install, first-run, or OpenClaw reconfiguration. Reserve it for internal runtime or materialization contracts.
- live OpenClaw dispatch, wait, abort, and callback authority validation remain runtime-owned; these commands configure or verify that runtime path, but they do not own it

## Effect taxonomy

- `check` means read-only verification and diagnostics. It must not write local config, OpenClaw config, workspace material, service manager state, or database state.
- `adapt` means consume host-owned OpenClaw state at connect time without taking ownership of that state. OpenClaw binary resolution, Gateway URL, loopback status, auth mode, bind, TLS, and exposure policy are checked and adapted to when supported.
- `set` means write AutoClaw-owned defaults only. AutoClaw may set its local config, package resources, service manager metadata, the selected worker/operator agent ids in local AutoClaw config, patched OpenClaw worker/operator agent profiles, OpenClaw-managed AutoClaw MCP server definitions, the default AutoClaw wrapper profile material, and the wrapper operator contract.
- `fix` means repair state AutoClaw owns or previously wrote. It includes the same AutoClaw-owned OpenClaw integration slice, must back up or preserve user-owned state where edits are required, and must not silently reset unrelated OpenClaw host policy.

## OpenClaw support matrix

- loopback Gateway with token auth: supported and adapted at connect time.
- loopback Gateway with password auth: supported and adapted at connect time.
- loopback Gateway with explicit no-auth mode: supported with a hard warning and adapted at connect time.
- non-loopback Gateway: blocked unless later canon adds the remote identity and trust model.
- trusted-proxy auth: blocked for the AutoClaw wrapper unless later canon adds that contract.
- ambiguous auth state, missing required secret input, unresolved secret reference, or mismatched auth mode: blocked with a clear diagnostic and remediation note.
- AutoClaw commands must not run `openclaw config set gateway.auth.*` or otherwise rewrite OpenClaw Gateway auth policy.

## Service lifecycle contract

- `autoclaw service install` installs or reconciles the platform-native service manager entry for AutoClaw and should fail fast on OpenClaw support before writing managed-service state.
- `autoclaw service start|restart` should fail fast on OpenClaw support before operating on that managed service entry; `stop|status` remain managed-service control/readback actions.
- Linux uses `systemd --user` as the default user-service model. A system service may be a later explicit install mode for multi-user hosts.
- macOS uses `launchd`.
- Windows uses Scheduled Task as the first-class service-manager model, with any fallback explicitly documented by the owning implementation slice.
- the old custom detached pid-file daemon model is current-behavior contrast only and is not the target design.
- `autoclaw serve` remains the foreground process that the service manager may execute.

## CLI output and interaction rules

- `--json` is output-shape only. It does not change command ownership, write semantics, or interactive intent by itself.
- `--non-interactive` controls automation behavior. It disables guided prompts and requires the command to operate from already-resolved inputs.
- `--plain`, `--no-color`, and `NO_COLOR` disable rich styling.
- Rich styling is TTY-only. Non-TTY output must stay stable and readable without assuming ANSI-capable consumers.
- Mutating setup-style commands should show concise human progress for major phases such as config write/reuse, bind checks, database schema work, packaged definition seeding, provider reconciliation, nested provider commands, and service-manager operations.
- Progress/status lines are human output, not machine payload. `--json` must keep stdout parseable and must not mix progress lines into the JSON stream.
- Nested provider command labels should be sanitized. Raw stdin payloads, token-bearing JSON arguments, and secret values must not be printed.
- Nested provider stdout/stderr should be shown on command failure or explicit verbose output, with token, password, authorization, and API-key shaped values redacted before rendering.
- when styling is present, mirror OpenClaw's lobster palette rather than inventing a separate AutoClaw palette. At minimum keep the heading and severity roles aligned to OpenClaw's accent, success, warn, error, and muted colors.
- the frozen palette roles are: accent `#FF5A2D`, success `#2FBF71`, warn `#FFB020`, error `#E23D2D`, and muted `#8B7F77`.
- Onboarding, setup, configure, and doctor output should mirror OpenClaw's warning-first tone rather than inventing a separate AutoClaw aesthetic.

## CLI visual style lock

When TTY-rich styling is enabled, copy OpenClaw's visual grammar closely:

- terminal-native, monospace, high-contrast presentation over decorative or app-like styling
- one prominent command header area near the top, typically combining product name, version, and the current command label
- accent-colored section titles and separators rather than mixed arbitrary accent colors
- boxed or framed warning, status, and review panels for dense structured content such as doctor findings, security disclaimers, and setup notes
- aligned key/value readouts, compact lists, and dense diagnostics when a command is primarily reporting state
- emphasis on clarity and scanability over minimalism; the visual style may be information-dense as long as section boundaries stay obvious
- if a short banner, wordmark, or tagline is present, treat it as secondary flourish only; required guidance must still live in the structured headings, panels, prompts, and command output

Do not reinterpret "copy OpenClaw style" as a license to design the CLI into generic pretty output, dashboard-like cards, or a new AutoClaw-specific color language.

## Rule

Guarded definition upload remains the canonical API/tool lifecycle surface. The root CLI import surface is a local authoring front door over that registry truth rather than a replacement for it. Runtime flow control remains API/tool-first and is not frozen as a general root CLI command family. Adapter wrappers may mirror canonical routes, but they do not create a third truth surface.

Task-start wrapper rule:

- `autoclaw task-compose start --file <task_compose_path>` reads one local YAML file
- that file must parse exactly as `TaskStartRequest`
- the wrapper then submits that exact body to the same canonical backend task-start handler as `POST /tasks/start`
- launch concurrency and root-path conflict handling are backend concerns, not separate CLI semantics

CLI import rules:

- canonical definition files carry top-level `kind`, so the root CLI wrapper does not take `--kind`
- zero-arg `autoclaw definitions import` is a shallow current-working-directory scan only
- zero-arg import scans only top-level `*.yaml` files in the current working directory
- zero-arg import does not recurse into subdirectories
- zero-arg import does not scan a configured root or package-bundled root
- `--file` is the explicit local import path for the shipped wrapper
- bundle-manifest batch import, if retained in implementation, is compatibility/helper only rather than the primary frozen v1 authoring path

Removed from live canon:

- legacy directory/recursive definition-import variants
- `bootstrap` as the primary operator-facing noun for OpenClaw onboarding, setup, or reconfiguration

## Related contracts

- `cli-api-and-package-shape.md`
- `api-surface-and-trust-lane-map.md`
- `definition-ingest-and-upload-contract.md`
