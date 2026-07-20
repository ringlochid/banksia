# Design interfaces

Status: Target

This folder owns the frozen external and adapter-facing contracts for:

- MCP surface boundaries and packaging/CLI terminology
- definition registry reads and guarded writes
- task start
- public operator runtime reads and flow control
- operator-safe and node-bound MCP tool surfaces
- CLI/package/install surfaces

`tool` is the canonical runtime term. `plugin` and `bundle` are packaging or parity-wrapper terminology only.

A retained secondary search router exists for legacy entry points. This `README.md` is the canonical interfaces front door.

Use the [secondary interfaces index](INDEX.md) only when arriving from a legacy search term.

## Start Here

Read in this order:

1. [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md)
2. [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md)
3. [API Schema Appendix](api-schema-appendix.md)
4. [api-machine-catalog.yaml](api-machine-catalog.yaml)
5. [Definition Registry And Upload Contract](definition-registry-and-upload-contract.md)
6. [Role And Policy Definition Schema](role-and-policy-definition-schema.md)
7. [Plugin Tool Reference](plugin-tool-reference.md)

## Canonical Live Owners

- [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md) the two-MCP model, plugin or bundle terminology limits, OpenClaw attachment boundary, the explicit-arg v1 node-MCP bridge, and CLI ownership split
- [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md) route families, trust lanes, and stale-write guards
- [API Schema Appendix](api-schema-appendix.md) named requests, responses, shared enums, and shared nested shapes
- [api-machine-catalog.yaml](api-machine-catalog.yaml) machine-readable route and MCP tool catalog, including exact caller-facing arguments and result carriers
- [Definition Registry And Upload Contract](definition-registry-and-upload-contract.md) registry lifecycle, upload rules, and registry-read discovery for structural edits
- [Role And Policy Definition Schema](role-and-policy-definition-schema.md) authored role/policy shapes and validation rules
- [Plugin Tool Reference](plugin-tool-reference.md) tool inventory split across `operator MCP` and `node MCP`

## Supporting Surfaces

- [Human And Operator Control Surface](human-and-operator-control-surface.md)
- [CLI Surface And Operator Workflows](cli-surface-and-operator-workflows.md)
- [CLI API And Package Shape](cli-api-and-package-shape.md)
- [Definition Ingest And Upload Contract](definition-ingest-and-upload-contract.md)
- [Release And Install Strategy](release-and-install-strategy.md)
- [Distribution And Database Support Matrix](distribution-and-database-support-matrix.md)
- [Testing And Release Checklist](testing-and-release-checklist.md)

## Search-First Questions

- "Which routes are public and which are internal?" [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md)
- "Which MCP surfaces exist and how do plugin, bundle, and CLI terms split?" [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md)
- "What are the exact request/response shapes?" [API Schema Appendix](api-schema-appendix.md)
- "What exact route arguments, tool arguments, filters, sorts, tool aliases, and result carriers may a model caller use?" [api-machine-catalog.yaml](api-machine-catalog.yaml)
- "How are roles and policies discovered and uploaded into current registry revisions?" [Definition Registry And Upload Contract](definition-registry-and-upload-contract.md)
- "What tool inventory does each MCP surface expose?" [Plugin Tool Reference](plugin-tool-reference.md)
- "What is the operator boundary?" [Operator Definition And Role Boundary](operator-definition-and-role-boundary.md)
- "What CLI/package/install behavior is in scope?" [CLI API And Package Shape](cli-api-and-package-shape.md) and [Release And Install Strategy](release-and-install-strategy.md)
- "What does the root CLI actually expose day to day?" [CLI Surface And Operator Workflows](cli-surface-and-operator-workflows.md)

## Fast Route Examples

- "I want to understand how upload-triggered internal validation works for a workflow definition." Read [Definition Registry And Upload Contract](definition-registry-and-upload-contract.md) first, then the exact request/response shape in [API Schema Appendix](api-schema-appendix.md).
- "I want to start a task from a local file." Read [Definition Ingest And Upload Contract](definition-ingest-and-upload-contract.md) for file-entry rules, then [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md) for `POST /tasks/start`.
- "I want to pause or continue a live flow." Read [Human And Operator Control Surface](human-and-operator-control-surface.md) for the authority boundary, then [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md) and [API Schema Appendix](api-schema-appendix.md).
- "I want the shortest root-command list before I read route details." Start with [CLI Surface And Operator Workflows](cli-surface-and-operator-workflows.md), then read [CLI API And Package Shape](cli-api-and-package-shape.md) for the split between CLI, API, and adapter/package surfaces.
- "I want to know whether the external MCP surface may call `assign_child`." Read [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md), [Plugin Tool Reference](plugin-tool-reference.md), and [Human And Operator Control Surface](human-and-operator-control-surface.md). The answer is no: that is `node MCP`, not `operator MCP`; in v1 it uses explicit `session_key` + `task_id`.
