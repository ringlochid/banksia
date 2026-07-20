# Integration boundary standard

Status: Reference

Use this guide when a change touches seams between backend layers, OpenClaw integration, CLI surfaces, operator lanes, node-tool lanes, or support-state readbacks.

## Core boundary rules

- keep controller-owned truth separate from provider behavior and support readbacks
- keep public surfaces separate from internal implementation helpers
- keep phase ownership explicit when several subsystems meet at one seam
- do not move business rules into adapters, routes, or support-state readers just because that is where the data arrives

## Backend boundaries

- `interfaces/http/**` owns HTTP parsing, dependency wiring, one boundary call into the owning layer, and HTTP translation only
- `interfaces/cli/**` owns command parsing, prompting, rendering, and exit-status mapping only
- `interfaces/mcp/**` owns MCP or server-facing transport wiring, tool exposure, and transport translation only
- inside `interfaces/http/**`, keep route modules under `routers/**`, keep HTTP-only support contracts and presenters under `contracts/**`, and keep shared HTTP wiring such as `router.py`, `dependencies.py`, and `errors.py` at the interface-owner root
- if older code still uses `api/**` or `cli/**`, apply the same entrypoint-thinness rules there
- do not keep DB transaction control, runtime effect-runner coordination, or controller orchestration inside interface modules unless canon names an explicit phase-bounded exception
- do not expose internal execution routing labels, package names, or internal-doc chronology in shipped API, CLI, MCP, operator, or runtime teaching strings when current product behavior can be described directly instead
- `services/**` owns orchestration, transaction-aware behavior, and domain flows only when that owner name is precise; otherwise keep orchestration under the named domain owner
- `definitions/**` owns authored-definition compilation, registry lookup, seed-definition, and related definition-domain behavior when those concerns are converged under one owner
- `runtime/**` owns runtime records, manifests, task-root materialization, prompt assembly, and controller-loop behavior named by canon
- `integrations/**` owns reusable provider substrate rather than runtime-specific controller behavior
- `persistence/**` owns persistence models and DB access surfaces; if legacy `db/**` remains, apply the same ownership rule there
- keep typed contracts near the owning domain, for example `definitions/contracts/**` and `runtime/contracts/**`; if legacy `schemas/**` remains, treat it as transitional contract ownership that must converge

## OpenClaw and support-state boundaries

- gateway/session continuity questions route to the gateway/session owner docs
- watchdog, operator lanes, node-tool lanes, and support-state readbacks route to the watchdog/operator owner docs
- session-authority simplification and same-session redispatch cleanup route to the session-authority owner docs
- public CLI/API ingest and definition-registry surfaces route to the ingest and registry owner docs
- install, onboarding, reset, package, and docs cutover route to the install and release owner docs

## Support-state rules

- support-state files explain committed truth; they do not become committed truth
- do not read support snapshots as the authority when controller-owned DB/runtime records own that answer
- do not let diagnostics-only paths become the steady-state business path

## Adapter and boundary discipline

- keep adapters thin and named for the external system they connect to
- do not hide controller decisions inside transport or adapter helpers
- do not bury route-local support models, presenters, or translators inside route-only packages; keep them under `interfaces/http/contracts/**` or another clearly named transport-contract owner
- when persisted metadata or default identifiers need to survive for operational reasons, prefer neutral product-language identifiers over internal execution-roadmap labels
- when an external integration forces dialect- or provider-specific behavior, isolate it behind a narrow persistence or adapter boundary
- when a seam crosses ownership, stop and confirm the documented owner before widening the edit

## Console frontend boundaries

The console is a browser client over controller-owned routes.

It must not become a second runtime, registry, support-state reader, or API contract owner.

Rules:

- generate TypeScript API types from the FastAPI OpenAPI schema and fail drift before relying on changed payloads
- keep one API client responsible for base URL resolution, request headers, query construction, JSON parsing, and error envelopes
- keep local admission in the API boundary: direct loopback peer, exact loopback `Host`, and exact allowed `Origin` for unsafe browser requests; do not add a browser API key, cookie, or session authority beside it
- keep one SSE client responsible for task event stream URLs, cursor resume, `Last-Event-ID` handling when used, backfill handoff, dedupe, and reset behavior
- keep runtime task list reads on `GET /runtime/tasks` until a real `/control/tasks` list route exists
- keep selected task, snapshot, trace, events, human requests, and command runs on `/control/tasks/{task_id}/*`
- keep stored definition browsing on `/definitions/*`
- keep flat definition draft create/read/save/delete/validate/publish on `/authoring/*`
- keep task launch on `POST /tasks/start`
- do not reconstruct runtime chronology from snapshot, trace, observability refs, support files, logs, screenshots, or local browser state when `task_event` is the replayable source
- do not reconstruct human-request currentness or command-run state from support files, logs, missing buttons, or local UI memory
- do not use `continue` for human-request resolution or command-run completion; use the dedicated control routes
- do not turn OpenAPI-generated types into edited source; add view-model mappers when render shape differs from controller shape
- do not let React, Tailwind, route names, or component names leak into runtime docs, provider docs, backend contracts, or API schemas

View-model boundaries:

- API response types describe controller payloads
- view-models describe render-ready facts, sorted rows, grouped event summaries, selected item state, and legal affordance shape
- components render view-models and local UI state, not raw controller rows
- mutations invalidate or update view-model state only after controller acknowledgement or event-stream readback

Design handoff boundaries:

- design repo charters, static HTML, screenshots, and shared CSS define visual language, interaction cadence, and expected states
- implementation extracts reusable console tokens, primitives, layouts, and state fixtures from the handoff instead of copying prototype page code
- `apps/console/src/styles/tokens.css` owns the implementation token vocabulary and uses the `--ac-*` namespace even when the design prototype uses a different prefix
- backend current docs, V2 contracts, OpenAPI, and route tests define legal routes, field names, state names, actions, and currentness
- when design handoff and controller truth disagree, patch the contract or the design handoff before encoding the behavior in components

## Review checklist

- which layer owns the behavior that changed
- did the diff move logic toward the correct owner or away from it
- did a support or transport surface start acting like the system of record
- did the change widen into another phase or public surface without explicit approval
- did console code keep API/SSE, view-model, component, and design-token responsibilities separate
- did console code preserve the route-family split instead of hiding it behind a fake merged client contract
