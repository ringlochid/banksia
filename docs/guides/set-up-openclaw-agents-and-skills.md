# Configure OpenClaw tools

OpenClaw is an experimental, user-managed provider lane. AutoClaw does not inject or maintain its MCP configuration.

## Keep worker and operator access separate

Configure a worker profile for bounded node work. Give it the compatible node MCP tools needed by its node kind and no operator tools. Do not expose parent-only tools to a worker.

If you use an OpenClaw operator profile, give it operator MCP access and no node-execution tools. Operator authority can inspect and steer every task, so keep that profile trusted and separate.

## Use the compatibility contract

Add the compatibility MCP server to `openclaw.json` using the current reference configuration. Because this is a static provider configuration, each node call supplies full `task_id` and `dispatch_id` selectors. The controller rejects stale or mismatched selectors.

Node MCP is the runtime boundary. OpenClaw output and provider state are not task truth.

Check the provider after any OpenClaw configuration change:

```bash
autoclaw providers check openclaw
```

See [use the experimental OpenClaw provider](../start/prepare-openclaw.md) and the [OpenClaw integration reference](../reference/operator/openclaw-integration-boundary.md).
