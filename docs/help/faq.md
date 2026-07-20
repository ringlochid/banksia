# FAQ

## Does AutoClaw require OpenClaw?

No. Codex, Claude, and OpenClaw are selectable providers. OpenClaw remains experimental, and the user still owns its Gateway, agent/tool policy, and compatibility MCP configuration.

## Which provider becomes the default?

Guided setup asks for the primary/default provider. With direct commands, the first configured provider becomes the default when none exists. Change it with `autoclaw providers set-default <provider>`. AutoClaw does not silently fall back.

## Does a provider's final response complete the task?

No. AutoClaw accepts runtime truth through controller-validated MCP operations. Provider output and terminal status are not assignment success.

## Why can a boundary return before the next agent starts?

The boundary transaction commits first and returns. An asynchronous handler then rereads the exact source, writes the successor's two request files, opens the successor, and starts its provider. This preserves the logical order without making the current tool call wait.

## Are generated task files authoritative?

No. They are materialized views of controller records. Use them for readable context and evidence; use current controller readbacks for authority.

## What is the difference between task events and current state?

Events are ordered history. Current task, dispatch, human-request, and command-run rows answer what is true now.

## Why does the browser reject an unusual Host or Origin?

The supported console is a loopback same-origin application. Exact local Host and Origin checks prevent a browser request from pretending to target a different host. Keep the server local.
