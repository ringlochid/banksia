# Codex support and compatibility

Status: Target

This page owns the local managed support contract for the `codex` route.

## Support status and packaging

Codex is a managed target provider. The supported base AutoClaw distribution includes the tested official Codex SDK integration and its pinned/bundled runtime; a separately installed global `codex` CLI is not required.

An explicit custom runtime may be added only as an advanced override that passes the same pinned adapter conformance. Installation alone does not configure or authenticate Codex.

## Authentication and native home

Codex authentication remains provider-owned. `autoclaw providers login codex` delegates to the supported native login flow for ChatGPT or API authentication. Codex stores and refreshes credentials under its own home or OS credential store; AutoClaw never reads, copies, prints, normalizes, or persists the credential payload.

Status, check, login, and runtime resolve the same service identity and default Codex home. A shell-only `CODEX_HOME` override does not redirect the managed route. A login under a different user/home does not make the runtime route ready.

## Configuration inheritance

The adapter inherits normal Codex user and trusted-project configuration, including native model/reasoning choices, compaction, project instructions, `AGENTS.md`, skills, and user MCP servers.

AutoClaw applies one nonpersistent dispatch overlay only:

- exact task workspace/cwd;
- exact separate instruction and input lanes;
- one private managed Node MCP connection with a fresh bearer credential;
- the exact role-scoped Node tool allowlist;
- noninteractive approval behavior;
- resolved provider-native tool/network policy; and
- optional sparse model/effort override.

The overlay never rewrites user or project `config.toml` and never stores the managed MCP credential in Codex configuration.

## Dynamic MCP attachment

For each provider-start attempt, AutoClaw dynamically attaches the managed MCP URL, authorization header, and exact enabled-tool list to the new Codex thread/turn invocation through the supported app-server/SDK request override.

The exact wire fields belong to the pinned-version adapter conformance because provider protocol shapes may evolve. These invariants do not:

- the attachment is per invocation and nonpersistent;
- the model-visible schemas contain semantic fields only;
- a worker is not given parent/root-only tools;
- concurrent dispatches use different credentials and ceilings; and
- every retry receives a fresh credential even when it keeps the same dispatch ID.

## Start, continuity, and stop

One AutoClaw dispatch starts one Codex turn. A thread ID or active turn handle may remain provider-private for optional continuity and precise interruption, but it is not generic controller state or Node authentication.

Every start receives both complete current request lanes. If safe continuity is unavailable, the adapter starts a fresh thread; no compact resume prompt or provider-history dependency is allowed.

`start()` returns on documented turn acceptance. Provider output, final response, EOF, token events, and native tool events are ignored for controller progression.

`stop(dispatch_id)` makes one bounded app-server interruption request when supported. Runtime does not wait for a provider final response or drain and proceeds after unsupported, failed, or timed-out stop. If the SDK requires stream consumption for resource health, the adapter owns it privately without turning it into a runtime fence.

## Noninteractive policy

Provider-native approval requests must never wait for an unconsumed app-server UI. The adapter applies the resolved machine policy to native tools, and AutoClaw human direction goes only through `open_human_request` when capability permits it.

Full native-tool access does not grant parent/root Node tools, controller command runs, or human-request capability.

## Status and check

Passive status may report enabled/default state, installed adapter/runtime versions, custom runtime path, effective Codex home/config sources, and locally observable authentication presence without credential contents.

`autoclaw providers check codex` may perform documented non-agent installation, configuration, auth/reachability, workspace-policy, and deterministic MCP prerequisite checks. It does not create a Codex thread/turn, dispatch, or binding and does not call Node tools.

A failed check blocks no global service. A dispatch that has already committed retries provider-origin start failure under the runtime contract rather than consuming a cached check result.

## Required proof

- dynamic per-dispatch MCP attachment without config mutation;
- exact worker versus parent/root tool exposure;
- two-lane request delivery on fresh and continuity-assisted starts;
- noninteractive native approval behavior;
- acceptance and definite/uncertain failure classification;
- one bounded interrupt attempt with no runtime drain gate;
- service-identity/native-home consistency; and
- no credential, provider-output, or private-binding leakage.

## External basis

- [Codex SDK](https://developers.openai.com/codex/sdk/)
- [Codex app-server](https://developers.openai.com/codex/app-server/)
- [Codex authentication](https://developers.openai.com/codex/auth/)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)

## Related contracts

- [Provider support and compatibility](provider-support-and-compatibility.md)
- [Provider CLI and check](provider-cli-and-check.md)
- [Codex app-server adapter](../architecture/adapters/codex-app-server.md)
- [Managed Node MCP binding](../architecture/managed-node-mcp-binding.md)
