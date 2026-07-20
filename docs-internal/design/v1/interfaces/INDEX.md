# Interfaces Index

Status: Reference

Use this page when you arrive from a legacy search term or old link and need the canonical interfaces owner quickly.

The canonical live front door for this subtree is the [Interfaces front door](README.md). Use that page for owner authority and read order.

## Fast route

- interfaces front door and owner routing: [Interfaces front door](README.md)
- MCP, plugin, and CLI boundary: [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md)
- API trust lanes and route families: [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md)
- exact request and response shapes: [API Schema Appendix](api-schema-appendix.md)
- machine-readable route and tool catalog: [api-machine-catalog.yaml](api-machine-catalog.yaml)
- registry lifecycle and upload rules: [Definition Registry And Upload Contract](definition-registry-and-upload-contract.md)
- role and policy schema: [Role And Policy Definition Schema](role-and-policy-definition-schema.md)
- operator and node tool inventory: [Plugin Tool Reference](plugin-tool-reference.md)

Compatibility rule: `tool` is the canonical runtime term. `plugin` and `bundle` are packaging or parity-wrapper terms only.

## Routes, Lanes, And Guards

- "Which MCP surfaces exist and how do they relate to plugin, bundle, and CLI terms?" [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md)
- "Which routes are public versus internal?" [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md)
- "Which stale-write guards are canonical?" [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md)
- "What are the exact route payloads?" [API Schema Appendix](api-schema-appendix.md)
- "What exact route arguments, tool arguments, sorts, tool aliases, and result carriers may a model caller use?" [api-machine-catalog.yaml](api-machine-catalog.yaml)

## Definition Registry

- "How do definitions upload, validate internally, and become current revisions?" [Definition Registry And Upload Contract](definition-registry-and-upload-contract.md)
- "What do role and policy definitions look like?" [Role And Policy Definition Schema](role-and-policy-definition-schema.md)
- "How do local files ingest into the registry or task start?" [Definition Ingest And Upload Contract](definition-ingest-and-upload-contract.md)

## Operator And Adapter Surfaces

- "What can a human/operator do?" [Human And Operator Control Surface](human-and-operator-control-surface.md)
- "What is the operator boundary?" [Operator Definition And Role Boundary](operator-definition-and-role-boundary.md)
- "What tool inventory does each MCP surface expose?" [Plugin Tool Reference](plugin-tool-reference.md)
- "How does v1 node MCP authorize calls?" [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md), [Plugin Tool Reference](plugin-tool-reference.md), and [API Schema Appendix](api-schema-appendix.md)

## Common Concrete Scenarios

- "I have a local workflow file and want to know the file-entry rules before upload." Use [Definition Ingest And Upload Contract](definition-ingest-and-upload-contract.md) for file-entry rules, then [Definition Registry And Upload Contract](definition-registry-and-upload-contract.md) for upload and internal-validation lifecycle, and [API Schema Appendix](api-schema-appendix.md) for exact request and response shapes.
- "I have a running flow and want the current summary without touching node-level state." Use the operator lane described in [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md) and [Human And Operator Control Surface](human-and-operator-control-surface.md).
- "I need to know whether an automation client is allowed to use parent/root tools." Read [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md), [Plugin Tool Reference](plugin-tool-reference.md), and [Operator Definition And Role Boundary](operator-definition-and-role-boundary.md). Standard operator-safe automation is task-scoped only; v1 `node MCP` uses explicit `session_key` + `task_id` for parent/root tools.
- "I need exact examples of compact surfaced refs or checkpoint/assignment payloads." Start with [API Schema Appendix](api-schema-appendix.md).

## CLI, Package, And Release

- "What does the CLI own?" [CLI Surface And Operator Workflows](cli-surface-and-operator-workflows.md)
- "How do CLI, API, and package boundaries split?" [CLI API And Package Shape](cli-api-and-package-shape.md)
- "What is the install and release posture?" [Release And Install Strategy](release-and-install-strategy.md)
- "What is the frozen support matrix?" [Distribution And Database Support Matrix](distribution-and-database-support-matrix.md)
- "What release/testing evidence is required?" [Testing And Release Checklist](testing-and-release-checklist.md)

## Historical Search Terms

If you arrive searching for:

- callback-era worker surfaces
- `parent_gate`
- public child retry or reassignment control
- `scope_key`
- `instruction_text`
- plugin-first tool model
- shared mixed MCP catalog

start with:

- [MCP Plugin And CLI Boundary](mcp-plugin-and-cli-boundary.md)
- [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md)
- [Plugin Tool Reference](plugin-tool-reference.md)
- [Role And Policy Definition Schema](role-and-policy-definition-schema.md)
